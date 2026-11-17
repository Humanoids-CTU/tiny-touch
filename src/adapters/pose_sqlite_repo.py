"""Versioned Pose-only SQLite state, confined to the creating thread.

Existing files are preflighted read-only before opening for writing. Each save is
one transaction. Labels are written incrementally (only keys changed since the
last load or successful save) when the repository can prove the labels object
and the database still share that baseline; otherwise every label row is
replaced. Either way deletions cannot leave stale rows behind.
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


def _write_label_changes(connection, changes):
    """Apply validated changes; each statement touches only its own keys."""
    upserts = changes.upserts
    connection.executemany("DELETE FROM zone_events WHERE frame=? AND zone=?",
                           changes.deleted_events)
    connection.executemany("DELETE FROM frame_quality WHERE frame=?",
                           ((frame,) for frame in changes.deleted_quality))
    connection.executemany("DELETE FROM scale_labels WHERE frame=? AND kind=?", (
        (frame, kind.value) for frame, kind in changes.deleted_scales))
    connection.executemany("INSERT OR REPLACE INTO zone_events VALUES (?, ?, ?)", (
        (frame, zone, event.value) for frame, zone, event in upserts.events))
    connection.executemany("INSERT OR REPLACE INTO frame_quality VALUES (?, ?)",
                           upserts.quality)
    connection.executemany("INSERT OR REPLACE INTO scale_labels VALUES (?, ?, ?, ?)", (
        (frame, kind.value, label.value, label.source.value)
        for frame, kind, label in upserts.scales))


def _replace_all_labels(connection, snapshot):
    for table in ("zone_events", "frame_quality", "scale_labels"):
        connection.execute(f"DELETE FROM {table}")
    connection.executemany("INSERT INTO zone_events VALUES (?, ?, ?)", (
        (frame, zone, event.value) for frame, zone, event in snapshot.events))
    connection.executemany("INSERT INTO frame_quality VALUES (?, ?)", snapshot.quality)
    connection.executemany("INSERT INTO scale_labels VALUES (?, ?, ?, ?)", (
        (frame, kind.value, label.value, label.source.value)
        for frame, kind, label in snapshot.scales))


def _check_label_frames(connection, max_frame):
    """Every stored label, changed or not, must lie inside the video."""
    if max_frame is None:
        return
    for table in ("zone_events", "frame_quality", "scale_labels"):
        # Each table's primary key starts with frame, so MAX uses the index.
        last = connection.execute(f"SELECT MAX(frame) FROM {table}").fetchone()[0]
        if last is not None and last > max_frame:
            raise ValueError("Pose annotation exceeds video length")


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
        # Baseline shared by one PoseLabels object and this database: the token
        # that object holds, and PRAGMA data_version when it was last confirmed.
        # data_version changes only when another connection commits.
        self._labels_token = None
        self._data_version = None
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
                data_version = self._read_data_version()
        except (sqlite3.DatabaseError, ValueError, TypeError) as error:
            raise PoseStorageError("Invalid Pose saved state") from error
        labels = PoseLabels.from_snapshot(snapshot)
        self._track(labels, data_version)
        return labels

    def _read_data_version(self):
        return self._connection.execute("PRAGMA data_version").fetchone()[0]

    def _track(self, labels, data_version):
        """Remember `labels` as matching this database right now."""
        self._labels_token = labels.start_tracking()
        self._data_version = data_version

    def _is_baseline(self, labels):
        """Only the object this repository last loaded or saved is trusted.

        A fresh, rehydrated or foreign PoseLabels, or one re-tracked by another
        repository since, has a different token and gets a full replace.
        """
        return (self._labels_token is not None
                and labels.tracking_token is self._labels_token)

    def save(self, labels: PoseLabels) -> None:
        """Compatibility API for a labels-only atomic save."""
        self._save(labels)

    def save_workspace(self, labels, *, shared_frames, special_zones, metadata,
                       max_frame=None):
        """Encode a validated complete workspace inside the labels transaction.

        With `max_frame`, the commit is refused if any stored label frame,
        including unchanged ones, would exceed it.
        """
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
        self._save(labels, workspace=(rows, points, dict(metadata)), max_frame=max_frame)

    def _save(self, labels: PoseLabels, *, workspace=None, max_frame=None) -> None:
        """Atomically write labels; failed writes retain previous state.

        Incremental when `labels` is this repository's baseline and no other
        connection has committed since; otherwise a full replace, after which
        `labels` becomes the baseline. Any failure drops the baseline, so the
        next save is a full replace that writes everything still pending.
        """
        self._check_thread()
        if not isinstance(labels, PoseLabels):
            raise ValueError("Expected PoseLabels")
        # Validated before writing; the cost follows the number of edits.
        changes = labels.pending_changes() if self._is_baseline(labels) else None
        connection = self._connection
        try:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                _validate_format(connection)
                data_version = self._read_data_version()
                if changes is not None and data_version == self._data_version:
                    _write_label_changes(connection, changes)
                else:
                    changes = None
                    _replace_all_labels(connection, labels.snapshot())
                _check_label_frames(connection, max_frame)
                if workspace is not None:
                    # Shared frames and Special Zones are sparse, user-made rows;
                    # replacing them keeps the save simple at negligible cost.
                    frames, points, metadata = workspace
                    connection.execute("DELETE FROM shared_frames")
                    connection.executemany("INSERT INTO shared_frames VALUES (?, ?, ?)", frames)
                    connection.execute("DELETE FROM special_zone_points")
                    connection.executemany("INSERT INTO special_zone_points VALUES (?, ?, ?, ?)", points)
                    connection.executemany("INSERT OR REPLACE INTO project_meta VALUES (?, ?)",
                                           metadata.items())
        except BaseException:
            # Rolled back, but trust nothing about the baseline after a failure.
            self._labels_token = None
            raise
        if changes is None:
            self._track(labels, data_version)
        else:
            labels.mark_saved(changes)

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
