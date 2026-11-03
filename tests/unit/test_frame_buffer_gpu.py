"""GPU buffering preserves decoded pixels and leaves final scaling to display."""

from threading import Thread
import time

from PIL import Image, ImageDraw
import pytest

from adapters.frame_buffer import BufferContext, FrameBuffer


@pytest.fixture
def frames(tmp_path):
    image = Image.new("RGB", (1920, 1080), "blue")
    ImageDraw.Draw(image).rectangle((0, 0, 959, 1079), fill="red")
    for index in range(3):
        image.save(tmp_path / f"frame{index}.jpg", quality=90)
    return str(tmp_path)


def assert_pixels(image):
    left = image.getpixel((image.width // 4, image.height // 2))
    right = image.getpixel((image.width * 3 // 4, image.height // 2))
    assert left[0] > 240 and left[1] < 10 and left[2] < 10
    assert right[0] < 10 and right[1] < 10 and right[2] > 240


@pytest.mark.parametrize("route", ["direct", "priority", "prefetch"])
@pytest.mark.parametrize("resize,expected", [(True, (700, 393)), (False, (960, 540))])
def test_final_cpu_size_or_gpu_draft_size_preserves_pixels(frames, route, resize, expected):
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
            assert image.size == (960, 540)
            assert_pixels(image)
    finally:
        buffer.shutdown(wait=True)
        thread.join(timeout=5)
    assert not thread.is_alive()
