"""M9 regression tests for close ordering and save-failure decisions."""

from types import SimpleNamespace
from copy import deepcopy

import pytest

import labeling_app
from labeling_app import LabelingApp
from gui.open_touches_dialog import GO_TO_ONSET, SAVE_AND_CLOSE


class _Buffer:
    """Stands in for adapters.frame_buffer.FrameBuffer, which now owns the
    loader pool that on_close tears down."""

    def __init__(self, events):
        self.events = events

    def shutdown(self, *, wait, cancel_futures):
        self.events.append(("shutdown", wait, cancel_futures))


class _Window:
    def __init__(self, width, height, x=0, y=0):
        self.width = width
        self.height = height
        self.x = x
        self.y = y
        self.geometry_value = None

    def update_idletasks(self):
        pass

    def winfo_width(self):
        return self.width

    def winfo_height(self):
        return self.height

    def winfo_rootx(self):
        return self.x

    def winfo_rooty(self):
        return self.y

    def geometry(self, value):
        self.geometry_value = value


def test_close_confirmation_is_centered_over_its_parent():
    root = _Window(width=1200, height=800, x=100, y=50)
    dialog = _Window(width=420, height=180)

    labeling_app.center_over_parent(dialog, root)

    assert dialog.geometry_value == "+490+360"


def test_video_picker_is_owned_by_main_window(monkeypatch):
    monkeypatch.setattr(labeling_app, "choose_video", lambda *args, **kwargs: "new")
    monkeypatch.setattr(labeling_app, "list_projects", lambda: [])
    app = SimpleNamespace(
        ask_labeling_mode=lambda: "Normal",
        ask_template=lambda: "default",
    )
    picker_options = {}
    monkeypatch.setattr(
        labeling_app.filedialog,
        "askopenfilename",
        lambda **kwargs: picker_options.update(kwargs) or "",
    )

    LabelingApp._load_video_flow(app)

    assert picker_options["parent"] is app


def _app(events, save_result=True):
    return SimpleNamespace(
        video=SimpleNamespace(frames={}),
        save_data=lambda: events.append("save") or save_result,
        save_last_position=lambda: events.append("last_position"),
        _finalize_video_time=lambda: events.append("finalize_time"),
        # The working-state SQLite connection must close AFTER every writer
        # (save, last position, labeling-time checkpoint) and BEFORE teardown.
        _close_state_repo=lambda: events.append("close_state_repo"),
        frame_buffer=_Buffer(events),
        # Repeating after() timers must be cancelled before the root is
        # destroyed, or Tcl reports "invalid command name" on every exit.
        _cancel_pending_timers=lambda: events.append("cancel_timers"),
        destroy=lambda: events.append("destroy"),
    )


def test_M9_cancel_has_zero_save_or_teardown_side_effects(monkeypatch):
    events = []
    app = _app(events)
    monkeypatch.setattr(
        labeling_app,
        "custom_confirm_close",
        lambda root: events.append("confirm") or False,
    )

    LabelingApp.on_close(app)

    assert events == ["confirm"]


def test_M9_confirm_saves_before_teardown(monkeypatch):
    events = []
    app = _app(events)
    app._frame_extraction_cancel = SimpleNamespace(
        set=lambda: events.append("cancel_extraction")
    )
    monkeypatch.setattr(
        labeling_app,
        "custom_confirm_close",
        lambda root: events.append("confirm") or True,
    )

    LabelingApp.on_close(app)

    assert events == [
        "confirm",
        "save",
        "last_position",
        "finalize_time",
        "cancel_extraction",
        "close_state_repo",
        ("shutdown", False, True),
        "cancel_timers",
        "destroy",
    ]


def test_M9_rejected_close_anyway_keeps_session_alive(monkeypatch):
    events = []
    app = _app(events, save_result=False)
    monkeypatch.setattr(labeling_app, "custom_confirm_close", lambda root: True)
    monkeypatch.setattr(
        labeling_app.messagebox,
        "askyesno",
        lambda *args, **kwargs: events.append("close_anyway") or False,
    )

    LabelingApp.on_close(app)

    assert events == ["save", "close_anyway"]
    assert app._closing is False


@pytest.mark.parametrize("result", [None, (GO_TO_ONSET, 1), (SAVE_AND_CLOSE, 0)])
def test_close_with_open_touches_offers_navigation_or_save(monkeypatch, result):
    events = []
    app = _app(events)
    app.video = SimpleNamespace(
        frames={2: {"RH": {"Onset": "ON"}}, 9: {"LL": {"Onset": "ON"}}},
        current_frame=4,
    )
    original = deepcopy(app.video.frames)
    app.stop_video = lambda: events.append("stop")
    app._cancel_arrow_hold_state = lambda: None
    app._cancel_wheel_scroll = lambda: None
    app.focus_set = lambda: None
    app.next_frame = lambda delta: events.append(("jump", delta))
    app._channel_display_label = lambda key: key
    app._resolve_open_touches = lambda touches, **kwargs: LabelingApp._resolve_open_touches(app, touches, **kwargs)

    def dialog(parent, touches, channel_label, *, closing=False):
        assert closing is True
        assert [touch.start_frame for touch in touches] == [2, 9]
        return SimpleNamespace(result=result)

    monkeypatch.setattr(labeling_app, "OpenTouchesDialog", dialog)
    monkeypatch.setattr(labeling_app, "custom_confirm_close", lambda root: pytest.fail("Duplicate close prompt"))

    LabelingApp.on_close(app)

    assert app.video.frames == original
    if result is None:
        assert events == ["stop"]
    elif result[0] == GO_TO_ONSET:
        assert events == ["stop", ("jump", 5)]
    else:
        assert events == [
            "stop", "save", "last_position", "finalize_time", "close_state_repo",
            ("shutdown", False, True), "cancel_timers", "destroy",
        ]


def test_close_without_video_uses_normal_confirmation(monkeypatch):
    events = []
    app = _app(events)
    app.video = None
    monkeypatch.setattr(labeling_app, "custom_confirm_close", lambda root: False)
    LabelingApp.on_close(app)
    assert events == []
