import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageDraw

from adapters.export_diagram import write_export_diagram
from domain.coding_setup import default_coding_setup
from domain.project import ProjectPaths
from service_layer.analysis_service import resolve_report_labels
from service_layer.save_service import MetadataInputs, run_export


@pytest.mark.parametrize("template,zone", [("default", "D"), ("alternate", "D"), ("general", "1")])
def test_export_contains_labeled_image_and_one_settings_snapshot(tmp_path, template, zone):
    paths = ProjectPaths("clip", str(tmp_path))
    setup = replace(default_coding_setup(template), zone_labels={zone: "Study target"})
    inputs = MetadataInputs("test", "clip", "Normal", None, None, None, 0,
                            template=template, coding_setup=setup)
    run_export({}, paths, 25, inputs, 0)
    meta = json.loads(Path(paths.export_metadata).read_text())
    assert type(setup).from_dict(meta["Coding Setup"]) == setup
    assert not {"Zone Labels", "Channel Labels", "Param Labels", "Channel Param Labels", "template"} & meta.keys()
    assert "zones" not in meta["Diagram"] and "template" not in meta["Diagram"]
    assert meta["Diagram"]["image"] == Path(paths.export_diagram).name
    assert meta["Diagram"]["image_sha256"] == hashlib.sha256(Path(paths.export_diagram).read_bytes()).hexdigest()
    labels = resolve_report_labels(paths.export_metadata)
    assert labels.zone_labels[zone] == "Study target"
    assert labels.channel("RH") == setup.channel_labels["RH"]
    plain_path = tmp_path / "plain.png"
    write_export_diagram(plain_path, default_coding_setup(template))
    with Image.open(paths.export_diagram) as labeled, Image.open(plain_path) as plain:
        assert labeled.format == "PNG"
        assert ImageChops.difference(labeled, plain).getbbox() is not None


def test_diagram_publish_failure_restores_entire_previous_export(tmp_path, monkeypatch):
    from service_layer import save_service
    paths = ProjectPaths("clip", str(tmp_path))
    inputs = MetadataInputs("test", "clip", "Normal", None, None, None, 0, template="general")
    run_export({}, paths, 25, inputs, 0)
    targets = (paths.export_csv, paths.export_metadata, paths.export_diagram)
    before = {path: Path(path).read_bytes() for path in targets}
    original = save_service.os.replace
    failed = False

    def fail_once(source, target):
        nonlocal failed
        if target == paths.export_diagram and not failed:
            failed = True
            raise OSError("image publication failed")
        return original(source, target)

    monkeypatch.setattr(save_service.os, "replace", fail_once)
    with pytest.raises(OSError, match="image publication"):
        run_export({}, paths, 30, inputs, 3)
    assert failed
    assert {path: Path(path).read_bytes() for path in targets} == before


def test_diagram_generation_failure_leaves_published_export_untouched(tmp_path, monkeypatch):
    paths = ProjectPaths("clip", str(tmp_path))
    inputs = MetadataInputs("test", "clip", "Normal", None, None, None, 0, template="general")
    run_export({}, paths, 25, inputs, 0)
    targets = (paths.export_csv, paths.export_metadata, paths.export_diagram)
    before = {path: Path(path).read_bytes() for path in targets}

    def fail(*args):
        raise OSError("missing diagram")

    monkeypatch.setattr("adapters.export_writer.write_export_diagram", fail)
    with pytest.raises(OSError, match="missing diagram"):
        run_export({}, paths, 30, inputs, 3)
    assert {path: Path(path).read_bytes() for path in targets} == before


def test_reference_prints_saved_names_ids_and_settings_without_legend(tmp_path, monkeypatch):
    printed = []
    original_text = ImageDraw.ImageDraw.text
    original_multiline = ImageDraw.ImageDraw.multiline_text

    def text(self, xy, value, *args, **kwargs):
        printed.append(value)
        return original_text(self, xy, value, *args, **kwargs)

    def multiline(self, xy, value, *args, **kwargs):
        printed.append(value)
        return original_multiline(self, xy, value, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", text)
    monkeypatch.setattr(ImageDraw.ImageDraw, "multiline_text", multiline)
    setup = replace(default_coding_setup("general"), zone_labels={"1": "Caregiver touch"},
                    channel_labels={"RH": "Probe", "LH": "Other probe", "RL": "Third", "LL": "Fourth"},
                    parameter_labels={"Par1": "Attention", "Par2": "Task", "Par3": "Trial"},
                    limb_parameter_labels={"Par1": "Pressure", "Par2": "Speed", "Par3": "Direction"})
    write_export_diagram(tmp_path / "reference.png", setup)
    assert "Caregiver touch\n(1)" in printed
    for value in ("Channels", "Parameters", "Channel parameters", "Channel1: Probe", "Parameter_1: Attention",
                  "Parameter_1: Pressure", "  Zones: 9"):
        assert value in printed
    assert not any("legend" in value.lower() or "IDs match" in value or "Zone reference" in value for value in printed)


@pytest.mark.parametrize("template", ["default", "alternate", "general"])
def test_long_zone_names_are_complete_and_labels_do_not_overlap_or_clip(template):
    from adapters.export_diagram import MARGIN, SCALE, _label_layout
    from adapters.zone_masks import load_zone_masks, zones_dir, zone_label_positions
    from domain.templates import get_template

    setup = default_coding_setup(template)
    positions = zone_label_positions(load_zone_masks(zones_dir(template), coding_setup=setup))
    name = "A carefully configured long target name"
    setup = replace(setup, zone_labels={zone: name for zone in positions})
    width, height = get_template(template).native_size
    bounds = (MARGIN, MARGIN, MARGIN + width * SCALE, MARGIN + height * SCALE)
    image = Image.new("RGB", (bounds[2] + MARGIN, bounds[3] + MARGIN))
    labels = _label_layout(ImageDraw.Draw(image), setup, positions, bounds)
    assert len(labels) == len(positions)
    for i, label in enumerate(labels):
        assert " ".join(label["text"].splitlines()[:-1]) == name
        left, top, right, bottom = label["rect"]
        assert bounds[0] <= left < right <= bounds[2]
        assert bounds[1] <= top < bottom <= bounds[3]
        for other in labels[i + 1:]:
            ol, ot, ore, ob = other["rect"]
            assert right <= ol or ore <= left or bottom <= ot or ob <= top
