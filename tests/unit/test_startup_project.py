"""The app reopens the project that was open at the last close, or the library."""
from types import SimpleNamespace

import pytest

import labeling_app
from adapters import config as config_utils
from adapters.config import load_config, load_last_project, save_config, save_last_project
from adapters.project_catalog import find_resumable
from labeling_app import LabelingApp


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    # Never the developer's real config.json.
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_utils, "get_config_path", lambda: str(path))
    return path


def entry(title, annotation_type="Touch", source="clip.mp4", state="ready"):
    return SimpleNamespace(title=title, annotation_type=annotation_type,
                           source=source, preparation_state=state)


def test_last_project_round_trips_and_keeps_other_settings(config_path):
    save_config({"jump_seconds": 2.0})
    assert load_last_project() is None
    save_last_project(("cat3_reliability", "Pose"))
    assert load_last_project() == ("cat3_reliability", "Pose")
    assert load_config()["jump_seconds"] == 2.0
    save_last_project(None)
    assert load_last_project() is None


@pytest.mark.parametrize("stored", ["cat3", {"name": "cat3"}, {"name": "", "annotation_type": "Touch"},
                                    {"name": "cat3", "annotation_type": "Other"}, 7])
def test_unusable_stored_project_means_none(config_path, stored):
    save_config({"last_project": stored})
    assert load_last_project() is None


def test_find_resumable_needs_the_same_kind_a_source_and_a_prepared_project():
    touch, pose = entry("cat3"), entry("cat3", "Pose")
    assert find_resumable([touch, pose], ("cat3", "Pose")) is pose
    assert find_resumable([touch, pose], ("other", "Touch")) is None
    assert find_resumable([touch], None) is None
    assert find_resumable([entry("cat3", source=None)], ("cat3", "Touch")) is None
    assert find_resumable([entry("cat3", state="draft")], ("cat3", "Touch")) is None


@pytest.mark.parametrize("last_project, resumed", [(("cat3", "Touch"), True),
                                                   (("gone", "Touch"), False), (None, False)])
def test_startup_resumes_the_last_project_or_asks_in_the_library(monkeypatch, last_project, resumed):
    saved = entry("cat3")
    monkeypatch.setattr(labeling_app, "list_projects", lambda: [saved])
    opened = []
    app = SimpleNamespace(load_video=opened.append)
    LabelingApp.open_startup_project(app, last_project)
    # None makes the load flow show the video library.
    assert opened == [saved if resumed else None]
