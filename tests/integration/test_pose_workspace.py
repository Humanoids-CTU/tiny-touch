"""Full Pose saves are atomic, including shared annotations."""
import sqlite3
import pytest
from adapters.pose_sqlite_repo import PoseSqliteRepository
from service_layer.pose_project_service import PoseProjectSession
from domain.pose import ZoneEvent, ScaleKind, ScaleLabel, ScaleSource


def save(session, frames, **changes):
    values = dict(last_frame=4, total_frames=10, labeling_time_seconds=12,
                  special_zones=((1, 30, 40, "Body"),), special_note="sleeve", special_scale=1.0)
    values.update(changes)
    session.save_workspace(frames, **values)


@pytest.mark.parametrize("failed_table", ["shared_frames", "special_zone_points", "project_meta"])
def test_full_workspace_roundtrip_and_rollback_retry(tmp_path, failed_table):
    path = tmp_path / "pose.db"
    repo = PoseSqliteRepository(path)
    session = PoseProjectSession.from_repository(repo)
    session.labels.set_event(4, "L", ZoneEvent.ON, displayed_frame=4)
    session.labels.set_scale(4, ScaleKind.BODY, ScaleLabel(1.2, ScaleSource.CARRIED), displayed_frame=4)
    frames = {4: {"Note": "hello", "Params": {"Par1": "OFF"}, "Changed": True}}
    save(session, frames)
    assert frames[4]["Changed"] is False
    saved = session.labels.snapshot()
    session.labels.set_quality(4, .2, displayed_frame=4)
    frames[4].update(Note="changed", Changed=True)
    repo._connection.execute(f"CREATE TEMP TRIGGER fail_workspace BEFORE INSERT ON {failed_table} BEGIN SELECT RAISE(ABORT, 'fail'); END")
    with pytest.raises(sqlite3.IntegrityError):
        save(session, frames, last_frame=5, labeling_time_seconds=20, special_note="new")
    assert frames[4]["Changed"] is True
    observer = PoseSqliteRepository(path)
    assert observer.load().quality(4) is None
    assert observer.load().snapshot() == saved
    assert observer.load_frames()[4]["Note"] == "hello"
    assert observer.read_last_position(10) == 4
    assert observer.load_labeling_time_seconds() == 12
    assert observer.special_zones_note() == "sleeve"
    assert observer.load_special_zone_rows() == [(1, 30., 40., "Body")]
    observer.close()
    repo._connection.execute("DROP TRIGGER fail_workspace")
    save(session, frames, last_frame=5, labeling_time_seconds=20, special_note="new")
    session.close()
    reopened = PoseSqliteRepository(path)
    assert reopened.load().quality(4) == .2
    assert reopened.load().event(4, "L") is ZoneEvent.ON
    assert reopened.load().scale(4, ScaleKind.BODY) == ScaleLabel(1.2, ScaleSource.CARRIED)
    assert reopened.load_frames() == {4: {"Note": "changed", "Params": {"Par1": "OFF"}, "Changed": False}}
    assert reopened.read_last_position(10) == 5
    assert reopened.load_labeling_time_seconds() == 20
    assert reopened.load_special_zone_rows() == [(1, 30., 40., "Body")]
    assert reopened.special_zones_note() == "new"
    reopened.close()


def test_invalid_workspace_never_replaces_labels_or_metadata(tmp_path):
    repo = PoseSqliteRepository(tmp_path / "pose.db")
    session = PoseProjectSession.from_repository(repo)
    save(session, {})
    session.labels.set_quality(2, .5, displayed_frame=2)
    with pytest.raises(ValueError):
        save(session, {3: {"Note": "oops", "Params": {"Par1": "bad"}}}, last_frame=8)
    assert repo.load().quality(2) is None
    assert repo.read_last_position(10) == 4
    session.close()


@pytest.mark.parametrize("scale", ["nan", "inf", "0", "-1"])
def test_corrupt_special_zone_scale_is_rejected_on_open(tmp_path, scale):
    from domain.project import ProjectPaths
    paths = ProjectPaths("clip", str(tmp_path))
    repo = PoseSqliteRepository(paths.pose_state_db)
    repo.set_meta("special_zones_diagram_scale", scale)
    repo.close()
    with pytest.raises(ValueError):
        PoseProjectSession(paths)
    # Failed construction released the connection, including its file handle.
    repo = PoseSqliteRepository(paths.pose_state_db)
    assert repo.get_meta("special_zones_diagram_scale") == scale
    repo.close()


def test_out_of_video_labels_reject_whole_workspace(tmp_path):
    repo = PoseSqliteRepository(tmp_path / "pose.db")
    session = PoseProjectSession.from_repository(repo)
    save(session, {})
    session.labels.set_quality(11, .5, displayed_frame=11)
    with pytest.raises(ValueError, match="exceeds"):
        save(session, {}, last_frame=8)
    assert repo.load().quality(11) is None
    assert repo.read_last_position(10) == 4
    session.close()


def test_special_zone_deletion_is_durable_and_labels_only_save_preserves_shared(tmp_path):
    repo = PoseSqliteRepository(tmp_path / "pose.db")
    session = PoseProjectSession.from_repository(repo)
    frames = {4: {"Note": "note", "Params": {"Par2": "ON"}}}
    save(session, frames)
    session.save()
    assert repo.load_frames()[4]["Note"] == "note"
    assert len(repo.load_special_zone_rows()) == 1
    save(session, {}, special_zones=(), special_note="")
    assert repo.load_frames() == {}
    assert repo.load_special_zone_rows() == []
    assert repo.special_zones_note() == ""
    session.close()


def test_controller_save_captures_open_special_zones_in_the_same_workspace(tmp_path):
    from types import SimpleNamespace
    import numpy as np
    from adapters.pose_diagram import pose_zone_masks
    from adapters.pose_diagram import zone_positions
    from labeling_app import LabelingApp

    repo = PoseSqliteRepository(tmp_path / "pose.db")
    session = PoseProjectSession.from_repository(repo)
    session.labels.set_quality(4, 0, displayed_frame=4)
    x, y = zone_positions()["L"]
    dialog = SimpleNamespace(top_level=SimpleNamespace(winfo_exists=lambda: True),
                             dots={1: (x * .5, y * .5)}, diagram_scale=.5,
                             note=lambda: "sleeve")
    frames = {4: {"Note": "hello", "Params": {"Par1": "ON"}, "Changed": True}}
    app = SimpleNamespace(annotation_type="Pose", video_name="clip", state_repo=repo,
                          pose_session=session, _special_zones_app=dialog,
                          video=SimpleNamespace(frames_dir="frames", frames=frames,
                                                current_frame=4, total_frames=10),
                          _current_video_time_s=lambda: 12,
                          _zone_masks=[(name, np.asarray(mask)) for name, mask in pose_zone_masks()])
    app._save_pose_workspace = lambda: LabelingApp._save_pose_workspace(app)
    from service_layer.save_service import SaveOutcome
    assert LabelingApp.save_data(app) is SaveOutcome.SAVED
    assert repo.load().quality(4) == 0
    assert repo.load_frames()[4]["Note"] == "hello"
    assert repo.load_special_zone_rows() == [(1, x * .5, y * .5, "L")]
    assert repo.special_zones_diagram_scale() == .5
    assert repo.special_zones_note() == "sleeve"
    assert repo.read_last_position(10) == 4
    assert frames[4]["Changed"] is False
    session.close()
