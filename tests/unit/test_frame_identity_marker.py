"""The pixel oracle must survive video-like degradation and reject wrong IDs."""

import importlib.util
import io
from pathlib import Path

from PIL import Image, ImageDraw
import pytest


spec = importlib.util.spec_from_file_location(
    "frame_identity", Path(__file__).resolve().parents[2] / "demos" / "frame_identity.py")
experiment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(experiment)


@pytest.mark.parametrize("index", [0, 1, 49, 50, 100, 159, 255])
def test_reads_burned_identity_after_jpeg_and_display_scaling(index):
    encoded = io.BytesIO()
    experiment.numbered_frame(index).save(encoded, format="JPEG", quality=80)
    encoded.seek(0)
    with Image.open(encoded) as image:
        displayed = image.resize((400, 225), Image.Resampling.BILINEAR)
        assert experiment.read_marker(displayed) == index
        assert experiment.read_marker(displayed) != (index + 1) % 256


def test_rejects_obscured_or_corrupt_marker():
    with pytest.raises(ValueError, match="magic/checksum"):
        experiment.read_marker(Image.new("RGB", (640, 360), "black"))
    image = experiment.numbered_frame(42)
    draw = ImageDraw.Draw(image)
    draw.rectangle((32, 286, 55, 325), fill="white")
    with pytest.raises(ValueError, match="magic/checksum"):
        experiment.read_marker(image)
