"""Stepping between same-size frames reuses the on-screen PhotoImage.

Creating a new `ImageTk.PhotoImage` per frame (and reconfiguring the label)
was the dominant UI-thread cost on big panels; pasting into the image that is
already displayed is ~30 % cheaper (SMOOTHNESS_PLAN.md step 4). The risk of
reuse is showing stale pixels, so every check also compares the pixels on
screen with the buffered frame.
"""

import pytest

from gui_driver import click, pump, wait_until

pytestmark = pytest.mark.gui

PROBE_XY = (2, 2)   # background corner, away from the frame-number text


def _screen_pixel(app):
    """RGB of PROBE_XY in the Tk image the video label currently shows."""
    name = app.frame_label.cget("image")
    return tuple(int(v) for v in app.tk.splitlist(app.tk.call(name, "get", *PROBE_XY)))


def _buffered_pixel(app, frame):
    return app.frame_buffer.get(frame).getpixel(PROBE_XY)[:3]


def _painted(app, frame):
    return app.displayed_frame == frame and app.frame_buffer.get(frame) is not None


def test_same_size_frames_reuse_the_photo_and_show_the_new_pixels(loaded_app):
    app = loaded_app
    wait_until(app, lambda: _painted(app, 0), what="frame 0 painted")
    image_before = app.frame_label.cget("image")
    assert _screen_pixel(app) == _buffered_pixel(app, 0)

    wait_until(app, lambda: 1 in app.frame_buffer, what="frame 1 buffered")
    click(app, ">")
    wait_until(app, lambda: _painted(app, 1), what="frame 1 painted")

    assert app.frame_label.cget("image") == image_before
    assert _screen_pixel(app) == _buffered_pixel(app, 1)
    assert _buffered_pixel(app, 1) != _buffered_pixel(app, 0)   # the probe can tell


def test_a_new_frame_size_gets_a_new_photo(loaded_app):
    app = loaded_app
    wait_until(app, lambda: _painted(app, 0), what="frame 0 painted")
    image_before = app.frame_label.cget("image")
    size_before = app._displayed_image.size

    app.geometry("900x800")
    wait_until(
        app,
        lambda: app._displayed_image is not None and app._displayed_image.size != size_before,
        what="frame repainted at the new panel size",
    )
    pump(app, 0.05)

    assert app.frame_label.cget("image") != image_before
    assert _screen_pixel(app) == _buffered_pixel(app, app.displayed_frame)
