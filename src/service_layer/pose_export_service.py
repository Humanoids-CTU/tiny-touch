"""Publishing the Pose export after a Pose save. No Tk and no SQLite here.

The GUI saves the Pose workspace to `state/<video>_pose.db` first (the source
of truth), then calls `run_pose_export`. A failure here never touches the
database: the GUI reports it as `SaveOutcome.EXPORT_STALE`.

Order of calls, all but the last on the Tk thread:

    1. has_unexported_changes(labels, frames)   BEFORE the database save, which
                                                clears both dirty trackers
    2. csv_can_be_reused(paths, published_csv)
    3. capture_content(labels, frames)          only when the CSV is rewritten
    4. run_pose_export(...)                     worker thread when it writes the
                                                CSV; it only sees detached data

The CSV is skipped only when it provably cannot be stale: this session
published it, nothing was edited since, and the file still has the size and
modification time of that export. The metadata is rewritten on every save
(labeling time and Special Zones change without label edits).
"""
import copy
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from typing import Optional

from adapters.pose_export_writer import write_pose_export_csv, write_pose_export_metadata
from domain.pose import PoseLabels, PoseTables
from domain.pose_setup import PoseCodingSetup
from domain.project import ProjectPaths
from service_layer.save_service import CsvStamp, csv_stamp

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PoseExportMetadata:
    """Non-tabular export inputs, gathered on the Tk thread."""
    program_version: object
    video_name: str
    labeling_mode: str
    coding_setup: PoseCodingSetup
    special_zones: tuple
    special_zones_note: Optional[str]
    labeling_time_seconds: Optional[float]


@dataclass(frozen=True)
class PoseExportContent:
    """Detached per-frame data for the CSV; safe to read on a worker thread."""
    tables: PoseTables
    shared_frames: dict


def has_unexported_changes(labels: PoseLabels, frames) -> bool:
    """True when a label, note or parameter changed since the last database save.

    Call it BEFORE saving: a successful save clears both trackers. Every save
    is followed by an export attempt, so "changed since the last save" covers
    "changed since the last export"; a failed export drops the published stamp.
    """
    return labels.has_pending_changes or any(
        isinstance(bundle, dict) and bundle.get("Changed") for bundle in frames.values())


def capture_content(labels: PoseLabels, frames) -> PoseExportContent:
    """Copy what the CSV needs, so later edits cannot tear a running export."""
    return PoseExportContent(labels.tables(), copy.deepcopy(frames))


def csv_can_be_reused(paths: ProjectPaths, published_csv: Optional[CsvStamp]) -> bool:
    """True when the published CSV still is the file this session exported."""
    return published_csv is not None and csv_stamp(paths.pose_export_csv) == published_csv


def run_pose_export(paths: ProjectPaths, fps, total_frames, metadata: PoseExportMetadata,
                    content: Optional[PoseExportContent]) -> Optional[CsvStamp]:
    """Publish the Pose export and return the stamp of the published CSV.

    `content=None` keeps the published CSV and rewrites only the metadata.
    Both files are staged first. The CSV replaces the published one before the
    metadata, and a failed replace restores what was already replaced.
    """
    os.makedirs(paths.export_dir, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".pose-export-", dir=paths.export_dir) as staging:
        publish = []
        if content is not None:
            staged_csv = os.path.join(staging, "export.csv")
            write_pose_export_csv(staged_csv, content.tables, content.shared_frames,
                                  total_frames=total_frames, frame_rate=fps)
            publish.append((staged_csv, paths.pose_export_csv))
        else:
            logger.debug("Pose export CSV unchanged since the last save; keeping %s",
                         paths.pose_export_csv)
        staged_meta = os.path.join(staging, "metadata.json")
        write_pose_export_metadata(
            staged_meta,
            program_version=metadata.program_version,
            video_name=metadata.video_name,
            labeling_mode=metadata.labeling_mode,
            frame_rate=fps,
            total_frames=total_frames,
            coding_setup=metadata.coding_setup,
            special_zones=metadata.special_zones,
            special_zones_note=metadata.special_zones_note,
            labeling_time_seconds=metadata.labeling_time_seconds,
        )
        publish.append((staged_meta, paths.pose_export_metadata))
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
    return csv_stamp(paths.pose_export_csv)
