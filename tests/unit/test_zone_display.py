"""Zone aliases preserve annotation identities and stay local to each project/template."""
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from adapters.sqlite_repo import SqliteRepository
from adapters.zone_masks import editable_zone_names, load_zone_masks, zone_label_positions, zones_dir
from domain.project import ProjectPaths
from domain.templates import TemplateState
from domain.touch import zones_at
from domain.zone_display import ZoneDisplaySettings
from service_layer.project_service import apply_project_template, plan_project_template
from service_layer.save_service import MetadataInputs, run_export


def test_labels_are_trimmed_and_blank_or_identity_names_restore_zone_ids():
    settings = ZoneDisplaySettings({"1": "  Light on  ", "2": " ", "3": "3"}, True)
    assert dict(settings.labels) == {"1": "Light on"}
    assert settings.label("2") == "2"
    with pytest.raises(TypeError):
        settings.labels["1"] = "Other"


@pytest.mark.parametrize("labels,show", [
    ({"1": "x" * 41}, False), ({"1": "two\nlines"}, False),
    ({"1": None}, False), ({1: "Name"}, False), ([], False), ({}, "false"),
])
def test_invalid_labels_are_rejected(labels, show):
    with pytest.raises(ValueError):
        ZoneDisplaySettings(labels, show)


@pytest.mark.parametrize("template,zone", [("default", "I"), ("alternate", "G"), ("general", "1")])
def test_project_names_reopen_without_locking_or_crossing_template_boundaries(tmp_path, template, zone):
    path = str(tmp_path / "state.db")
    repo = SqliteRepository(path)
    try:
        repo.save_template(TemplateState(template))
        assert repo.load_zone_display(template) == ZoneDisplaySettings()
        settings = ZoneDisplaySettings({zone: "Light on"}, True)
        repo.save_zone_display(template, settings)
        assert not repo.load_template().locked
        repo.lock_template()
        repo.save_zone_display(template, settings)
    finally:
        repo.close()
    repo = SqliteRepository(path)
    try:
        assert repo.load_zone_display(template) == settings
        assert repo.load_template().locked
        for other in {"default", "alternate", "general"} - {template}:
            assert repo.load_zone_display(other) == ZoneDisplaySettings()
    finally:
        repo.close()


def test_corrupt_saved_names_are_reported(tmp_path):
    repo = SqliteRepository(str(tmp_path / "state.db"))
    try:
        repo.set_meta("zone_display:general", '{"labels": {}, "show_names": "false"}')
        with pytest.raises(ValueError, match="Invalid saved zone names"):
            repo.load_zone_display("general")
    finally:
        repo.close()


@pytest.mark.parametrize("template,zone", [("default", "I"), ("alternate", "G"), ("general", "1")])
def test_reliability_inherits_names_once_then_keeps_its_own_settings(tmp_path, template, zone):
    original = ProjectPaths("video", base_dir=str(tmp_path))
    reliability = ProjectPaths("video_reliability", base_dir=str(tmp_path))
    source = SqliteRepository(original.state_db)
    try:
        source.save_template(TemplateState(template))
        source.save_zone_display(template, ZoneDisplaySettings({zone: "Source"}, True))
    finally:
        source.close()
    plan = plan_project_template(reliability, "default")
    repo = SqliteRepository(reliability.state_db)
    try:
        apply_project_template(repo, plan)
        assert repo.load_zone_display(template) == ZoneDisplaySettings({zone: "Source"}, True)
        repo.save_zone_display(template, ZoneDisplaySettings({zone: "Second pass"}, False))
        apply_project_template(repo, plan_project_template(reliability, "default"))
        assert repo.load_zone_display(template).label(zone) == "Second pass"
    finally:
        repo.close()


@pytest.mark.parametrize("template", ["default", "alternate", "general"])
def test_display_positions_hit_the_zone_they_label(template):
    masks = load_zone_masks(zones_dir(template))
    positions = zone_label_positions(masks)
    assert set(positions) == set(editable_zone_names(template))
    for zone, (x, y) in positions.items():
        assert zones_at(masks, x, y) == [zone]


@pytest.mark.parametrize("template,zone", [("default", "I"), ("alternate", "G"), ("general", "1")])
def test_save_service_exports_aliases_without_changing_csv(tmp_path, template, zone):
    paths = ProjectPaths("video", base_dir=str(tmp_path))
    metadata = MetadataInputs("test", "video", "Normal", None, None, None, None,
                              template=template)
    run_export({}, paths, 25, metadata, 2)
    before = Path(paths.export_csv).read_bytes()
    run_export({}, paths, 25, replace(metadata, zone_labels={zone: "Light on"}), 2)
    assert Path(paths.export_csv).read_bytes() == before
    exported = json.loads(Path(paths.export_metadata).read_text(encoding="utf-8"))
    assert exported["Zone Labels"] == {zone: "Light on"}
    assert list(exported)[-1] == "Zone Labels"


def test_failed_inheritance_does_not_leave_a_partly_initialized_project(tmp_path, monkeypatch):
    original = ProjectPaths("video", base_dir=str(tmp_path))
    reliability = ProjectPaths("video_reliability", base_dir=str(tmp_path))
    source = SqliteRepository(original.state_db)
    try:
        source.save_template(TemplateState("general"))
        source.save_zone_display("general", ZoneDisplaySettings({"1": "Light on"}, True))
    finally:
        source.close()
    plan = plan_project_template(reliability, "default")
    repo = SqliteRepository(reliability.state_db)
    original_write = repo._set_meta_unlocked

    def fail_on_names(key, value):
        if key == "zone_display:general":
            raise sqlite3.OperationalError("disk full")
        original_write(key, value)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(repo, "_set_meta_unlocked", fail_on_names)
            with pytest.raises(sqlite3.OperationalError, match="disk full"):
                apply_project_template(repo, plan)
        assert repo.load_template() == TemplateState()
        assert repo.load_zone_display("general") == ZoneDisplaySettings()
        apply_project_template(repo, plan)
        assert repo.load_template() == TemplateState("general", True)
        assert repo.load_zone_display("general").label("1") == "Light on"
    finally:
        repo.close()
