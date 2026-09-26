"""The priority path (current frame / jump target) never decodes a frame twice.

The buffering thread loads the frame the user is looking at synchronously,
ahead of the pool's FIFO queue. When that frame is ALREADY in the pool —
queued behind other prefetches, or being decoded right now — the priority
path must reuse that work instead of decoding the same JPEG a second time
(SMOOTHNESS_PLAN.md step 1):

  * queued  -> cancel the pool job and decode on the buffering thread
  * running -> wait for the pool job, which finishes sooner than a new decode
"""

import os
import threading
import time
from collections import Counter

import pytest
from PIL import Image

from adapters import frame_buffer
from adapters.frame_buffer import BufferContext, FrameBuffer

TOTAL_FRAMES = 20
TARGET = 10


@pytest.fixture
def frames_dir(tmp_path):
    directory = tmp_path / "frames"
    directory.mkdir()
    for i in range(TOTAL_FRAMES + 1):
        Image.new("RGB", (8, 6), "red").save(directory / f"frame{i}.jpg")
    return str(directory)


@pytest.fixture
def decodes(monkeypatch):
    """Counts Image.open calls per frame number inside the frame buffer.

    `decodes.hold(n)` makes the FIRST decode of frame n block until
    `decodes.release()` — a way to keep a pool decode "running".
    """
    real_open = frame_buffer.Image.open

    class Decodes(Counter):
        held = None
        started = threading.Event()
        gate = threading.Event()

        def hold(self, frame):
            self.held = frame

        def release(self):
            self.gate.set()

    counts = Decodes()

    def counting_open(path, *args, **kwargs):
        name = os.path.basename(str(path))
        frame = int(name[len("frame"):-len(".jpg")])
        counts[frame] += 1
        if frame == counts.held and counts[frame] == 1:
            counts.started.set()
            counts.gate.wait(timeout=5.0)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(frame_buffer.Image, "open", counting_open)
    return counts


def _make_buffer(context):
    return FrameBuffer(
        get_buffer_context=lambda: context["ctx"],
    )


def _context(frames_dir, current_frame):
    return BufferContext(
        frames_dir=frames_dir, current_frame=current_frame,
        total_frames=TOTAL_FRAMES, display_w=100, display_h=100, downscale=1.0,
        jump_frame_count=1, last_step_sign=0,
    )


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def _submit(fb, frame, frames_dir):
    fb._maybe_submit_load(frame, TOTAL_FRAMES, frames_dir, 100, 100, 1.0, fb._gen)


def _run_until_buffered(fb, frame):
    thread = threading.Thread(target=fb.background_update, daemon=True)
    thread.start()
    assert _wait_for(lambda: frame in fb), f"frame {frame} never reached the buffer"
    return thread


def _drain_and_stop(fb, thread):
    """Stop the buffering loop, then let every queued pool job run to the end,
    so a job that SHOULD have been cancelled gets its chance to decode."""
    fb._stopped.set()
    fb.poke()
    thread.join(timeout=5.0)
    fb._loader_pool.shutdown(wait=True, cancel_futures=False)


def test_a_queued_pool_decode_is_not_repeated_by_the_priority_load(frames_dir, decodes):
    context = {"ctx": None}
    fb = _make_buffer(context)
    release = threading.Event()
    for _ in range(fb._loader_pool._max_workers):   # keep every worker busy
        fb._loader_pool.submit(release.wait)
    _submit(fb, TARGET, frames_dir)                   # -> QUEUED behind them

    context["ctx"] = _context(frames_dir, TARGET)    # the user lands on it
    thread = _run_until_buffered(fb, TARGET)
    release.set()
    _drain_and_stop(fb, thread)

    assert decodes[TARGET] == 1


def test_a_running_pool_decode_is_awaited_not_repeated(frames_dir, decodes):
    context = {"ctx": None}
    fb = _make_buffer(context)
    decodes.hold(TARGET)
    _submit(fb, TARGET, frames_dir)
    assert decodes.started.wait(timeout=5.0), "the pool never started the decode"

    context["ctx"] = _context(frames_dir, TARGET)    # the user lands on it
    threading.Timer(0.2, decodes.release).start()   # the pool decode finishes
    thread = _run_until_buffered(fb, TARGET)
    _drain_and_stop(fb, thread)

    assert decodes[TARGET] == 1


def test_a_priority_hint_is_honoured_while_the_pool_is_saturated(frames_dir, decodes):
    context = {"ctx": None}
    fb = _make_buffer(context)
    release = threading.Event()
    for _ in range(fb._loader_pool._max_workers):
        fb._loader_pool.submit(release.wait)

    context["ctx"] = _context(frames_dir, TARGET)
    fb.request_priority(TARGET + 1)                   # e.g. a `>` step target
    thread = _run_until_buffered(fb, TARGET + 1)     # loaded without the pool
    release.set()
    _drain_and_stop(fb, thread)

    assert decodes[TARGET + 1] == 1
