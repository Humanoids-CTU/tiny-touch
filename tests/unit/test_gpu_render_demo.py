"""Frame access and decoding must preserve identity without a GPU dependency."""

import importlib.util
from pathlib import Path

from PIL import Image
import pytest


DEMOS = Path(__file__).resolve().parents[2] / "demos"


def load_demo(name):
    spec = importlib.util.spec_from_file_location(name, DEMOS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


demo = load_demo("gpu_render_demo")
identity = load_demo("frame_identity")


def test_frame_access_uses_numeric_order(tmp_path):
    for index in reversed(range(12)):
        (tmp_path / f"frame{index}.jpg").touch()
    (tmp_path / "frame_preview.jpg").touch()
    assert [p.name for p in demo.frame_paths(tmp_path)] == [f"frame{i}.jpg" for i in range(12)]


@pytest.mark.parametrize("indices", [[], [0, 2], [1, 2]])
def test_rejects_missing_frames_instead_of_shifting_frame_numbers(tmp_path, indices):
    for index in indices:
        (tmp_path / f"frame{index}.jpg").touch()
    with pytest.raises(ValueError, match="complete"):
        demo.frame_paths(tmp_path)


def test_decoded_4k_jpeg_keeps_frame_identity_after_file_closes(tmp_path):
    path = tmp_path / "frame50.jpg"
    identity.numbered_frame(50).resize((3840, 2160), Image.Resampling.BILINEAR).save(
        path, quality=85)
    decoded = demo.decode(path)
    path.unlink()
    assert identity.read_marker(decoded) == 50


def test_portrait_frame_fits_without_stretching_or_cropping():
    assert demo.fit_rect((1080, 1920), (1280, 720)) == (437, 0, 405, 720)
