"""Controller boundaries exercised without constructing Tk or opening a video."""
from types import SimpleNamespace
import pytest

import labeling_app
from labeling_app import LabelingApp
from service_layer.save_service import SaveOutcome
from gui.special_zones_app import SpecialZonesApp
from service_layer import annotation_service


def test_pose_shared_annotations_never_create_touch_records():
    frames = {}
    assert annotation_service.set_note(frames, 3, "note", shared_only=True)
    assert [annotation_service.toggle_global_param(frames, 3, 1, shared_only=True)
            for _ in range(3)] == ["ON", "OFF", None]
    assert set(frames[3]) == {"Note", "Params", "Changed"}
    assert frames[3]["Note"] == "note"


@pytest.mark.parametrize("displayed", [None, 2])
def test_pose_shared_edits_wait_for_paint(displayed):
    app = SimpleNamespace(annotation_type="Pose", video=SimpleNamespace(current_frame=3, frames={}),
                          displayed_frame=displayed)
    LabelingApp.parameter_dic_insert(app, 1)
    LabelingApp.save_note(app)
    assert app.video.frames == {}


def test_pose_save_routes_only_to_workspace_and_reports_retry(monkeypatch):
    errors = []
    app = SimpleNamespace(annotation_type="Pose", video_name="pose",
                          video=SimpleNamespace(frames_dir="frames"), state_repo=object(),
                          _save_pose_workspace=lambda: True,
                          # The export step has its own tests (test_pose_export_save.py).
                          _publish_pose_export=lambda: SaveOutcome.SAVED)
    assert LabelingApp.save_data(app) is SaveOutcome.SAVED
    def fail():
        raise OSError("disk full")
    app._save_pose_workspace = fail
    monkeypatch.setattr(labeling_app.messagebox, "showerror", lambda *a, **kw: errors.append(a))
    assert LabelingApp.save_data(app) is SaveOutcome.NOT_SAVED
    assert app.video is not None and app.state_repo is not None
    assert "disk full" in errors[0][1]


def test_pose_analysis_and_touch_settings_actions_are_noops():
    app = SimpleNamespace(annotation_type="Pose", video=object())
    LabelingApp.analysis(app)
    LabelingApp.change_project_template(app)
    LabelingApp.edit_project_zone_names(app)
    LabelingApp.toggle_limb_parameter(app, 1)
    LabelingApp._apply_active_template(app, "default")


@pytest.mark.parametrize("kind, expected", [("Pose", "disabled"), ("Touch", "normal")])
def test_analysis_button_is_disabled_only_for_pose(kind, expected):
    options = {}
    app = SimpleNamespace(annotation_type=kind, video=object(),
                          analysis_btn=SimpleNamespace(config=lambda **kw: options.update(kw)))
    LabelingApp._set_mode_button_states(app)
    assert options["state"] == expected


def test_special_zone_failed_close_preserves_window_and_dots():
    dots = {2: (20, 30)}
    app = SimpleNamespace(dots=dots, diagram_scale=1, note=lambda: "shirt",
                          on_close_callback=lambda *a: False)
    assert SpecialZonesApp.on_close(app) is False
    assert app.dots == dots


def test_close_pose_save_failure_keeps_active_session(monkeypatch):
    monkeypatch.setattr(labeling_app, "custom_confirm_close", lambda app, **kw: True)
    monkeypatch.setattr(labeling_app, "find_open_touches", lambda *a: pytest.fail("Touch scan"))
    monkeypatch.setattr(labeling_app.messagebox, "showerror", lambda *a, **kw: None)
    app = SimpleNamespace(annotation_type="Pose", video=object(), save_data=lambda: SaveOutcome.NOT_SAVED)
    app._ask_how_to_close = lambda: LabelingApp._ask_how_to_close(app)
    LabelingApp.on_close(app)
    assert app.video is not None
    assert not app._closing


def test_pose_close_repo_detaches_paint_listener_and_session():
    events = []
    panel = SimpleNamespace(detach=lambda: events.append("detach"))
    app = SimpleNamespace(state_repo=SimpleNamespace(close=lambda: events.append("close")),
                          _pose_panel=panel, pose_session=object(), _pose_timeline_index=object())
    LabelingApp._close_state_repo(app)
    assert events == ["detach", "close"]
    assert app.state_repo is None and app._pose_timeline_index is None
    assert not hasattr(app, "pose_session") and not hasattr(app, "_pose_panel")


def test_pose_timer_and_position_never_checkpoint_separately():
    app = SimpleNamespace(annotation_type="Pose", video=object(), state_repo=object(),
                          labeling_timer=SimpleNamespace(cancel_session=lambda: None))
    LabelingApp._persist_video_time(app)
    LabelingApp.save_last_position(app)
    LabelingApp._finalize_video_time(app)
