"""Pose saves write only what changed since the last successful save.

Row counts come from SQLite's `total_changes` on the repository connection, so
the checks do not depend on wall-clock time.
"""

import random
import sqlite3

import pytest

from adapters.pose_sqlite_repo import PoseSqliteRepository
from domain.pose import (
    PoseLabels, PoseSnapshot, POSE_ZONES, ScaleKind, ScaleLabel, ScaleSource, ZoneEvent,
)
from service_layer.pose_project_service import PoseProjectSession

BODY, HEAD = ScaleKind.BODY, ScaleKind.HEAD
MANUAL, CARRIED = ScaleSource.MANUAL, ScaleSource.CARRIED
FRAMES = 2000
LABEL_TABLES = ("zone_events", "frame_quality", "scale_labels")


def dense_store(path, frames=FRAMES):
    """A store with carried body+head scale on every frame, like a long session."""
    label = ScaleLabel(1.1, CARRIED)
    repo = PoseSqliteRepository(path)
    repo.save(PoseLabels.from_snapshot(PoseSnapshot(
        events=((0, "L", ZoneEvent.ON),), quality=((0, .5),),
        scales=tuple((frame, kind, label) for frame in range(frames) for kind in ScaleKind))))
    repo.close()


def rows(path):
    with sqlite3.connect(path) as connection:
        return {table: connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
                for table in LABEL_TABLES}


def full_rewrite_rows(tmp_path, labels, name="reference.db"):
    """What the full replace stores for the same labels, in a separate file."""
    repo = PoseSqliteRepository(tmp_path / name)
    repo.save(PoseLabels.from_snapshot(labels.snapshot()))
    repo.close()
    return rows(tmp_path / name)


def written(repo, action):
    before = repo._connection.total_changes
    action()
    return repo._connection.total_changes - before


def save_workspace(session, total_frames=FRAMES):
    session.save_workspace({}, last_frame=0, total_frames=total_frames,
                           labeling_time_seconds=1, special_zones=(),
                           special_note="", special_scale=1.0)


def test_unchanged_labels_only_save_writes_no_rows(tmp_path):
    dense_store(tmp_path / "pose.db")
    repo = PoseSqliteRepository(tmp_path / "pose.db")
    session = PoseProjectSession.from_repository(repo)
    assert written(repo, session.save) == 0
    session.close()


def test_unchanged_workspace_save_writes_only_metadata(tmp_path):
    dense_store(tmp_path / "pose.db")
    repo = PoseSqliteRepository(tmp_path / "pose.db")
    session = PoseProjectSession.from_repository(repo)
    # Five project_meta rows: position, length, timer, note and diagram scale.
    assert written(repo, lambda: save_workspace(session)) == 5
    session.close()


def test_editing_a_few_labels_writes_only_those_rows(tmp_path):
    path = tmp_path / "pose.db"
    dense_store(path)
    repo = PoseSqliteRepository(path)
    session = PoseProjectSession.from_repository(repo)
    session.labels.set_scale(1500, BODY, ScaleLabel(.8, MANUAL), displayed_frame=1500)
    session.labels.set_quality(0, None, displayed_frame=0)
    session.labels.set_event(9, "K", ZoneEvent.OFF, displayed_frame=9)
    assert written(repo, session.save) == 3
    assert rows(path) == full_rewrite_rows(tmp_path, session.labels)
    session.close()


def test_deletions_leave_no_stale_rows(tmp_path):
    path = tmp_path / "pose.db"
    dense_store(path)
    repo = PoseSqliteRepository(path)
    session = PoseProjectSession.from_repository(repo)
    for frame in range(100, 110):
        session.labels.set_scale(frame, HEAD, None, displayed_frame=frame)
    session.labels.set_event(0, "L", None, displayed_frame=0)
    session.labels.set_quality(0, None, displayed_frame=0)
    session.save()
    session.close()
    stored = rows(path)
    assert stored["zone_events"] == [] and stored["frame_quality"] == []
    assert len(stored["scale_labels"]) == 2 * FRAMES - 10
    assert not any(frame in range(100, 110) and kind == "head"
                   for frame, kind, *_ in stored["scale_labels"])


def test_failed_incremental_save_rolls_back_and_retry_writes_everything(tmp_path):
    path = tmp_path / "pose.db"
    dense_store(path)
    repo = PoseSqliteRepository(path)
    session = PoseProjectSession.from_repository(repo)
    before = rows(path)
    session.labels.set_quality(5, .9, displayed_frame=5)
    session.labels.set_scale(7, BODY, None, displayed_frame=7)
    session.labels.set_scale(8, HEAD, ScaleLabel(.7, MANUAL), displayed_frame=8)
    repo._connection.execute("CREATE TEMP TRIGGER fail_scale BEFORE INSERT ON scale_labels "
                             "BEGIN SELECT RAISE(ABORT, 'fail'); END")
    with pytest.raises(sqlite3.IntegrityError):
        save_workspace(session)
    assert rows(path) == before
    repo._connection.execute("DROP TRIGGER fail_scale")
    session.labels.set_event(3, "L", ZoneEvent.OFF, displayed_frame=3)
    save_workspace(session)
    session.close()
    assert rows(path) == full_rewrite_rows(tmp_path, session.labels)


def test_foreign_labels_get_a_full_replace(tmp_path):
    path = tmp_path / "pose.db"
    dense_store(path)
    repo = PoseSqliteRepository(path)
    session = PoseProjectSession.from_repository(repo)
    # A rehydrated copy has no pending changes but differs from the database.
    foreign = PoseLabels.from_snapshot(PoseSnapshot(quality=((3, .25),)))
    repo.save(foreign)
    assert repo.load().snapshot() == foreign.snapshot()
    # The session's labels are no longer known to match the database either.
    session.labels.set_quality(4, .5, displayed_frame=4)
    session.save()
    assert rows(path) == full_rewrite_rows(tmp_path, session.labels)
    session.close()


def test_labels_saved_into_another_store_are_fully_replaced_on_return(tmp_path):
    dense_store(tmp_path / "a.db")
    first = PoseSqliteRepository(tmp_path / "a.db")
    labels = first.load()
    second = PoseSqliteRepository(tmp_path / "b.db")
    second.save(labels)
    labels.set_quality(6, .3, displayed_frame=6)
    second.save(labels)
    labels.set_quality(7, .4, displayed_frame=7)
    first.save(labels)
    first.close()
    second.close()
    assert rows(tmp_path / "a.db") == full_rewrite_rows(tmp_path, labels)
    assert rows(tmp_path / "b.db")["frame_quality"] == [(0, .5), (6, .3)]


def test_a_commit_from_another_connection_forces_a_full_replace(tmp_path):
    path = tmp_path / "pose.db"
    dense_store(path)
    repo = PoseSqliteRepository(path)
    session = PoseProjectSession.from_repository(repo)
    other = PoseSqliteRepository(path)
    other.save(PoseLabels())
    other.close()
    session.labels.set_quality(1, .1, displayed_frame=1)
    session.save()
    assert rows(path) == full_rewrite_rows(tmp_path, session.labels)
    session.close()


def test_out_of_video_check_covers_unchanged_stored_labels(tmp_path):
    path = tmp_path / "pose.db"
    dense_store(path)
    repo = PoseSqliteRepository(path)
    session = PoseProjectSession.from_repository(repo)
    session.labels.set_quality(1, .2, displayed_frame=1)
    with pytest.raises(ValueError, match="exceeds"):
        save_workspace(session, total_frames=FRAMES - 10)
    assert repo.load().quality(1) is None
    save_workspace(session)
    assert repo.load().quality(1) == .2
    session.close()


@pytest.mark.parametrize("seed", range(5))
def test_mixed_edit_sequences_roundtrip_exactly(tmp_path, seed):
    rng = random.Random(seed)
    path = tmp_path / "pose.db"
    dense_store(path, frames=200)
    repo = PoseSqliteRepository(path)
    session = PoseProjectSession.from_repository(repo)
    labels = session.labels
    for _ in range(6):
        for _ in range(rng.randrange(1, 40)):
            frame = rng.randrange(0, 220)
            choice = rng.randrange(3)
            if choice == 0:
                event = rng.choice((ZoneEvent.ON, ZoneEvent.OFF, None))
                labels.set_event(frame, rng.choice(POSE_ZONES), event, displayed_frame=frame)
            elif choice == 1:
                value = rng.choice((None, 0, .5, 1))
                labels.set_quality(frame, value, displayed_frame=frame)
            else:
                label = rng.choice((None, ScaleLabel(rng.choice((.5, 1, 1.5)),
                                                     rng.choice((MANUAL, CARRIED)))))
                labels.set_scale(frame, rng.choice((BODY, HEAD)), label, displayed_frame=frame)
        pending = labels.pending_changes()
        bound = 5 + sum(map(len, (
            pending.upserts.events, pending.upserts.quality, pending.upserts.scales,
            pending.deleted_events, pending.deleted_quality, pending.deleted_scales)))
        assert written(repo, lambda: save_workspace(session, total_frames=220)) <= bound
        # A second connection only reads, so the session keeps saving incrementally.
        observer = PoseSqliteRepository(path)
        assert observer.load().snapshot() == labels.snapshot()
        observer.close()
        assert labels.pending_changes().is_empty
    session.close()
    assert rows(path) == full_rewrite_rows(tmp_path, labels)
    reopened = PoseSqliteRepository(path)
    assert reopened.load().snapshot() == labels.snapshot()
    reopened.close()
