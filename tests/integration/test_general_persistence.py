"""General's stored channel identities survive reopening and the full export."""
import csv
import json
from dataclasses import replace
from pathlib import Path

import pytest

from adapters.sqlite_repo import SqliteRepository
from domain.model import empty_bundle
from domain.project import ProjectPaths
from domain.templates import TemplateState
from service_layer.project_service import apply_project_template, plan_project_template
from service_layer.save_service import MetadataInputs, run_export


@pytest.mark.parametrize("mode", ["Normal", "Reliability"])
def test_general_reopens_and_exports_all_four_channels_without_csv_changes(tmp_path, mode):
    name = "session_reliability" if mode == "Reliability" else "session"
    paths = ProjectPaths(name, base_dir=str(tmp_path))
    frames = {0: empty_bundle(), 2: empty_bundle()}
    for frame, onset in ((0, "ON"), (2, "OFF")):
        frames[frame]["Note"] = "General session"
        frames[frame]["Params"]["Par1"] = onset
        frames[frame]["Changed"] = True
        for index, key in enumerate(("RH", "LH", "RL", "LL")):
            frames[frame][key].update(
                X=[137 + index % 2 * 176], Y=[102 + index // 2 * 164],
                Zones=[[str(index + 1)]], Onset=onset, LimbParams={"Par2": onset},
            )

    plan = plan_project_template(paths, "general")
    repo = SqliteRepository(paths.state_db)
    try:
        apply_project_template(repo, plan)
        repo.save_frames(frames, total_frames=3)
    finally:
        repo.close()

    assert plan_project_template(paths, "default").template == "general"
    repo = SqliteRepository(paths.state_db)
    try:
        assert repo.load_template() == TemplateState("general", True)
        restored = repo.load_frames()
    finally:
        repo.close()

    for frame in frames:
        assert restored[frame]["Note"] == "General session"
        assert restored[frame]["Params"] == frames[frame]["Params"]
        for key in ("RH", "LH", "RL", "LL"):
            for field in ("X", "Y", "Zones", "Onset", "LimbParams"):
                assert restored[frame][key][field] == frames[frame][key][field]

    metadata = MetadataInputs(
        program_version="test", video_name=name, labeling_mode=mode,
        special_zones_list=None, param_labels=None, limb_param_labels=None,
        labeling_time_seconds=None, template="general",
    )
    run_export(restored, paths, 25, metadata, total_frames=3)
    exported = json.loads(Path(paths.export_metadata).read_text(encoding="utf-8"))
    assert exported["Labeling Mode"] == mode
    assert exported["Channel Labels"] == {
        "RH": "Channel 1", "LH": "Channel 2", "RL": "Channel 3", "LL": "Channel 4",
    }
    with open(paths.export_csv, encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 4
    for key, zone in zip(("RH", "LH", "RL", "LL"), range(1, 5)):
        assert rows[0][f"{key}_Zones"] == json.dumps([[str(zone)]])
        assert rows[0][f"{key}_Onset"] == "ON"
        assert rows[2][f"{key}_Onset"] == "OFF"
        assert rows[0][f"{key}_Parameter_2"] == "ON"

    baseline = ProjectPaths("baseline", base_dir=str(tmp_path))
    run_export(restored, baseline, 25, replace(metadata, template="default"), total_frames=3)
    assert Path(paths.export_csv).read_bytes() == Path(baseline.export_csv).read_bytes()
