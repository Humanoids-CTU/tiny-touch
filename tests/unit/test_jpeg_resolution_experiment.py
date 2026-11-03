"""Observable dimensions and burned frame identity for the isolated experiment."""

import importlib.util
from pathlib import Path

from PIL import Image
import pytest

spec = importlib.util.spec_from_file_location(
    "benchmark_jpeg_resolution", Path(__file__).resolve().parents[2] /
    "demos" / "benchmark_jpeg_resolution.py")
experiment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(experiment)


@pytest.mark.parametrize("source,expected", [
    ((3840, 2160), (1920, 1080)), ((1920, 1080), (1920, 1080)),
    ((640, 360), (640, 360)), ((2160, 3840), (607, 1080)),
    ((4096, 2160), (1920, 1012)), ((3000, 3000), (1080, 1080)),
    ((1001, 501), (1001, 501)),
])
def test_cap_fits_without_upscale_or_stretch(source, expected):
    assert experiment.capped_size(*source) == expected


@pytest.mark.parametrize("source", [(0, 1080), (1920, -1)])
def test_rejects_invalid_dimensions(source):
    with pytest.raises(ValueError, match="positive"):
        experiment.capped_size(*source)


def test_real_4k_video_cap_preserves_count_order_and_burned_identity(tmp_path):
    checks = experiment.verify_identity(tmp_path)
    assert len(checks) == 2 * len(experiment.IDENTITY_IDS)
    assert all(row["actual"] == row["expected"] for row in checks)
    with Image.open(tmp_path / "identity_capped" / "frame0.jpg") as image:
        assert image.size == (1920, 1080)
    with Image.open(tmp_path / "identity_original" / "frame0.jpg") as image:
        assert image.size == (3840, 2160)
