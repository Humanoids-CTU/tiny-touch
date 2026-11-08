"""Duplicate loading offers separate state and can resume the copied identity."""
import pytest

from adapters.project_catalog import list_projects
from gui_driver import load_video, dismiss_dialog

pytestmark = pytest.mark.gui


def test_copy_is_separate_and_resumes_its_own_project(app, workspace, monkeypatch):
    load_video(app, workspace, workspace.video, template="General")
    original = app.video_name
    app.state_repo.set_meta("copy_test_marker", "original")
    load_video(app, workspace, workspace.video, duplicate="Create new copy")
    assert app.video_name == original + "_copy"
    assert app.coding_setup.template == "default"
    assert app.state_repo.get_meta("copy_test_marker") is None
    app.state_repo.set_meta("copy_test_marker", "copy")

    load_video(app, workspace, workspace.video)
    assert app.video_name == original
    assert app.state_repo.get_meta("copy_test_marker") == "original"
    assert app.coding_setup.template == "general"
    copy_entry = next(entry for entry in list_projects() if entry.title == original + "_copy")
    monkeypatch.setattr("labeling_app.choose_video", lambda *args, **kwargs: copy_entry)
    app.load_video_btn.invoke()
    assert app.video_name == original + "_copy"
    assert app.state_repo.get_meta("copy_test_marker") == "copy"
    assert workspace.errors() == []


def test_duplicate_cancel_keeps_current_project(app, workspace):
    load_video(app, workspace, workspace.video)
    video = app.video
    repo = app.state_repo
    dismiss_dialog(app, "Video library", "Load new video")
    dismiss_dialog(app, "Select Mode", "Continue", radio_text="Normal")
    dismissed = dismiss_dialog(app, "Video already added", "Cancel")
    app.load_video_btn.invoke()
    assert dismissed["clicked"]
    assert app.video is video
    assert app.state_repo is repo
