"""A shared setup can evolve without reinterpreting an already prepared video."""
import csv
import json
from dataclasses import replace

from adapters.coding_configs import CodingConfigStore
from adapters.export_reader import read_export_df
from adapters.sqlite_repo import SqliteRepository
from domain.coding_setup import default_coding_setup
from domain.model import empty_bundle
from domain.project import ProjectPaths
from service_layer.save_service import MetadataInputs, run_export


def test_prepared_video_exports_its_snapshot_after_shared_config_changes(tmp_path):
    store = CodingConfigStore(tmp_path / "config")
    original = replace(
        default_coding_setup("general"), name="Shared looking study",
        channel_labels={"RH": "Observer A", "LH": "Observer B", "RL": "Target A", "LL": "Target B"},
        zone_labels={"1": "Left target", "2": "Right target"},
        parameter_labels={"Par1": "Looking", "Par2": "Vocalizing", "Par3": "Moving"},
    )
    config_path = store.save(original, "coding_look.json")
    paths = ProjectPaths("video_a", str(tmp_path / "data"))
    repo = SqliteRepository(paths.state_db)
    try:
        repo.save_coding_setup(store.load(config_path))
        repo.mark_prepared()
    finally:
        repo.close()

    revised = replace(original, name="Revised study", parameter_labels={"Par1": "Sleeping", "Par2": "P2", "Par3": "P3"})
    store.save(revised, "coding_look.json", overwrite=True)
    assert store.load(config_path) == revised

    repo = SqliteRepository(paths.state_db)
    try:
        saved_setup = repo.load_coding_setup()
        assert saved_setup == original
        assert repo.load_preparation_state() == "ready"
    finally:
        repo.close()

    frame = empty_bundle()
    frame["RH"].update(X=[120, 9], Y=[130, 0], Zones=[["1", "2"], ["OUTSIDE"]], Onset="ON")
    frame["Params"]["Par1"] = "ON"
    run_export(
        {201: frame}, paths, 25.0,
        MetadataInputs(
            program_version="test", video_name="video_a", labeling_mode="Normal",
            special_zones_list=None, param_labels=None, limb_param_labels=None,
            labeling_time_seconds=0, template="general", coding_setup=saved_setup,
        ),
        total_frames=201,
    )
    with open(paths.export_csv, newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 202
    row = rows[201]
    assert row["Time_ms"] == "8040.000"
    assert json.loads(row["Channel1_XY"]) == [[120, 130], [9, 0]]
    assert json.loads(row["Channel1_Zones"]) == [["1", "2"], ["OUTSIDE"]]
    assert not any(key.startswith(("RH_", "LH_", "RL_", "LL_")) for key in row)
    with open(paths.export_metadata, encoding="utf-8") as stream:
        metadata = json.load(stream)
    assert metadata["Coding Setup"] == original.to_dict()
    assert metadata["Coding Setup"]["parameter_labels"]["Par1"] == "Looking"
    assert metadata["Coding Setup"]["channel_labels"]["Channel1"] == "Observer A"
    restored = read_export_df(paths.export_csv)
    assert restored.loc[201, "RH_X"] == "120,9"
    assert restored.loc[201, "RH_Y"] == "130,0"
    assert json.loads(restored.loc[201, "RH_Zones"]) == [["1", "2"], ["OUTSIDE"]]
