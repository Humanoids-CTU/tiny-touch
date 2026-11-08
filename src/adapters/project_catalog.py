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
    def title(self):
        return self.paths.video_name


def list_projects(base_dir=DATA_DIR, videos_dir=VIDEOS_DIR):
    entries = []
    for folder in sorted(Path(base_dir).glob("*")):
        paths = ProjectPaths(folder.name, str(base_dir))
        if not Path(paths.state_db).is_file():
            continue
        try:
            connection = sqlite3.connect(Path(paths.state_db).resolve().as_uri() + "?mode=ro", uri=True)
            try:
                meta = dict(connection.execute("SELECT key, value FROM meta"))
            finally:
                connection.close()
            source = meta.get(SOURCE_META)
            if source and not Path(source).is_file():
                source = None
            if not source:
                # Old databases have no association: offer only an unambiguous stem.
                matches = [p for p in Path(videos_dir).glob("*") if p.stem == paths.original.video_name and p.is_file()]
                source = str(matches[0]) if len(matches) == 1 else None
            setup = json.loads(meta.get("coding_setup", "null"))
            template = setup.get("template", DEFAULT_TEMPLATE) if isinstance(setup, dict) else meta.get("template", DEFAULT_TEMPLATE)
            validate_template(template)
            thumb = Path(paths.frames_dir) / "frame0.jpg"
            entries.append(LibraryEntry(paths, source, template, meta.get("preparation_state", "needs_review"), str(thumb) if thumb.is_file() else None, setup.get("name", "") if isinstance(setup, dict) else ""))
        except (sqlite3.Error, OSError, ValueError):
            # A damaged project stays visible with an explicit unavailable status.
            entries.append(LibraryEntry(paths, None, DEFAULT_TEMPLATE, "unavailable", None))
    return entries
