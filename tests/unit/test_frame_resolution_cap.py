"""Production extractors must keep frame identity while capping JPEG size."""

import importlib.util
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
import pytest

from adapters import frame_extractor


spec = importlib.util.spec_from_file_location(
    "resolution_marker", Path(__file__).resolve().parents[2] / "demos" / "frame_identity.py")
marker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(marker)


@pytest.fixture(scope="module")
def marked_4k_video(tmp_path_factory):
    path = tmp_path_factory.mktemp("cap_video") / "numbered.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25, (3840, 2160))
    assert writer.isOpened()
    try:
        for index in range(3):
            image = marker.numbered_frame(index).resize((3840, 2160))
            writer.write(cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR))
    finally:
        writer.release()
    return path


@pytest.mark.parametrize("backend", ["ffmpeg", "opencv"])
def test_production_4k_extraction_caps_pixels_without_changing_frames(marked_4k_video, tmp_path, backend):
    frames = tmp_path / "frames"
    frames.mkdir()
    extract = getattr(frame_extractor, f"_extract_frames_{backend}")
    assert extract(str(marked_4k_video), str(frames), None, .01)
    assert sorted(p.name for p in frames.glob("*.jpg")) == [f"frame{i}.jpg" for i in range(3)]
    for index in range(3):
        with Image.open(frames / f"frame{index}.jpg") as image:
            assert image.size == (1920, 1080)
            assert marker.read_marker(image) == index


@pytest.mark.parametrize("source, expected", [
    ((1920, 1080), (1920, 1080)), ((640, 480), (640, 480)),
    ((3840, 2160), (1920, 1080)), ((2160, 3840), (607, 1080)),
    ((3000, 3000), (1080, 1080)), ((4096, 2160), (1920, 1012)),
])
def test_extraction_size_preserves_aspect_without_upscaling(source, expected):
    assert frame_extractor.frame_output_size(*source) == expected


@pytest.mark.parametrize("backend", ["ffmpeg", "opencv"])
def test_production_extraction_does_not_upscale_small_input(tmp_path, backend):
    video = tmp_path / "small.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 25, (640, 360))
    assert writer.isOpened()
    try:
        writer.write(cv2.cvtColor(np.array(marker.numbered_frame(42)), cv2.COLOR_RGB2BGR))
    finally:
        writer.release()
    frames = tmp_path / "frames"
    frames.mkdir()
    assert getattr(frame_extractor, f"_extract_frames_{backend}")(str(video), str(frames), None, .01)
    assert [p.name for p in frames.glob("*.jpg")] == ["frame0.jpg"]
    with Image.open(frames / "frame0.jpg") as image:
        assert image.size == (640, 360)
        assert marker.read_marker(image) == 42


def test_ffmpeg_cap_uses_decoded_size_when_probe_dimensions_are_unknown(marked_4k_video, tmp_path, monkeypatch):
    capture_factory = cv2.VideoCapture

    class UnknownDimensionsCapture:
        def __init__(self, path):
            self.capture = capture_factory(path)

        def get(self, prop):
            if prop in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT):
                return 0
            return self.capture.get(prop)

        def release(self):
            self.capture.release()

    monkeypatch.setattr(frame_extractor.cv2, "VideoCapture", UnknownDimensionsCapture)
    assert frame_extractor._extract_frames_ffmpeg(str(marked_4k_video), str(tmp_path), None, .01)
    with Image.open(tmp_path / "frame0.jpg") as image:
        assert image.size == (1920, 1080)
        assert marker.read_marker(image) == 0
