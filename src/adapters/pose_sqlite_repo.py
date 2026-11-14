"""Versioned Pose-only SQLite state, confined to the creating thread.

Existing files are preflighted read-only before opening for writing. Saves replace
all sparse labels in one transaction; deletions cannot leave stale rows behind.
"""

from contextlib import closing
from pathlib import Path
import sqlite3
import json
import math
from domain.pose_setup import PoseCodingSetup
import threading

from domain.pose import (
    ZoneEvent, PoseLabels, PoseSnapshot, ScaleKind, ScaleLabel, ScaleSource,
)


POSE_KIND = "tinytouch.pose"
SCHEMA_VERSION = "3"
BUSY_TIMEOUT_MS = 5000
_COLUMNS = {
    "project_meta": ("key", "value"),
    "shared_frames": ("frame", "note", "params"),
    "special_zone_points": ("dot_id", "x", "y", "zones"),
    "pose_meta": ("key", "value"),
    "zone_events": ("frame", "zone", "event"),
    "frame_quality": ("frame", "value"),
    "scale_labels": ("frame", "kind", "value", "source"),
}
_SCHEMA = (
    "CREATE TABLE project_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE shared_frames (frame INTEGER PRIMARY KEY, note TEXT, params TEXT NOT NULL)",
    "CREATE TABLE special_zone_points (dot_id INTEGER PRIMARY KEY, x REAL NOT NULL, y REAL NOT NULL, zones TEXT NOT NULL)",
    "CREATE TABLE pose_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE zone_events (frame INTEGER NOT NULL, zone TEXT NOT NULL, "
    "event TEXT NOT NULL, PRIMARY KEY(frame, zone))",
    "CREATE TABLE frame_quality (frame INTEGER PRIMARY KEY, value REAL NOT NULL)",
    "CREATE TABLE scale_labels (frame INTEGER NOT NULL, kind TEXT NOT NULL, "
    "value REAL NOT NULL, source TEXT NOT NULL, PRIMARY KEY(frame, kind))",
)


class PoseStorageError(ValueError):
    """The database format or saved annotations are invalid/unsupported."""


def _validate_shared_frame(frame, note, params):
    if (type(frame) is not int or frame < 0
            or note is not None and not isinstance(note, str)
            or not isinstance(params, dict) or set(params) - {"Par1", "Par2", "Par3"}
            or any(value not in (None, "ON", "OFF") for value in params.values())):
        raise PoseStorageError("Invalid Pose shared frame")


def _validate_special_points(points):
    ids = set()
    for dot_id, x, y, zones in points:
        if (type(dot_id) is not int or dot_id < 0 or dot_id in ids
                or any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not math.isfinite(v) or v < 0 for v in (x, y))
                or not isinstance(zones, str)):
            raise PoseStorageError("Invalid Pose Special Zones point")
        ids.add(dot_id)


def _validate_format(connection):
    objects = connection.execute(
        "SELECT name, type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
    ).fetchall()
    if set(objects) != {(name, "table") for name in _COLUMNS}:
        raise PoseStorageError("Not a supported Pose database: unexpected schema")
    for table, columns in _COLUMNS.items():
        actual = tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table})"))
        if actual != columns:
            raise PoseStorageError(f"Invalid Pose table: {table}")
    metadata = connection.execute("SELECT key, value FROM pose_meta").fetchall()
    if len(metadata) != 2 or set(metadata) != {
            ("kind", POSE_KIND), ("schema_version", SCHEMA_VERSION)}:
        raise PoseStorageError("Unsupported Pose kind or schema version")


class PoseSqliteRepository:
    """Explicit save/load/close API; never exports or changes Touch state."""

    @staticmethod
    def inspect_metadata(path):
        """Read-only library/setup inspection, without creating missing files."""
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            _validate_format(connection)
            metadata = dict(connection.execute("SELECT key, value FROM project_meta"))
            if metadata.get("annotation_type", "Pose") != "Pose":
                raise PoseStorageError("Invalid Pose annotation type")
            return metadata

    def __init__(self, path: str | Path):
        self._owner = threading.get_ident()
        self._connection = None
        path = Path(path).absolute()
        existed = path.exists()
        if existed:
            # A wrong-kind/unknown/malformed file remains untouched, including
            # its journal mode. mode=rw below cannot recreate a vanished file.
            try:
                with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as probe:
                    _validate_format(probe)
            except sqlite3.DatabaseError as error:
                raise PoseStorageError("Cannot read Pose database") from error
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation closes the exists()/connect() race: a file
            # created by another process is never opened as a new Pose store.
            with path.open("xb"):
                pass
        connection = sqlite3.connect(
            path.as_uri() + "?mode=rw", uri=True,
        )
        try:
            if existed:
                _validate_format(connection)
            connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            if not existed:
                connection.execute("BEGIN IMMEDIATE")
                for statement in _SCHEMA:
                    connection.execute(statement)
                connection.executemany("INSERT INTO pose_meta VALUES (?, ?)", (
                    ("kind", POSE_KIND), ("schema_version", SCHEMA_VERSION),
                ))
                connection.commit()
            self._connection = connection
        except Exception:
            connection.close()
            raise

    def _check_thread(self):
        if threading.get_ident() != self._owner:
            raise RuntimeError("Pose repository must be used on its owning thread")
        if self._connection is None:
            raise RuntimeError("Pose repository is closed")

    def load(self) -> PoseLabels:
        """Read one consistent snapshot and validate every row before publishing."""
        self._check_thread()
        connection = self._connection
        try:
            with connection:
                connection.execute("BEGIN")
                _validate_format(connection)
                snapshot = PoseSnapshot(
                    events=tuple((frame, zone, ZoneEvent(event)) for frame, zone, event
                                 in connection.execute("SELECT * FROM zone_events ORDER BY frame, zone")),
                    quality=tuple(connection.execute("SELECT * FROM frame_quality ORDER BY frame")),
                    scales=tuple((frame, ScaleKind(kind), ScaleLabel(value, ScaleSource(source)))
                                 for frame, kind, value, source in connection.execute(
                                     "SELECT * FROM scale_labels ORDER BY frame, kind")),
                )
        except (sqlite3.DatabaseError, ValueError, TypeError) as error:
            raise PoseStorageError("Invalid Pose saved state") from error
        return PoseLabels.from_snapshot(snapshot)

    def save(self, labels: PoseLabels) -> None:
        """Compatibility API for a labels-only atomic save."""
        self._save(labels)

    def save_workspace(self, labels, *, shared_frames, special_zones, metadata):
        """Encode a validated complete workspace inside the labels transaction."""
        self._check_thread()
        rows = []
        for frame, bundle in shared_frames.items():
            if not isinstance(bundle, dict) or set(bundle) - {"Note", "Params", "Changed"}:
                raise PoseStorageError("Pose shared frames cannot contain Touch records")
            note, params = bundle.get("Note"), bundle.get("Params", {})
            _validate_shared_frame(frame, note, params)
            rows.append((frame, note, json.dumps(params)))
        points = tuple(tuple(row) for row in special_zones)
        _validate_special_points(points)
        self._save(labels, workspace=(rows, points, dict(metadata)))

    def _save(self, labels: PoseLabels, *, workspace=None) -> None:
        """Atomically replace sparse labels; failed writes retain previous state."""
        self._check_thread()
        snapshot = labels.snapshot()
        connection = self._connection
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            _validate_format(connection)
            for table in ("zone_events", "frame_quality", "scale_labels"):
                connection.execute(f"DELETE FROM {table}")
            connection.executemany("INSERT INTO zone_events VALUES (?, ?, ?)", (
                (frame, zone, event.value) for frame, zone, event in snapshot.events
            ))
            connection.executemany("INSERT INTO frame_quality VALUES (?, ?)", snapshot.quality)
            connection.executemany("INSERT INTO scale_labels VALUES (?, ?, ?, ?)", (
                (frame, kind.value, label.value, label.source.value)
                for frame, kind, label in snapshot.scales
            ))
            if workspace is not None:
                frames, points, metadata = workspace
                connection.execute("DELETE FROM shared_frames")
                connection.executemany("INSERT INTO shared_frames VALUES (?, ?, ?)", frames)
                connection.execute("DELETE FROM special_zone_points")
                connection.executemany("INSERT INTO special_zone_points VALUES (?, ?, ?, ?)", points)
                connection.executemany("INSERT OR REPLACE INTO project_meta VALUES (?, ?)", metadata.items())

    def close(self) -> None:
        self._check_thread()
        self._connection.close()
        self._connection = None

    def get_meta(self, key, default=None):
        self._check_thread()
        row = self._connection.execute("SELECT value FROM project_meta WHERE key=?", (key,)).fetchone()
        return default if row is None else row[0]

    def set_meta(self, key, value):
        self.set_meta_many({key: value})

    def set_meta_many(self, values):
        self._check_thread()
        with self._connection:
            self._connection.executemany(
                "INSERT OR REPLACE INTO project_meta VALUES (?, ?)",
                ((key, str(value)) for key, value in values.items()))

    def load_coding_setup(self):
        raw = self.get_meta("coding_setup")
        return PoseCodingSetup.from_dict(json.loads(raw)) if raw else None

    def load_preparation_state(self):
        state = self.get_meta("preparation_state", "draft")
        if state not in ("draft", "preparing", "ready"):
            raise PoseStorageError("Invalid Pose preparation state")
        return state

    def save_coding_setup(self, setup, preparation_state="draft"):
        if not isinstance(setup, PoseCodingSetup):
            raise ValueError("A complete Pose coding setup is required")
        if preparation_state not in ("draft", "preparing", "ready"):
            raise ValueError("Invalid Pose preparation state")
        current = self.load_coding_setup()
        if current and self.load_preparation_state() == "ready":
            if current != setup or preparation_state != "ready":
                raise ValueError("Prepared Pose coding setup is locked")
            return
        self.set_meta_many({"annotation_type": "Pose", "coding_setup": json.dumps(setup.to_dict()),
                            "preparation_state": preparation_state})

    def mark_prepared(self):
        setup = self.load_coding_setup()
        if setup is None:
            raise ValueError("Prepare the Pose coding setup first")
        self.save_coding_setup(setup, "ready")

    def load_frames(self, progress_cb=None):
        """Shared frame annotations only; Pose never creates limb records."""
        self._check_thread()
        frames = {}
        for frame, note, raw_params in self._connection.execute("SELECT * FROM shared_frames ORDER BY frame"):
            try:
                params = json.loads(raw_params)
                _validate_shared_frame(frame, note, params)
            except (TypeError, ValueError) as exc:
                raise PoseStorageError("Invalid Pose shared frame") from exc
            frames[frame] = {"Note": note, "Params": params, "Changed": False}
        return frames

    def load_labeling_time_seconds(self):
        value = float(self.get_meta("labeling_time_seconds", "0"))
        if not math.isfinite(value) or value < 0:
            raise PoseStorageError("Invalid Pose labeling time")
        return value

    def save_labeling_time_seconds(self, seconds):
        self.set_meta("labeling_time_seconds", seconds)

    def save_last_position(self, frame, total_frames):
        self.set_meta_many({"last_frame": frame, "total_frames": total_frames})

    def read_last_position(self, total_frames):
        value = self.get_meta("last_frame")
        return max(0, min(total_frames, int(value))) if value is not None else None

    def has_special_zones(self):
        return bool(self.load_special_zone_rows())

    def load_special_zone_rows(self):
        self._check_thread()
        points = self._connection.execute("SELECT * FROM special_zone_points ORDER BY dot_id").fetchall()
        _validate_special_points(points)
        return points

    def special_zones_note(self):
        return self.get_meta("special_zones_note")

    def special_zones_diagram_scale(self):
        value = self.get_meta("special_zones_diagram_scale")
        if value is None:
            return None
        scale = float(value)
        if not math.isfinite(scale) or scale <= 0:
            raise PoseStorageError("Invalid Pose Special Zones scale")
        return scale
