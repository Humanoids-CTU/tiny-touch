"""Headless checks for `LabelingApp._display_pump`.

The buffering thread no longer calls into Tk (SMOOTHNESS_PLAN.md step 2);
the Tk thread polls the buffer instead. The pump must paint a frame that
finished decoding after the user moved to it, repaint when the buffer was
rebuilt at a new size, and otherwise leave the screen alone.
"""

from contextlib import nullcontext
from types import MethodType, SimpleNamespace

import pytest
from PIL import Image

import labeling_app
from labeling_app import LabelingApp


class FakeBuffer:
    def __init__(self):
        self.frames = {}

    def get(self, frame):
        return self.frames.get(frame)


class Chip:
    def __init__(self):
        self.shown = []

    def set(self, color, text):
        self.shown.append(text)


@pytest.fixture(autouse=True)
def no_tk_photo(monkeypatch):
    # ImageTk.PhotoImage needs a Tk root; the pump's logic does not.
    monkeypatch.setattr(labeling_app.ImageTk, "PhotoImage", lambda img: ("photo", img.size))


def _pump_app(current_frame=5):
    app = SimpleNamespace(
        video=SimpleNamespace(current_frame=current_frame, total_frames=99),
        frame_buffer=FakeBuffer(),
        perf=SimpleNamespace(time=lambda name: nullcontext()),
        frame_label=SimpleNamespace(configure=lambda **kw: None),
        loading_label=Chip(),
        _suspend_frame_workers=False,
        _displayed_image=None,
        _buffer_status_shown=None,
        _display_pump_id=None,
        displayed_frame=None,
        frame_paint_listeners=[],
        scheduled=[],
    )
    app.after = lambda delay, callback: app.scheduled.append((delay, callback)) or len(app.scheduled)
    app._assert_ui_thread = lambda: None
    for name in ("update_note_entry", "update_frame_counter",
                 "update_limb_parameter_buttons", "update_button_colors"):
        setattr(app, name, lambda: None)
    for name in ("display_first_frame", "_show_buffer_status", "_display_pump"):
        setattr(app, name, MethodType(getattr(LabelingApp, name), app))
    painted = []
    app.frame_paint_listeners.append(lambda frame, size: painted.append((frame, size)))
    return app, painted


def test_a_frame_decoded_after_the_step_is_painted_by_the_pump():
    app, painted = _pump_app(current_frame=5)
    app._display_pump()                       # frame 5 still decoding
    assert painted == []

    app.frame_buffer.frames[5] = Image.new("RGB", (40, 30))   # decode lands
    app._display_pump()

    assert painted == [(5, (40, 30))]


def test_the_pump_does_not_repaint_what_is_already_on_screen():
    app, painted = _pump_app(current_frame=5)
    app.frame_buffer.frames[5] = Image.new("RGB", (40, 30))
    app._display_pump()
    app._display_pump()
    app._display_pump()

    assert len(painted) == 1


def test_a_rebuilt_frame_of_the_same_number_is_repainted():
    # After a resize the buffer holds a NEW image object for the same frame.
    app, painted = _pump_app(current_frame=5)
    app.frame_buffer.frames[5] = Image.new("RGB", (40, 30))
    app._display_pump()
    app.frame_buffer.frames[5] = Image.new("RGB", (80, 60))
    app._display_pump()

    assert painted == [(5, (40, 30)), (5, (80, 60))]


def test_the_status_chip_changes_only_when_the_state_changes():
    app, _ = _pump_app(current_frame=5)
    app._display_pump()
    app._display_pump()
    app.frame_buffer.frames[5] = Image.new("RGB", (40, 30))
    app._display_pump()
    app._display_pump()

    assert app.loading_label.shown == ["Loading", "Loaded"]


def test_the_pump_keeps_running_but_idles_without_a_video():
    app, painted = _pump_app()
    app.video = None
    app._display_pump()

    assert painted == [] and app.loading_label.shown == []
    assert app.scheduled and app.scheduled[-1][1] == app._display_pump
