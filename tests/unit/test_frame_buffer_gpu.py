"""GPU buffering decodes with OpenCV, shrinks to the display, never enlarges, and stores BGRX frames."""

from threading import Thread
import time

import numpy as np
from PIL import Image, ImageDraw
import pytest

from adapters import frame_buffer
from adapters.frame_buffer import (
    BufferContext, FrameBuffer, GPU_FRAME_MODE, GpuFrame, decode_for_gpu, jpeg_size, pack_for_gpu,
)


@pytest.fixture
def frames(tmp_path):
    image = Image.new("RGB", (1920, 1080), "blue")
    ImageDraw.Draw(image).rectangle((0, 0, 959, 1079), fill="red")
    for index in range(3):
        image.save(tmp_path / f"frame{index}.jpg", quality=90)
    return str(tmp_path)


def assert_pixels(image):
    if isinstance(image, GpuFrame):   # GPU buffer frames are B, G, R, X arrays
        image = image.to_image()
    left = image.getpixel((image.width // 4, image.height // 2))
    right = image.getpixel((image.width * 3 // 4, image.height // 2))
    assert left[0] > 240 and left[1] < 10 and left[2] < 10
    assert right[0] < 10 and right[1] < 10 and right[2] > 240


@pytest.mark.parametrize("route", ["direct", "priority", "prefetch"])
@pytest.mark.parametrize("resize,expected", [(True, (700, 393)), (False, (700, 393))])
def test_cpu_and_gpu_shrink_to_display_and_preserve_pixels(frames, route, resize, expected):
    buffer = FrameBuffer(get_buffer_context=lambda: None)
    try:
        args = (0, frames, 700, 400, 1.0, buffer._gen)
        if route == "direct":
            buffer._load_frame_to_buffer(*args, resize_in_worker=resize)
        elif route == "priority":
            buffer._load_priority(*args, resize_in_worker=resize)
        else:
            buffer._maybe_submit_load(0, 2, frames, 700, 400, 1.0, buffer._gen,
                                      resize_in_worker=resize)
            # Waiting for the pool makes this deterministic without polling.
            buffer._loader_pool.shutdown(wait=True)
        image = buffer.get(0)
        assert image is not None
        assert image.size == expected
        assert_pixels(image)
    finally:
        buffer.shutdown(wait=True)


def test_eight_positional_context_and_decode_default_remain_cpu_compatible(frames):
    context = BufferContext(frames, 0, 2, 700, 400, 1.0, 1, 0)
    assert context.resize_in_worker is True
    buffer = FrameBuffer(get_buffer_context=lambda: context)
    try:
        buffer._load_frame_to_buffer(0, frames, 700, 400, 1.0, buffer._gen)
        assert buffer.get(0).size == (700, 393)
        assert_pixels(buffer.get(0))
    finally:
        buffer.shutdown(wait=True)


def test_background_context_applies_gpu_mode_to_current_hint_and_prefetch(frames):
    context = BufferContext(frames, 0, 2, 700, 400, 1.0, 1, 0,
                            resize_in_worker=False)
    buffer = FrameBuffer(get_buffer_context=lambda: context)
    buffer.request_priority(2)
    thread = Thread(target=buffer.background_update)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and any(buffer.get(i) is None for i in range(3)):
            time.sleep(.005)
        for index in range(3):
            image = buffer.get(index)
            assert image is not None
            assert image.size == (700, 393)
            assert isinstance(image, GpuFrame) and image.mode == GPU_FRAME_MODE
            assert_pixels(image)
    finally:
        buffer.shutdown(wait=True)
        thread.join(timeout=5)
    assert not thread.is_alive()


def test_gpu_never_enlarges_but_cpu_does(frames):
    """A panel larger than the frame: the GPU scales up, so its buffer keeps source pixels."""
    buffer = FrameBuffer(get_buffer_context=lambda: None)
    try:
        buffer._load_frame_to_buffer(0, frames, 3840, 2160, 1.0, buffer._gen, resize_in_worker=False)
        buffer._load_frame_to_buffer(1, frames, 3840, 2160, 1.0, buffer._gen, resize_in_worker=True)
        assert buffer.get(0).size == (1920, 1080)
        assert buffer.get(1).size == (3840, 2160)
    finally:
        buffer.shutdown(wait=True)


def test_gpu_frames_hold_bgrx_pixels_and_convert_back_to_rgb(frames):
    buffer = FrameBuffer(get_buffer_context=lambda: None)
    try:
        buffer._load_frame_to_buffer(0, frames, 700, 400, 1.0, buffer._gen, resize_in_worker=False)
        frame = buffer.get(0)
        assert isinstance(frame, GpuFrame)
        assert frame.pixels.shape == (393, 700, 4) and frame.pixels.dtype == np.uint8
        assert frame.pixels.flags["C_CONTIGUOUS"]
        assert (frame.width, frame.height) == frame.size == (700, 393)
        blue, green, red, _ = frame.pixels[196, 175]      # the left half is red
        assert red > 240 and green < 10 and blue < 10
        # The CPU fallback can always get plain RGB back, as its own copy.
        image = frame.to_image()
        assert image.mode == "RGB" and image.size == frame.size
        assert_pixels(image)
        frame.pixels[:] = 0
        assert_pixels(image)
    finally:
        buffer.shutdown(wait=True)


def test_pack_for_gpu_keeps_pixels_in_bgrx_order():
    source = Image.new("RGB", (5, 3), (10, 20, 30))
    packed = pack_for_gpu(source)
    assert isinstance(packed, GpuFrame) and packed.size == (5, 3)
    assert packed.pixels.shape == (3, 5, 4)
    assert tuple(packed.pixels[2, 4, :3]) == (30, 20, 10)
    assert packed.to_image().getpixel((4, 2)) == (10, 20, 30)


def test_jpeg_size_reads_the_frame_header(frames, tmp_path):
    data = np.fromfile(f"{frames}/frame0.jpg", np.uint8)
    assert jpeg_size(data) == (1920, 1080)
    assert jpeg_size(np.zeros(64, np.uint8)) is None
    assert jpeg_size(data[:4]) is None


@pytest.mark.parametrize("display,expected", [
    ((700, 400), (700, 393)),      # 1/2 decode (960x540), then shrunk
    ((960, 540), (960, 540)),      # 1/2 decode lands on the target
    ((200, 120), (200, 112)),      # 1/8 decode (240x135), then shrunk
    ((1300, 800), (1300, 731)),    # full decode, then shrunk
])
def test_gpu_decode_uses_reduced_jpeg_scales_and_keeps_pixels(frames, display, expected):
    frame = decode_for_gpu(f"{frames}/frame0.jpg", *display, 1.0)
    assert frame.size == expected
    assert_pixels(frame)


def test_gpu_decode_can_leave_the_shrink_to_the_gpu(frames, monkeypatch):
    monkeypatch.setattr(frame_buffer, "GPU_SHRINK_IN_WORKER", False)
    assert decode_for_gpu(f"{frames}/frame0.jpg", 1300, 800, 1.0).size == (1920, 1080)
    # A reduced decode that still covers the target is kept.
    assert decode_for_gpu(f"{frames}/frame0.jpg", 700, 400, 1.0).size == (960, 540)


def test_a_file_opencv_cannot_decode_falls_back_to_pillow(frames, monkeypatch):
    monkeypatch.setattr(frame_buffer, "decode_for_gpu", lambda *args: None)
    buffer = FrameBuffer(get_buffer_context=lambda: None)
    try:
        buffer._load_frame_to_buffer(0, frames, 700, 400, 1.0, buffer._gen, resize_in_worker=False)
        frame = buffer.get(0)
        assert isinstance(frame, GpuFrame) and frame.size == (700, 393)
        assert_pixels(frame)
    finally:
        buffer.shutdown(wait=True)


def test_gpu_decode_reads_a_non_ascii_path(tmp_path):
    folder = tmp_path / "vidéo_žluťoučký"
    folder.mkdir()
    Image.new("RGB", (64, 48), (200, 30, 40)).save(folder / "frame0.jpg", quality=95)
    frame = decode_for_gpu(str(folder / "frame0.jpg"), 640, 480, 1.0)
    assert frame.size == (64, 48)
    red, green, blue = frame.to_image().getpixel((32, 24))
    assert red > 190 and green < 45 and blue < 55
