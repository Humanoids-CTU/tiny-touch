"""Typed setup/loading foundations; no windows or project writes on inspection."""
from pathlib import Path
import json
import sqlite3
import pytest

from adapters.pose_sqlite_repo import PoseSqliteRepository, PoseStorageError
from adapters.project_catalog import list_projects, SOURCE_META
from adapters.sqlite_repo import SqliteRepository
from domain.pose_setup import PoseCodingSetup
from domain.coding_setup import default_coding_setup
from domain.project import ProjectPaths
from service_layer.project_service import inspect_coding_setup, can_resume_preparation, open_state
from service_layer.project_service import validate_source_association, source_fingerprint
from service_layer.project_copy import next_copy_project


def test_pose_setup_has_only_dedicated_template_and_global_labels():
    setup = PoseCodingSetup(parameter_labels={"Par1": "Visible", "Par2": "Moving", "Par3": "Other"})
    assert PoseCodingSetup.from_dict(setup.to_dict()) == setup
    assert not hasattr(setup, "channel_labels")
    assert setup.template == "alternate"
    with pytest.raises(ValueError, match="Alternate"):
        PoseCodingSetup(template="default")
    with pytest.raises(TypeError):
        setup.parameter_labels["Par1"] = "Changed"


def test_touch_and_pose_workspaces_coexist_and_catalog_restore_types(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"source")
    base = str(tmp_path / "data")
    touch_paths = ProjectPaths("clip", base)
    pose_paths = ProjectPaths("clip", base, "Pose")
    Path(touch_paths.state_dir).mkdir(parents=True)
    touch = SqliteRepository(touch_paths.state_db)
    touch.save_coding_setup(default_coding_setup())
    touch.mark_prepared()
    touch.set_meta(SOURCE_META, str(source))
    touch.close()
    pose = open_state(pose_paths, fps=25, program_version="test")
    setup = PoseCodingSetup(name="Zone study")
    pose.save_coding_setup(setup)
    pose.mark_prepared()
    pose.set_meta(SOURCE_META, str(source))
    pose.close()
    before = Path(pose_paths.state_db).read_bytes()
    assert inspect_coding_setup(pose_paths) == (setup, True)
    assert can_resume_preparation(pose_paths)
    entries = list_projects(base)
    assert {(entry.annotation_type, entry.template) for entry in entries} == {("Touch", "default"), ("Pose", "alternate")}
    assert all(entry.source == str(source) for entry in entries)
    assert Path(pose_paths.state_db).read_bytes() == before


def test_pose_reliability_can_prepare_independently(tmp_path):
    paths = ProjectPaths.for_video("clip", reliability=True, base_dir=str(tmp_path), annotation_type="Pose")
    setup, ready = inspect_coding_setup(paths)
    assert isinstance(setup, PoseCodingSetup)
    assert ready is False
    assert not Path(paths.state_db).exists()
    assert paths.original.annotation_type == "Pose"
    assert next_copy_project(paths).annotation_type == "Pose"
    repo = open_state(paths)
    repo.save_coding_setup(setup)
    repo.mark_prepared()
    repo.close()
    assert inspect_coding_setup(paths) == (setup, True)
    assert not Path(paths.original.state_db).exists()


def test_pose_ready_setup_is_locked(tmp_path):
    repo = PoseSqliteRepository(tmp_path / "pose.db")
    setup = PoseCodingSetup()
    repo.save_coding_setup(setup)
    repo.mark_prepared()
    with pytest.raises(ValueError, match="locked"):
        repo.save_coding_setup(PoseCodingSetup(name="Different"))
    assert repo.load_coding_setup() == setup
    repo.close()


@pytest.mark.parametrize("params", [{"LH": "ON"}, {"Par1": "invalid"}, []])
def test_invalid_pose_shared_params_are_rejected(tmp_path, params):
    path = tmp_path / "pose.db"
    repo = PoseSqliteRepository(path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO shared_frames VALUES (?, ?, ?)", (1, "note", json.dumps(params)))
    with pytest.raises(PoseStorageError, match="shared frame"):
        repo.load_frames()
    repo.close()


def test_invalid_annotation_type_is_rejected():
    with pytest.raises(ValueError, match="annotation type"):
        ProjectPaths("clip", annotation_type="unknown")


@pytest.mark.parametrize("existing_type,new_type", [("Touch", "Pose"), ("Pose", "Touch")])
def test_other_annotation_type_guards_shared_frame_source(tmp_path, monkeypatch, existing_type, new_type):
    monkeypatch.setattr("service_layer.project_service.DEFAULT_VIDEOS_DIR", str(tmp_path / "videos"))
    first = tmp_path / "clip.mp4"
    second = tmp_path / "clip.mov"
    first.write_bytes(b"original")
    second.write_bytes(b"different")
    paths = ProjectPaths("clip", str(tmp_path / "data"), existing_type)
    Path(paths.state_dir).mkdir(parents=True)
    repo = open_state(paths)
    repo.set_meta(SOURCE_META, str(first))
    repo.set_meta("source_video_sha256", source_fingerprint(first))
    repo.close()
    candidate = ProjectPaths("clip", paths.base_dir, new_type)
    with pytest.raises(ValueError, match="source video content changed"):
        validate_source_association(candidate, str(second))
    validate_source_association(candidate, str(first))
    assert not Path(candidate.state_db).exists()


def test_unknown_other_type_source_cannot_reuse_shared_frames(tmp_path, monkeypatch):
    monkeypatch.setattr("service_layer.project_service.DEFAULT_VIDEOS_DIR", str(tmp_path / "videos"))
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"source")
    paths = ProjectPaths("clip", str(tmp_path / "data"))
    Path(paths.state_dir).mkdir(parents=True)
    repo = open_state(paths)
    repo.close()
    candidate = ProjectPaths("clip", paths.base_dir, "Pose")
    with pytest.raises(ValueError, match="no verified source"):
        validate_source_association(candidate, str(source))


def test_pose_empty_workspace_does_not_invoke_touch_legacy_inference(tmp_path):
    paths = ProjectPaths("clip", str(tmp_path), "Pose")
    repo = open_state(paths)
    repo.close()
    assert inspect_coding_setup(paths) == (PoseCodingSetup(), False)


def test_pose_zone_aliases_roundtrip_and_keep_zone_ids(tmp_path):
    from dataclasses import replace
    setup = PoseCodingSetup(zone_labels={"A": "Left foot", "Q": "Face"})
    with pytest.raises(TypeError):
        setup.zone_labels["A"] = "changed"
    with pytest.raises(ValueError, match="Unknown"):
        replace(setup, zone_labels={"unknown": "Wrong"})
    repo = PoseSqliteRepository(tmp_path / "pose.db")
    repo.save_coding_setup(setup)
    repo.mark_prepared()
    repo.close()
    reopened = PoseSqliteRepository(tmp_path / "pose.db")
    assert reopened.load_coding_setup() == setup
    reopened.close()


def test_pose_wizard_captures_zone_names_and_global_parameters_without_channels():
    from gui.coding_setup_wizard import CodingSetupWizard
    from domain.pose import POSE_ZONES
    from types import SimpleNamespace
    wizard = CodingSetupWizard.__new__(CodingSetupWizard)
    wizard.pose = True
    wizard.setup = PoseCodingSetup()
    wizard.step = 1
    wizard.variables = {zone: SimpleNamespace(get=lambda z=zone: "Foot" if z == "A" else "") for zone in wizard.editable_zones()}
    assert set(wizard.editable_zones()) == set(POSE_ZONES)
    wizard.capture()
    assert dict(wizard.setup.zone_labels) == {"A": "Foot"}
    wizard.step = 2
    wizard.variables = {key: SimpleNamespace(get=lambda v=value: v) for key, value in
                        {"name": "Study", "Par1": "Visible", "Par2": "Moving", "Par3": "Other"}.items()}
    wizard.capture()
    assert wizard.setup.name == "Study"
    assert wizard.setup.parameter_labels["Par1"] == "Visible"
    assert wizard.setup.zone_labels["A"] == "Foot"
    assert not hasattr(wizard.setup, "channel_labels")


def test_reuse_pose_and_alternate_touch_coding_configurations(tmp_path):
    from dataclasses import replace
    from adapters.coding_configs import CodingConfigStore
    touch_store = CodingConfigStore(tmp_path)
    pose_store = CodingConfigStore(tmp_path, pose=True)
    original = replace(default_coding_setup("alternate"), zone_labels={"A": "Foot"})
    touch_path = touch_store.save(original, "Touch study")
    pose = pose_store.load(touch_path)
    assert pose.zone_labels["A"] == "Foot"
    assert not hasattr(pose, "channel_labels")
    pose_path = pose_store.save(pose, "Pose study")
    assert pose_store.load(pose_path) == pose
    default_path = touch_store.save(default_coding_setup(), "Default study")
    assert pose_store.list_configs() == [pose_path, touch_path]
    assert touch_store.list_configs() == [default_path, touch_path]
    imported = CodingConfigStore(tmp_path / "imported", pose=True)
    assert imported.load(imported.import_config(pose_path)) == pose
    with pytest.raises(ValueError, match="Touch"):
        touch_store.load(pose_path)
