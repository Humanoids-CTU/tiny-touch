"""Pose-only storage acceptance; all databases live in temporary projects."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3

import pytest

from adapters.pose_sqlite_repo import PoseSqliteRepository, PoseStorageError
from domain.pose import (
    ZoneEvent, Navigation, PoseLabels, PoseSnapshot, ScaleKind, ScaleLabel, ScaleSource,
)
from domain.project import ProjectPaths
from service_layer.pose_project_service import PoseProjectSession


BODY, HEAD = ScaleKind.BODY, ScaleKind.HEAD
MANUAL, CARRIED = ScaleSource.MANUAL, ScaleSource.CARRIED
JOINT = "L"


def test_s7_j5_save_reopen_preserves_sparse_labels_and_provenance(tmp_path):
    paths = ProjectPaths("video", str(tmp_path))
    session = PoseProjectSession(paths)
    session.labels.set_event(100, JOINT, ZoneEvent.ON, displayed_frame=100)
    session.labels.set_event(104, JOINT, ZoneEvent.OFF, displayed_frame=104)
    session.labels.set_quality(100, 0, displayed_frame=100)
    session.labels.set_quality(1000000, 1, displayed_frame=1000000)
    session.scales.edit(100, BODY, 1.2, displayed_frame=100)
    session.scales.reset(100, HEAD, displayed_frame=100)
    session.scales.arrive(100, 101, Navigation.FORWARD_STEP, displayed_frame=101)
    session.scales.edit(102, BODY, 1.15, displayed_frame=102)
    session.scales.arrive(102, 103, Navigation.FORWARD_HOLD, displayed_frame=103)
    saved = session.labels.snapshot()
    session.save()
    session.close()
    assert not Path(paths.state_db).exists()

    reopened = PoseProjectSession(paths)
    try:
        assert reopened.labels.snapshot() == saved
        assert reopened.labels.quality(100) == 0
        assert reopened.labels.quality(101) is None
        assert reopened.labels.scale(100, HEAD) == ScaleLabel(1.0, MANUAL)
        assert reopened.labels.scale(101, HEAD) == ScaleLabel(1.0, CARRIED)
        assert reopened.labels.scale(1000000, BODY) is None
        assert reopened.labels.active_zones(103) == {JOINT}
        assert reopened.labels.active_zones(104) == set()
        assert reopened.scales.carried_value(BODY) is None
        assert reopened.scales.carried_value(HEAD) is None
        reopened.scales.arrive(103, 104, Navigation.FORWARD_STEP, displayed_frame=104)
        assert reopened.labels.scale(104, BODY) is None
        # A fresh edit can overwrite carried records but protects manual barriers.
        reopened.scales.edit(99, BODY, 1.3, displayed_frame=99)
        reopened.scales.arrive(99, 101, Navigation.FORWARD_STEP, displayed_frame=101)
        assert reopened.labels.scale(101, BODY) == ScaleLabel(1.3, CARRIED)
        reopened.scales.arrive(101, 102, Navigation.FORWARD_STEP, displayed_frame=102)
        reopened.scales.arrive(102, 103, Navigation.FORWARD_STEP, displayed_frame=103)
        assert reopened.labels.scale(102, BODY) == ScaleLabel(1.15, MANUAL)
        assert reopened.labels.scale(103, BODY) == ScaleLabel(1.15, CARRIED)
        with pytest.raises(ValueError, match="painted"):
            reopened.labels.set_quality(100, .5, displayed_frame=None)
    finally:
        reopened.close()


def test_deletions_are_durable_and_independent(tmp_path):
    repo = PoseSqliteRepository(tmp_path / "pose.db")
    labels = PoseLabels()
    labels.set_event(3, JOINT, ZoneEvent.ON, displayed_frame=3)
    labels.set_quality(3, 0, displayed_frame=3)
    labels.set_scale(3, BODY, ScaleLabel(1, MANUAL), displayed_frame=3)
    repo.save(labels)
    labels.set_event(3, JOINT, None, displayed_frame=3)
    labels.set_scale(3, BODY, None, displayed_frame=3)
    repo.save(labels)
    assert repo.load().snapshot() == PoseSnapshot(quality=((3, 0.0),))
    labels.set_quality(3, None, displayed_frame=3)
    repo.save(labels)
    repo.close()
    reopened = PoseSqliteRepository(tmp_path / "pose.db")
    assert reopened.load().snapshot() == PoseSnapshot()
    reopened.close()


def test_saving_twice_preserves_multiple_zone_and_scale_keys(tmp_path):
    repo = PoseSqliteRepository(tmp_path / "pose.db")
    labels = PoseLabels()
    labels.set_event(3, "L", ZoneEvent.ON, displayed_frame=3)
    labels.set_event(3, "K", ZoneEvent.OFF, displayed_frame=3)
    labels.set_scale(3, BODY, ScaleLabel(1.2, MANUAL), displayed_frame=3)
    labels.set_scale(3, HEAD, ScaleLabel(.9, CARRIED), displayed_frame=3)
    repo.save(labels)
    repo.save(labels)
    assert repo.load().snapshot() == labels.snapshot()
    repo.close()


def test_touch_and_pose_coexist_without_changing_touch_state(tmp_path):
    from adapters.sqlite_repo import SqliteRepository
    from domain.model import empty_bundle

    paths = ProjectPaths("video", str(tmp_path))
    touch = SqliteRepository(paths.state_db)
    frames = {3: empty_bundle()}
    frames[3]["Note"] = "Touch data stays intact"
    touch.save_frames(frames, total_frames=5)
    expected = touch.load_frames()
    touch.close()
    before = Path(paths.state_db).read_bytes()
    pose = PoseProjectSession(paths)
    pose.labels.set_quality(3, 0, displayed_frame=3)
    pose.save()
    pose.close()
    assert Path(paths.state_db).read_bytes() == before
    touch = SqliteRepository(paths.state_db)
    assert touch.load_frames() == expected
    touch.close()


def test_failed_save_rolls_back_prior_data_and_session_can_retry(tmp_path):
    session = PoseProjectSession(ProjectPaths("v", str(tmp_path)))
    session.labels.set_quality(1, .5, displayed_frame=1)
    session.save()
    session.labels.set_event(2, JOINT, ZoneEvent.ON, displayed_frame=2)
    # Python frame indices are unbounded; SQLite cannot bind this integer.
    huge_frame = 2 ** 80
    session.labels.set_quality(huge_frame, .8, displayed_frame=huge_frame)
    with pytest.raises(OverflowError):
        session.save()
    disk = PoseSqliteRepository(ProjectPaths("v", str(tmp_path)).pose_state_db)
    assert disk.load().snapshot() == PoseSnapshot(quality=((1, .5),))
    disk.close()
    assert session.labels.event(2, JOINT) is ZoneEvent.ON
    session.labels.set_quality(huge_frame, None, displayed_frame=huge_frame)
    session.save()
    session.close()
    disk = PoseSqliteRepository(ProjectPaths("v", str(tmp_path)).pose_state_db)
    assert disk.load().event(2, JOINT) is ZoneEvent.ON
    disk.close()


def test_new_file_creation_race_does_not_modify_competing_file(tmp_path, monkeypatch):
    path = tmp_path / "pose.db"
    original_open = Path.open

    def competing_open(target, mode="r", *args, **kwargs):
        if mode == "xb":
            with original_open(target, "wb") as writer:
                writer.write(b"competing file")
        return original_open(target, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", competing_open)
    with pytest.raises(FileExistsError):
        PoseSqliteRepository(path)
    assert path.read_bytes() == b"competing file"


@pytest.mark.parametrize("kind", ["touch", "future", "missing_table", "wrong_columns", "junk", "empty"])
def test_unsupported_existing_file_is_untouched(tmp_path, kind):
    path = tmp_path / "unknown.db"
    if kind in ("touch", "empty"):
        with sqlite3.connect(path) as connection:
            if kind == "touch":
                connection.execute("CREATE TABLE frames (frame INTEGER)")
    elif kind == "junk":
        path.write_bytes(b"not sqlite")
    else:
        repo = PoseSqliteRepository(path)
        repo.close()
        with sqlite3.connect(path) as connection:
            if kind == "future":
                connection.execute("UPDATE pose_meta SET value='999' WHERE key='schema_version'")
            elif kind == "missing_table":
                connection.execute("DROP TABLE frame_quality")
            else:
                connection.execute("ALTER TABLE frame_quality ADD COLUMN extra TEXT")
            connection.execute("PRAGMA journal_mode=PERSIST")
    before = path.read_bytes()
    with pytest.raises(PoseStorageError):
        PoseSqliteRepository(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("statement", [
    "INSERT INTO zone_events VALUES(-1, 'L', 'ON')",
    "INSERT INTO zone_events VALUES(1, 'UNKNOWN', 'ON')",
    "INSERT INTO zone_events VALUES(1, 'L', 'INVALID')",
    "INSERT INTO frame_quality VALUES(1, 1.1)",
    "INSERT INTO frame_quality VALUES(1, 'bad')",
    "INSERT INTO scale_labels VALUES(1, 'body', 1, 'bad')",
    "INSERT INTO scale_labels VALUES(1, 'body', 0, 'manual')",
    "INSERT INTO scale_labels VALUES(1, 'wrong', 1, 'manual')",
    "INSERT INTO scale_labels VALUES(1.5, 'body', 1, 'manual')",
])
def test_corrupt_rows_fail_explicitly(tmp_path, statement):
    path = tmp_path / "pose.db"
    repo = PoseSqliteRepository(path)
    repo.close()
    with sqlite3.connect(path) as connection:
        connection.execute(statement)
    repo = PoseSqliteRepository(path)
    try:
        with pytest.raises(PoseStorageError, match="Invalid Pose saved state"):
            repo.load()
    finally:
        repo.close()


@pytest.mark.parametrize("operation", ["load", "save", "close"])
def test_repository_rejects_cross_thread_access(tmp_path, operation):
    repo = PoseSqliteRepository(tmp_path / "pose.db")
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            args = (PoseLabels(),) if operation == "save" else ()
            with pytest.raises(RuntimeError, match="owning thread"):
                pool.submit(getattr(repo, operation), *args).result()
        assert repo.load().snapshot() == PoseSnapshot()
    finally:
        repo.close()


def test_snapshot_is_detached_from_both_original_and_restored_labels():
    labels = PoseLabels()
    labels.set_quality(3, .5, displayed_frame=3)
    snapshot = labels.snapshot()
    restored = PoseLabels.from_snapshot(snapshot)
    restored.set_quality(3, .7, displayed_frame=3)
    labels.set_quality(4, 0, displayed_frame=4)
    assert snapshot == PoseSnapshot(quality=((3, .5),))
    assert labels.quality(3) == .5
    assert restored.quality(4) is None


@pytest.mark.parametrize("kwargs", [
    {"events": ((1, JOINT, "ON"),)},
    {"events": ((1, JOINT, ZoneEvent.ON), (1, JOINT, ZoneEvent.OFF))},
    {"quality": ((1, 0), (1, 1))},
    {"quality": ((True, 0),)},
    {"quality": ((1, float('nan')),)},
    {"quality": [(1, .5)]},
    {"scales": ((1, BODY, ScaleLabel(1, MANUAL)), (1, BODY, ScaleLabel(1, CARRIED)))},
])
def test_snapshot_rejects_invalid_records(kwargs):
    with pytest.raises(ValueError):
        PoseSnapshot(**kwargs)
