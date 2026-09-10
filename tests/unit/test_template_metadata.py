"""Template provenance must never silently fall back to global preferences."""

from dataclasses import replace
from pathlib import Path

import pytest

from adapters.export_writer import write_export_metadata
from domain.project import ProjectPaths
from service_layer.analysis_service import resolve_template
from service_layer.save_service import MetadataInputs, run_export


def _write_metadata(path, template):
    write_export_metadata(
        path, program_version="test", video_name="vid", labeling_mode="Normal",
        frame_rate=25, clothes_list=None, template=template,
    )


@pytest.mark.parametrize("template", ["default", "alternate"])
def test_metadata_round_trip(tmp_path, template):
    path = str(tmp_path / "vid_metadata.json")
    _write_metadata(path, template)
    assert resolve_template(path) == template


@pytest.mark.parametrize("content", [
    "not json", "[]", '{"template": true}', '{"template": null}',
    '{"template": "unknown-v1"}', '{}',
])
def test_bad_metadata_does_not_fall_back_to_explicit_choice(tmp_path, content):
    path = tmp_path / "vid_metadata.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        resolve_template(str(path), template="default")


@pytest.mark.parametrize("template", [None, "default", "alternate"])
def test_export_without_metadata_is_rejected_even_with_explicit_template(tmp_path, template):
    path = str(tmp_path / "absent.json")
    with pytest.raises(ValueError, match="metadata"):
        resolve_template(path, template=template)


def test_explicit_choice_cannot_override_metadata(tmp_path):
    path = str(tmp_path / "vid_metadata.json")
    _write_metadata(path, "alternate")
    with pytest.raises(ValueError, match="Export uses template"):
        resolve_template(path, template="default")


def test_invalid_template_preserves_existing_export_files(tmp_path):
    paths = ProjectPaths("vid", base_dir=str(tmp_path))
    Path(paths.export_dir).mkdir(parents=True)
    destinations = [paths.export_csv, paths.export_metadata]
    for path in destinations:
        Path(path).write_text("original", encoding="utf-8")
    metadata = MetadataInputs("test", "vid", "Normal", None, None, None, None)
    for template in (None, "unknown-v1"):
        with pytest.raises(ValueError):
            run_export({}, paths, 25, replace(metadata, template=template), 5)
        assert all(Path(path).read_text(encoding="utf-8") == "original" for path in destinations)


def test_metadata_replace_failure_preserves_previous_file(tmp_path, monkeypatch):
    path = str(tmp_path / "vid_metadata.json")
    _write_metadata(path, "default")

    def fail_replace(*args):
        raise OSError("disk failure")

    monkeypatch.setattr("adapters.atomic_io.os.replace", fail_replace)
    with pytest.raises(OSError, match="disk failure"):
        _write_metadata(path, "alternate")
    assert resolve_template(path) == "default"
    assert not Path(path + ".tmp").exists()
