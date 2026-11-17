"""
service_layer/save_service.py
The save Unit of Work, extracted from LabelingApp.save_data. No Tk here:
the GUI orchestrates the modal progress dialog + worker thread and calls
these steps in order:

    1. persist_state(repo, ...)    — dirty frames -> state DB, ONE transaction
                                     (UI thread; the repo is Tk-thread-bound)
    2. snapshot = build_save_snapshot(frames)
    3. run_export(snapshot, ...)   — metadata sidecar + diagram, and the export
                                     CSV unless it is provably unchanged
                                     (the GUI runs THIS on its worker thread)
    4. clear_clean_flags(frames, snapshot)   — only after step 3 succeeded

The GUI reports the result as a `SaveOutcome`: step 1 failing means the
annotations are not on disk; step 3 failing means they are (the state DB is
the source of truth) but the export files are out of date.

Concurrency invariant (pinned by tests): the snapshot is a deep copy taken
BEFORE the worker-thread export, and afterwards `Changed` is cleared ONLY
for bundles still equal to their snapshot (`b == snapshot.get(f)`), so a
frame edited DURING the export stays dirty and reaches the next save. The
same flags drive the CSV skip in `run_export`: a frame still dirty forces a
CSV rewrite.

Thread invariant: step 1 touches the SQLite connection and MUST run on the Tk
thread; step 3 only ever sees the immutable deepcopy and writes through
`adapters.export_writer`, which is file-based and repository-free. The
repository enforces this itself (`SqliteRepository._check_thread`).
"""

import copy
import os
import logging
import json
import shutil
import tempfile
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple

from adapters.export_writer import export_from_unified, write_export_metadata
from adapters.sqlite_repo import SqliteRepository
from domain.model import FrameBundle
from domain.coding_setup import CodingSetup
from domain.project import ProjectPaths
from domain.templates import validate_template


logger = logging.getLogger(__name__)

# (size in bytes, modification time in ns) of the export CSV a save published.
CsvStamp = Tuple[int, int]


class SaveOutcome(Enum):
    """What a save achieved. Only NOT_SAVED can lose annotations."""
    SAVED = "saved"                # state DB written, export files updated
    EXPORT_STALE = "export_stale"  # state DB written, export files NOT updated
    NOT_SAVED = "not_saved"        # state DB not written


@dataclass(frozen=True)
class MetadataInputs:
    """Non-tabular export inputs, gathered on the UI thread (button labels are
    Tk reads; labeling time is clocked before the export starts)."""
    program_version: object
    video_name: str
    labeling_mode: str
    special_zones_list: Optional[list]
    param_labels: Optional[dict]
    limb_param_labels: Optional[dict]
    labeling_time_seconds: Optional[float]
    template: Optional[str] = None
    special_zones_note: Optional[str] = None
    zone_labels: Optional[dict] = None
    coding_setup: CodingSetup | None = None


def load_special_zones(repo: Optional[SqliteRepository]):
    """Special-zone list for the export metadata, or None without a repo.

    Reproduces the retired sidecar reader `extract_zones_from_file` exactly
    (set-deduplicated, UNSORTED, a multi-zone dot contributing its whole
    comma-joined string as one entry) because
    `export/<video>_metadata.json` is a frozen contract.
    """
    return repo.special_zone_list() if repo is not None else None


def load_special_zones_note(repo: Optional[SqliteRepository]) -> Optional[str]:
    """Project-wide Special Zones note for the export metadata, or None."""
    return repo.special_zones_note() if repo is not None else None


def build_save_snapshot(frames: Dict[int, FrameBundle]) -> Dict[int, FrameBundle]:
    """Deep-copy the live frames dict BEFORE the worker-thread export so
    concurrent edits can't tear the export nor be wrongly marked clean."""
    return copy.deepcopy(frames)


def persist_state(repo: SqliteRepository, total_frames: int,
                  frames: Dict[int, FrameBundle]) -> int:
    """Write every dirty frame to the state DB in ONE transaction.

    Replaces the old changed-only journal append. Same dirty tracker
    (`Changed`), but the write is now an UPSERT: idempotent (a second identical
    save changes nothing) and atomic (no torn tail to repair, no compaction to
    schedule). Returns the number of frames written.
    """
    return repo.save_frames(frames, total_frames)


def csv_stamp(path) -> Optional[CsvStamp]:
    """(size, modification time in ns) of a file, or None when it is missing."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return stat.st_size, stat.st_mtime_ns


def _published_metadata_is_current(paths: ProjectPaths) -> bool:
    try:
        with open(paths.export_metadata, encoding="utf-8") as stream:
            previous = json.load(stream)
        version = (previous.get("Export Format Version"),
                   previous.get("Metadata Format Version", 1))
    except (OSError, ValueError, AttributeError):
        return False
    return version == (2, 2)


def _csv_can_be_reused(snapshot: Dict[int, FrameBundle], paths: ProjectPaths,
                       published_csv: Optional[CsvStamp]) -> bool:
    """True only when the published CSV cannot be stale.

    `published_csv` is the stamp this session got back from the last
    successful `run_export` (the GUI drops it on load, unload and failure).
    `Changed` is cleared only after a successful export, so "no dirty frame
    in the snapshot" means no frame changed since that export. The stamp
    check catches a CSV deleted or replaced outside the app.
    """
    return (
        published_csv is not None
        and not any(isinstance(b, dict) and b.get("Changed") for b in snapshot.values())
        and csv_stamp(paths.export_csv) == published_csv
    )


def run_export(snapshot: Dict[int, FrameBundle],
               paths: ProjectPaths,
               fps,
               metadata: MetadataInputs,
               total_frames: int,
               *,
               published_csv: Optional[CsvStamp] = None) -> CsvStamp:
    """Publish the export set (CSV, metadata, diagram) from the immutable
    snapshot. Runs on the GUI's worker thread.

    The metadata and diagram are written every time. The CSV is rewritten
    unless `_csv_can_be_reused` proves the published one is still exact, and
    always when an older export pair has to be archived first. Returns the
    stamp of the published CSV, to pass back as `published_csv` next time.
    """
    template = validate_template(metadata.template)
    os.makedirs(paths.export_dir, exist_ok=True)
    archive_previous = (os.path.exists(paths.export_csv)
                        and not _published_metadata_is_current(paths))
    write_csv = archive_previous or not _csv_can_be_reused(snapshot, paths, published_csv)
    with tempfile.TemporaryDirectory(prefix=".export-", dir=paths.export_dir) as staging:
        staged_csv = os.path.join(staging, "export.csv")
        staged_meta = os.path.join(staging, "metadata.json")
        staged_diagram = os.path.join(staging, os.path.basename(paths.export_diagram))
        if write_csv:
            export_from_unified(
                snapshot,
                staged_csv,
                metadata.program_version,
                metadata.video_name,
                metadata.labeling_mode,
                fps,
                metadata.special_zones_list,
                total_frames=total_frames,
                param_labels=metadata.param_labels,
                limb_param_labels=metadata.limb_param_labels,
            )
        else:
            logger.debug("export CSV unchanged since the last save; keeping %s", paths.export_csv)
        write_export_metadata(
            meta_path=staged_meta,
            template=template,
            program_version=metadata.program_version,
            video_name=metadata.video_name,
            labeling_mode=metadata.labeling_mode,
            frame_rate=fps,
            special_zones_list=metadata.special_zones_list,
            special_zones_note=metadata.special_zones_note,
            param_labels=metadata.param_labels,
            limb_param_labels=metadata.limb_param_labels,
            labeling_time_seconds=metadata.labeling_time_seconds,
            zone_labels=metadata.zone_labels,
            coding_setup=metadata.coding_setup,
            diagram_path=staged_diagram,
        )
        if archive_previous:
            archive = os.path.join(paths.export_dir, "legacy-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
            os.makedirs(archive)
            for existing in (paths.export_csv, paths.export_metadata, paths.export_diagram):
                if os.path.exists(existing):
                    shutil.copy2(existing, archive)
        # Metadata goes LAST: it names the diagram by hash and describes the
        # CSV, so once a new metadata file is visible, the files it describes
        # are already in place. A failure undoes only what was replaced.
        publish = [(staged_diagram, paths.export_diagram)]
        if write_csv:
            publish.append((staged_csv, paths.export_csv))
        publish.append((staged_meta, paths.export_metadata))
        backups = {}
        for _, target in publish:
            if os.path.exists(target):
                backup = os.path.join(staging, os.path.basename(target) + ".previous")
                shutil.copy2(target, backup)
                backups[target] = backup
        replaced = []
        try:
            for staged, target in publish:
                os.replace(staged, target)
                replaced.append(target)
        except OSError:
            for target in reversed(replaced):
                if target in backups:
                    os.replace(backups[target], target)
                else:
                    os.remove(target)
            raise
    return csv_stamp(paths.export_csv)



def clear_clean_flags(frames: Dict[int, FrameBundle],
                      snapshot: Dict[int, FrameBundle]) -> None:
    """Clear `Changed` ONLY for bundles still identical to their exported
    snapshot — a frame edited during the export stays dirty."""
    for f, b in frames.items():
        if (
            isinstance(b, dict)
            and b.get("Changed")
            and b == snapshot.get(f)
        ):
            b["Changed"] = False
    logger.debug("cleared clean bundle flags after save")
