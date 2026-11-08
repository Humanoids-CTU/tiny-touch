"""Human report labels must never merge zones or alter exported numeric results."""
import json
from html import escape
from pathlib import Path

import pytest
from PIL import Image

from adapters import plotting
from domain.model import LIMBS, empty_bundle
from domain.project import ProjectPaths
from gui.resource_utils import asset_path
from service_layer.analysis_service import run_analysis
from service_layer.save_service import MetadataInputs, run_export


def project(tmp_path, template, zones):
    paths = ProjectPaths("labels", base_dir=str(tmp_path))
    frames = {}
    for frame, zone, onset in [(0, zones[0], "ON"), (1, zones[0], "OFF"),
                               (2, zones[1], "ON"), (3, zones[1], "OFF")]:
        frames[frame] = empty_bundle()
        for key in LIMBS:
            frames[frame][key].update(X=[137], Y=[102], Zones=[[zone]], Onset=onset)
    inputs = MetadataInputs("test", "labels", "Normal", None, None, None, None, template=template)
    run_export(frames, paths, 25, inputs, 4)
    return paths


@pytest.mark.parametrize("template,zones", [("default", ("I", "J")), ("alternate", ("G", "H")),
                                           ("general", ("1", "2"))])
def test_reports_use_exported_names_without_changing_calculations(tmp_path, monkeypatch, template, zones):
    paths = project(tmp_path, template, zones)
    metadata_path = Path(paths.export_metadata)
    metadata = json.loads(metadata_path.read_text())
    metadata.pop("Metadata Format Version")
    metadata["template"] = metadata.pop("Coding Setup")["template"]
    # Missing optional mappings are valid, including old General exports.
    metadata.pop("Channel Labels", None)
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    baseline = run_analysis(paths, output_folder=str(tmp_path / "baseline"))
    source_csv = Path(paths.export_csv).read_bytes()
    metadata["Zone Labels"] = {zone: "Light <on> & off" for zone in zones}
    if template == "general":
        metadata["Channel Labels"] = {"RH": "Channel One"}
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    figures = {}
    original = plotting._write_figure

    def capture(figure, output_folder, filename, **kwargs):
        figures[filename] = figure
        return original(figure, output_folder, filename, **kwargs)

    monkeypatch.setattr(plotting, "_write_figure", capture)
    result = run_analysis(paths, output_folder=str(tmp_path / "renamed"))
    assert result.stats == baseline.stats
    assert Path(paths.export_csv).read_bytes() == source_csv
    for filename in ("analysis_table_frames.csv", "analysis_table_seconds.csv"):
        assert (tmp_path / "baseline" / filename).read_bytes() == (tmp_path / "renamed" / filename).read_bytes()
    heatmap = figures["heatmap_Channel1.html"]
    assert heatmap.layout.xaxis.type == heatmap.layout.yaxis.type == "category"
    assert list(heatmap.layout.xaxis.categoryarray) == list(heatmap.data[0].x)
    assert zones[0] in heatmap.data[0].x and zones[1] in heatmap.data[0].x
    for zone in zones:
        assert escape(f"Light <on> & off ({zone})") in heatmap.layout.xaxis.ticktext
    trajectory = figures["touch_trajectory.html"]
    assert any(escape(f"Light <on> & off ({zones[0]})") in text
               for trace in trajectory.data for text in trace.text)
    assert len(figures["zone_table.html"].data[0].cells.values[0]) == 8
    channel = "Channel One" if template == "general" else "Channel 1"
    assert channel in heatmap.layout.title.text
    assert any(trace.name == channel for trace in figures["histogram.html"].data)
    assert any(trace.name == channel for trace in figures["histogram_2.html"].data)
    summary = figures["table.html"].data[0]
    assert channel in summary.cells.values[0]
    expected_channels = (["Channel One", "Channel 2", "Channel 3", "Channel 4"] if template == "general"
                         else ["Channel 1", "Channel 2", "Channel 3", "Channel 4"])
    assert list(summary.cells.values[0]) == expected_channels
    assert [trace.name for trace in figures["histogram.html"].data] == expected_channels
    assert summary.header.values[0] == "Channel"
    assert any(channel in trace.name for trace in trajectory.data)
    master = Path(result.master_html).read_text(encoding="utf-8")
    assert "Zone touch counts" in master
    if template == "general":
        assert "limb diagrams" not in master and "Right Hand" not in master
        assert "Channel 2" in master and "Channel 3" in master and "Channel 4" in master


@pytest.mark.parametrize("key,value", [("Zone Labels", None), ("Zone Labels", []),
                                       ("Zone Labels", {"1": 123}), ("Channel Labels", {"XX": "Other"})])
def test_bad_labels_fail_before_creating_reports(tmp_path, key, value):
    paths = project(tmp_path, "general", ("1", "2"))
    metadata = json.loads(Path(paths.export_metadata).read_text())
    metadata.pop("Metadata Format Version")
    metadata["template"] = metadata.pop("Coding Setup")["template"]
    metadata[key] = value
    Path(paths.export_metadata).write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError):
        run_analysis(paths)
    assert not Path(paths.plots_dir).exists()


def test_general_footer_highlights_only_the_owning_channel():
    with Image.open(asset_path("icons/general.png")) as image:
        neutral = image.convert("RGB")
    for selected, key in enumerate(("RH", "LH", "RL", "LL")):
        with Image.open(asset_path(f"icons/general_{key}.png")) as image:
            assert image.size == (450, 696)
            assert image.crop((0, 0, 450, 600)).tobytes() == neutral.crop((0, 0, 450, 600)).tobytes()
            for index in range(4):
                assert image.getpixel((20 + index * 108, 616)) == ((27, 175, 208) if selected == index else (255, 255, 255))
