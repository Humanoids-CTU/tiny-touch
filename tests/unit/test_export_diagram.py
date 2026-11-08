import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image, ImageChops

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
    assert meta["Coding Setup"] == setup.to_dict()
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
