import copy
import json
from dataclasses import replace

import pytest

from adapters.coding_configs import CodingConfigStore
from adapters.sqlite_repo import SqliteRepository
from domain.coding_setup import CodingSetup, default_coding_setup
from domain.templates import TemplateState
from domain.zone_display import ZoneDisplaySettings
from service_layer.coding_setup_service import adopt_legacy_coding_setup, inherit_coding_setup


@pytest.fixture
def repo(tmp_path):
    repository = SqliteRepository(str(tmp_path / "video.db"))
    yield repository
    repository.close()


@pytest.mark.parametrize("template", ["default", "alternate", "general"])
def test_portable_roundtrip_preserves_complete_setup(template):
    setup = replace(default_coding_setup(template), name="Study α", zone_labels={"1": "Head"})
    raw = setup.to_dict()
    assert raw["channel_labels"]["Channel1"] == setup.channel_labels["RH"]
    assert CodingSetup.from_dict(json.loads(json.dumps(raw))) == setup
    assert copy.deepcopy(setup) == setup
    with pytest.raises(TypeError):
        setup.channel_labels["RH"] = "Changed"


def test_incomplete_or_future_configs_fail():
    raw = default_coding_setup().to_dict()
    raw["schema_version"] = 2
    with pytest.raises(ValueError):
        CodingSetup.from_dict(raw)
    with pytest.raises(ValueError):
        replace(default_coding_setup(), parameter_labels={"Par1": "Gaze"})
    with pytest.raises(ValueError):
        replace(default_coding_setup(), channel_labels={"RH": "a" * 41, "LH": "2", "RL": "3", "LL": "4"})


def test_portable_schema_uses_channel_parameters_and_reads_legacy_key():
    setup = default_coding_setup(limb_parameter_labels={"Par1": "LP1", "Par2": "LP2", "Par3": "LP3"})
    raw = setup.to_dict()
    assert raw["channel_parameter_labels"] == dict(setup.limb_parameter_labels)
    assert "limb_parameter_labels" not in raw
    assert CodingSetup.from_dict(raw) == setup
    legacy = dict(raw)
    legacy["limb_parameter_labels"] = legacy.pop("channel_parameter_labels")
    assert CodingSetup.from_dict(legacy) == setup
    assert "channel_parameter_labels" in CodingSetup.from_dict(legacy).to_dict()
    assert CodingSetup.from_dict(legacy).limb_parameter_labels["Par1"] == "LP1"


def test_legacy_database_snapshot_keeps_explicit_channel_labels(repo):
    setup = default_coding_setup(limb_parameter_labels={"Par1": "Historical grasp", "Par2": "LP2", "Par3": "LP3"})
    legacy = setup.to_dict()
    legacy["limb_parameter_labels"] = legacy.pop("channel_parameter_labels")
    repo.save_template(TemplateState("default", True))
    repo.set_meta_many({"coding_setup": json.dumps(legacy), "preparation_state": "ready"})
    assert repo.load_coding_setup() == setup
    repo.mark_prepared()
    assert repo.load_coding_setup().limb_parameter_labels["Par1"] == "Historical grasp"


def test_portable_schema_rejects_conflicting_channel_parameter_aliases():
    setup = default_coding_setup()
    raw = setup.to_dict()
    raw["limb_parameter_labels"] = dict(setup.limb_parameter_labels)
    assert CodingSetup.from_dict(raw) == setup
    raw["limb_parameter_labels"]["Par1"] = "Different study meaning"
    with pytest.raises(ValueError, match="Conflicting"):
        CodingSetup.from_dict(raw)


def test_portable_schema_requires_channel_parameters():
    raw = default_coding_setup().to_dict()
    raw.pop("channel_parameter_labels")
    with pytest.raises(ValueError):
        CodingSetup.from_dict(raw)


def test_named_store_import_and_overwrite_protection(tmp_path):
    store = CodingConfigStore(tmp_path / "configs")
    setup = default_coding_setup("general")
    path = store.save(setup, "study")
    assert store.list_configs() == [path]
    assert store.load(path) == setup
    with pytest.raises(FileExistsError):
        store.save(setup, "study")
    imported = store.import_config(path, "second.json")
    assert store.load(imported) == setup
    with pytest.raises(ValueError):
        store.save(setup, "../outside.json")


def test_preparation_locks_entire_snapshot_and_old_setters(repo):
    setup = default_coding_setup()
    repo.save_coding_setup(setup)
    assert repo.load_preparation_state() == "draft"
    repo.save_coding_setup(setup, "preparing")
    repo.mark_prepared()
    assert repo.load_preparation_state() == "ready"
    assert repo.load_coding_setup() == setup
    for changed in (replace(setup, name="Changed"), replace(setup, template="general"),
                    replace(setup, parameter_labels={"Par1": "Changed", "Par2": "P2", "Par3": "P3"})):
        with pytest.raises(ValueError):
            repo.save_coding_setup(changed)
    with pytest.raises(ValueError):
        repo.save_zone_display("default", ZoneDisplaySettings({"1": "Changed"}))
    with pytest.raises(ValueError):
        repo.save_template(TemplateState("general"))
    repo.save_zone_display("default", ZoneDisplaySettings(show_names=True))
    assert repo.load_zone_display("default").show_names


def test_reopen_snapshot_ignores_later_config_file_changes(tmp_path):
    path = str(tmp_path / "snapshot.db")
    original = default_coding_setup("general")
    with_repo = SqliteRepository(path)
    with_repo.save_coding_setup(original)
    with_repo.mark_prepared()
    with_repo.close()
    reopened = SqliteRepository(path)
    try:
        assert reopened.load_coding_setup() == original
        assert reopened.load_preparation_state() == "ready"
    finally:
        reopened.close()


def test_legacy_missing_labels_requires_review(repo):
    repo.save_template(TemplateState("default"))
    assert adopt_legacy_coding_setup(repo) is None
    assert repo.load_preparation_state() == "needs_review"
    assert repo.load_coding_setup() is None


def test_legacy_adoption_and_reliability_preserve_historical_labels(repo, tmp_path):
    repo.save_template(TemplateState("general"))
    repo.save_zone_display("general", ZoneDisplaySettings({"1": "Target"}))
    original = default_coding_setup("general")
    metadata = {"Param Labels": {"Parameter_1": "Historical gaze", "Parameter_2": "P2", "Parameter_3": "P3"},
                "Limb Param Labels": {f"XX_Parameter_{i}": original.limb_parameter_labels[f"Par{i}"] for i in (1, 2, 3)}}
    setup = adopt_legacy_coding_setup(repo, metadata)
    assert setup.parameter_labels["Par1"] == "Historical gaze"
    assert setup.zone_labels == {"1": "Target"}
    target = SqliteRepository(str(tmp_path / "reliability.db"))
    try:
        assert inherit_coding_setup(repo, target) == setup
        target.mark_prepared()
        assert target.load_coding_setup() == setup
    finally:
        target.close()


def test_legacy_cleared_aliases_override_stale_export(repo):
    repo.save_template(TemplateState("general"))
    repo.save_zone_display("general", ZoneDisplaySettings())
    defaults = default_coding_setup("general")
    metadata = {"Param Labels": dict(defaults.parameter_labels),
                "Limb Param Labels": dict(defaults.limb_parameter_labels), "Zone Labels": {"1": "Stale"}}
    assert adopt_legacy_coding_setup(repo, metadata).zone_labels == {}


def test_legacy_template_lock_cannot_be_bypassed_by_new_snapshot(repo):
    repo.save_template(TemplateState("default", True))
    with pytest.raises(ValueError):
        repo.save_coding_setup(default_coding_setup("general"))


@pytest.mark.parametrize("zone", ["NN", "LINE", "not-a-zone", "1"])
def test_configuration_rejects_aliases_outside_template(tmp_path, repo, zone):
    setup = replace(default_coding_setup("default"), zone_labels={zone: "Alias"})
    with pytest.raises(ValueError):
        repo.save_coding_setup(setup)
    with pytest.raises(ValueError):
        CodingConfigStore(tmp_path).save(setup, "bad")


@pytest.mark.parametrize("filename", ["CON", "nul.json", "COM1.json", "trailing. ", "bad?.json", "bad\nname"])
def test_configuration_rejects_nonportable_filenames(tmp_path, filename):
    with pytest.raises(ValueError):
        CodingConfigStore(tmp_path).save(default_coding_setup(), filename)


def test_read_only_legacy_review_preserves_partial_historical_labels(repo):
    from service_layer.coding_setup_service import inspect_legacy_coding_setup
    repo.save_template(TemplateState("default", True))
    metadata = {"Param Labels": {"Parameter_1": "Historical gaze"},
                "Limb Param Labels": {"XX_Parameter_2": "Historical reach"},
                "Zone Labels": {"A": "Face"}}
    review = inspect_legacy_coding_setup(repo, metadata)
    assert review.setup.parameter_labels["Par1"] == "Historical gaze"
    assert review.setup.limb_parameter_labels["Par2"] == "Historical reach"
    assert review.setup.zone_labels == {"A": "Face"}
    assert review.setup.channel_labels["RH"] == "Right Hand"
    assert review.needs_review
    assert "P2" in review.warning and "CP1" in review.warning
    assert repo.load_coding_setup() is None
    assert repo.get_meta("preparation_state") is None


def test_read_only_legacy_review_accepts_actual_historical_metadata(repo):
    from service_layer.coding_setup_service import inspect_legacy_coding_setup
    repo.save_template(TemplateState("general"))
    metadata = json.loads('''{"template":"general","Param Labels":{"Parameter_1":"Looking","Parameter_2":"Quiet","Parameter_3":"Awake"},"Limb Param Labels":{"XX_Parameter_1":"Grasp","XX_Parameter_2":"Reach","XX_Parameter_3":"Other"},"Channel Labels":{"RH":"Tool 1","LH":"Tool 2","RL":"Tool 3","LL":"Tool 4"},"Zone Labels":{"1":"Target"}}''')
    review = inspect_legacy_coding_setup(repo, metadata)
    assert not review.needs_review
    assert review.warning == ""
    assert review.setup.parameter_labels == {"Par1": "Looking", "Par2": "Quiet", "Par3": "Awake"}
    assert review.setup.channel_labels["RH"] == "Tool 1"
    assert repo.load_coding_setup() is None


def test_read_only_legacy_review_rejects_conflicting_template(repo):
    from service_layer.coding_setup_service import inspect_legacy_coding_setup
    repo.save_template(TemplateState("general"))
    with pytest.raises(ValueError, match="template"):
        inspect_legacy_coding_setup(repo, {"template": "default"})
