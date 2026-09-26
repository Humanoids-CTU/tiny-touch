"""The buffering thread keeps working while the Tk thread is busy.

A worker thread's `Tk.after()` call is a synchronous round-trip: it waits
until the Tk thread is back in its event loop. So a buffering thread that
reports to the GUI that way stalls behind every slow repaint (measured:
~72 ms per call on average in the perf scenario). SMOOTHNESS_PLAN.md step 2:
the buffering thread never calls Tk; the GUI polls the buffer instead.

Needs a real Tk interpreter (the blocking is a property of tkinter's
cross-thread calls), hence the `gui` marker.
"""

import threading
import time
import tkinter as tk

import pytest
from PIL import Image

from adapters.frame_buffer import BufferContext, FrameBuffer

pytestmark = pytest.mark.gui

TOTAL_FRAMES = 400
CURRENT = 300          # nothing is buffered yet: the user just jumped here
UI_BUSY_S = 0.6        # the Tk thread is stuck in one long callback...
SAMPLE_AT_S = 0.3      # ...and halfway through we look at the buffer
MIN_PREFETCHED = 20    # the window is 80 frames; tiny JPEGs decode in ~1 ms


def _make_buffer(root, frames_dir):
    context = BufferContext(
        frames_dir=frames_dir, current_frame=CURRENT, total_frames=TOTAL_FRAMES,
        display_w=100, display_h=100, downscale=1.0,
        jump_frame_count=1, last_step_sign=0,
    )
    # Exactly how LabelingApp wires its thread -> UI boundary.
    return FrameBuffer(
        schedule_on_ui=lambda fn: root.after(0, fn),
        get_buffer_context=lambda: context,
        get_playback_context=lambda: None,
        apply_play_advance=lambda *a: None,
        on_playback_boundary=lambda *a: None,
        on_playback_schedule_error=lambda exc: None,
    )


def test_prefetch_continues_while_the_ui_thread_is_busy(tmp_path):
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    for i in range(TOTAL_FRAMES + 1):
        Image.new("RGB", (8, 6), "red").save(frames_dir / f"frame{i}.jpg")

    root = tk.Tk()
    root.withdraw()
    fb = _make_buffer(root, str(frames_dir))
    worker = threading.Thread(target=fb.background_update, daemon=True)
    observed = {}

    def sample():
        observed["buffered"] = sum(1 for f in range(TOTAL_FRAMES + 1) if f in fb)

    def start_and_block():
        worker.start()
        threading.Timer(SAMPLE_AT_S, sample).start()
        time.sleep(UI_BUSY_S)          # a slow repaint / heavy redraw

    try:
        root.after(0, start_and_block)
        root.after(int((UI_BUSY_S + 0.2) * 1000), root.quit)
        root.mainloop()
    finally:
        fb.shutdown(wait=False, cancel_futures=True)
        worker.join(timeout=5.0)
        root.destroy()

    assert observed["buffered"] >= MIN_PREFETCHED, (
        f"only {observed['buffered']} frame(s) buffered while the UI thread was "
        f"busy — the buffering thread is waiting on Tk"
    )
