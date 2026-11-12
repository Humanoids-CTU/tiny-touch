"""Headless checks for `LabelingApp.displayed_frame` and the paint listeners.

`displayed_frame` is what is ON SCREEN, not what is buffered: the perf
scenario (tests/e2e/test_perf_scenario.py) times "press -> painted" with it,
so it must only move when `display_first_frame` really shows an image.
"""

from contextlib import nullcontext
from types import MethodType, SimpleNamespace

import pytest
from PIL import Image

import labeling_app
from labeling_app import LabelingApp


class FakeBuffer:
    def __init__(self, frames):
        self.frames = frames

    def get(self, frame):
        return self.frames.get(frame)


class Recorder:
    """Stand-in for any widget: accepts and records every call."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return record


class FakePhoto:
    """Stand-in for ImageTk.PhotoImage (which needs a Tk root)."""

    def __init__(self, img, master=None):
        self.size = img.size

    def paste(self, img):
        self.size = img.size


@pytest.fixture(autouse=True)
def no_tk_photo(monkeypatch):
    # ImageTk.PhotoImage needs a Tk root; the paint bookkeeping does not.
    monkeypatch.setattr(labeling_app.ImageTk, "PhotoImage", FakePhoto)


def _display_app(buffered):
    app = SimpleNamespace(
        video=SimpleNamespace(current_frame=0, total_frames=99),
        frame_buffer=FakeBuffer(buffered),
        perf=SimpleNamespace(time=lambda name: nullcontext()),
        frame_label=Recorder(),
        loading_label=Recorder(),
        displayed_frame=None,
        frame_paint_listeners=[],
        _displayed_image=None,
        _buffer_status_shown=None,
        image=None,
    )
    app._assert_ui_thread = lambda: None
    for name in ("update_note_entry", "update_frame_counter",
                 "update_limb_parameter_buttons", "update_button_colors",
                 "_draw_diagram_dots"):
        setattr(app, name, lambda: None)
    app.display_first_frame = MethodType(LabelingApp.display_first_frame, app)
    app._show_buffer_status = MethodType(LabelingApp._show_buffer_status, app)
    app._show_frame_image = MethodType(LabelingApp._show_frame_image, app)
    app._refresh_frame_controls = MethodType(LabelingApp._refresh_frame_controls, app)
    return app


def test_painting_a_buffered_frame_sets_displayed_frame_and_notifies():
    app = _display_app({5: Image.new("RGB", (40, 30))})
    painted = []
    app.frame_paint_listeners.append(lambda frame, size: painted.append((frame, size)))

    app.display_first_frame(5)

    assert app.displayed_frame == 5
    assert painted == [(5, (40, 30))]


def test_a_missing_frame_leaves_displayed_frame_and_listeners_alone():
    app = _display_app({5: Image.new("RGB", (40, 30))})
    app.display_first_frame(5)
    painted = []
    app.frame_paint_listeners.append(lambda frame, size: painted.append(frame))

    app.display_first_frame(6)  # not buffered: the old image stays on screen

    assert app.displayed_frame == 5
    assert painted == []
