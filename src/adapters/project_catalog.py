"""Read-only project library discovery; working databases remain authoritative."""
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import json

from domain.project import ProjectPaths, VIDEOS_DIR, DATA_DIR
from domain.templates import DEFAULT_TEMPLATE, validate_template

SOURCE_META = "source_video_path"

@dataclass(frozen=True)
class LibraryEntry:
    paths: ProjectPaths
    source: str | None
    template: str
    preparation_state: str
    thumbnail: str | None
    setup_name: str = ""

    @property
    def annotation_type(self):
        return self.paths.annotation_type

    @property
    def title(self):
        return self.paths.video_name


def list_projects(base_dir=DATA_DIR, videos_dir=VIDEOS_DIR):
    entries = []
    candidates = (ProjectPaths(folder.name, str(base_dir), kind)
                  for folder in sorted(Path(base_dir).glob("*")) for kind in ("Touch", "Pose"))
    for paths in candidates:
        if not Path(paths.state_db).is_file():
            continue
        try:
            if paths.annotation_type == "Pose":
                from adapters.pose_sqlite_repo import PoseSqliteRepository
                meta = PoseSqliteRepository.inspect_metadata(paths.state_db)
            else:
                meta = _touch_metadata(paths.state_db)
            source = meta.get(SOURCE_META)
            if source and not Path(source).is_file():
                source = None
            if not source:
                # Old databases have no association: offer only an unambiguous stem.
                matches = [p for p in Path(videos_dir).glob("*") if p.stem == paths.original.video_name and p.is_file()]
                source = str(matches[0]) if len(matches) == 1 else None
            setup = json.loads(meta.get("coding_setup", "null"))
            template = setup.get("template", DEFAULT_TEMPLATE) if isinstance(setup, dict) else meta.get("template", DEFAULT_TEMPLATE)
            if paths.annotation_type == "Pose":
                from domain.pose_setup import PoseCodingSetup
                if setup is not None:
                    PoseCodingSetup.from_dict(setup)
                template = "alternate"
            else:
                from domain.annotation_type import annotation_type
                if annotation_type(meta.get("annotation_type", "Touch")) != "Touch":
                    raise ValueError("Project kind disagrees with its database")
                validate_template(template)
            thumb = Path(paths.frames_dir) / "frame0.jpg"
            entries.append(LibraryEntry(paths, source, template, meta.get("preparation_state", "needs_review"), str(thumb) if thumb.is_file() else None, setup.get("name", "") if isinstance(setup, dict) else ""))
        except (sqlite3.Error, OSError, ValueError):
            # A damaged project stays visible with an explicit unavailable status.
            entries.append(LibraryEntry(paths, None, DEFAULT_TEMPLATE, "unavailable", None))
    return entries


def _touch_metadata(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return dict(connection.execute("SELECT key, value FROM meta"))
    finally:
        connection.close()
