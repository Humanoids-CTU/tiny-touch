"""Versioned Pose-only SQLite state, confined to the creating thread.

Existing files are preflighted read-only before opening for writing. Saves replace
all sparse labels in one transaction; deletions cannot leave stale rows behind.
"""

from contextlib import closing
from pathlib import Path
import sqlite3
import threading

from domain.pose import (
    JointEvent, PoseLabels, PoseSnapshot, ScaleKind, ScaleLabel, ScaleSource,
)


POSE_KIND = "tinytouch.pose"
SCHEMA_VERSION = "1"
BUSY_TIMEOUT_MS = 5000
_COLUMNS = {
    "pose_meta": ("key", "value"),
    "joint_events": ("frame", "joint", "event"),
    "frame_quality": ("frame", "value"),
    "scale_labels": ("frame", "kind", "value", "source"),
}
_SCHEMA = (
    "CREATE TABLE pose_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE joint_events (frame INTEGER NOT NULL, joint TEXT NOT NULL, "
    "event TEXT NOT NULL, PRIMARY KEY(frame, joint))",
    "CREATE TABLE frame_quality (frame INTEGER PRIMARY KEY, value REAL NOT NULL)",
    "CREATE TABLE scale_labels (frame INTEGER NOT NULL, kind TEXT NOT NULL, "
    "value REAL NOT NULL, source TEXT NOT NULL, PRIMARY KEY(frame, kind))",
)


class PoseStorageError(ValueError):
    """The database format or saved annotations are invalid/unsupported."""


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
                    events=tuple((frame, joint, JointEvent(event)) for frame, joint, event
                                 in connection.execute("SELECT * FROM joint_events ORDER BY frame, joint")),
                    quality=tuple(connection.execute("SELECT * FROM frame_quality ORDER BY frame")),
                    scales=tuple((frame, ScaleKind(kind), ScaleLabel(value, ScaleSource(source)))
                                 for frame, kind, value, source in connection.execute(
                                     "SELECT * FROM scale_labels ORDER BY frame, kind")),
                )
        except (sqlite3.DatabaseError, ValueError, TypeError) as error:
            raise PoseStorageError("Invalid Pose saved state") from error
        return PoseLabels.from_snapshot(snapshot)

    def save(self, labels: PoseLabels) -> None:
        """Atomically replace sparse labels; failed writes retain previous state."""
        self._check_thread()
        snapshot = labels.snapshot()
        connection = self._connection
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            _validate_format(connection)
            for table in ("joint_events", "frame_quality", "scale_labels"):
                connection.execute(f"DELETE FROM {table}")
            connection.executemany("INSERT INTO joint_events VALUES (?, ?, ?)", (
                (frame, joint, event.value) for frame, joint, event in snapshot.events
            ))
            connection.executemany("INSERT INTO frame_quality VALUES (?, ?)", snapshot.quality)
            connection.executemany("INSERT INTO scale_labels VALUES (?, ?, ?, ?)", (
                (frame, kind.value, label.value, label.source.value)
                for frame, kind, label in snapshot.scales
            ))

    def close(self) -> None:
        self._check_thread()
        self._connection.close()
        self._connection = None
