"""Playback keeps video frames exact without repainting all controls at 100 Hz."""
from contextlib import nullcontext
from types import MethodType, SimpleNamespace

import pytest

import labeling_app
from labeling_app import LabelingApp


@pytest.fixture
def app(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(labeling_app.time, "perf_counter", lambda: now[0])
    app = SimpleNamespace(
        video=SimpleNamespace(current_frame=0, total_frames=499),
        frame_rate=100, play=False, play_dir=1,
        _hold_play_active=False, _play_tick_id=None, _play_next_due=None,
        _arrow_start_id=None, _arrow_release_id=None, _arrow_held_dir=None,
        _play_ui_next_due=None, _play_ui_pending=False,
        _precise_timers=SimpleNamespace(hold=lambda _: None, release=lambda _: None),
        _selecting_frame=False, _last_step_sign=0,
        perf=SimpleNamespace(time=lambda _: nullcontext()),
        displayed_frame=0, _displayed_image=None, frame_paint_listeners=[],
        now=now, queue=[], painted=[], controls=[], timelines=[], timelines2=[], note="",
        _suspend_frame_workers=False,
        _assert_ui_thread=lambda: None, _show_buffer_status=lambda _: None,
    )
    images = {frame: SimpleNamespace(size=(10, 10)) for frame in range(500)}
    app.frame_buffer = SimpleNamespace(get=images.get)
    app.after = lambda delay, callback: app.queue.append((delay, callback)) or len(app.queue)
    app.after_cancel = lambda _: None
    app._show_frame_image = lambda image: app.painted.append(app.video.current_frame) or image.size
    app.update_note_entry = lambda: setattr(app, "note", f"note {app.video.current_frame}")
    app.update_frame_counter = lambda: app.controls.append(app.video.current_frame)
    app.update_limb_parameter_buttons = lambda: None
    app.update_button_colors = lambda: None
    app._draw_diagram_dots = lambda: None
    app.draw_timeline = lambda: app.timelines.append(app.video.current_frame)
    app.draw_timeline2 = lambda: app.timelines2.append(app.video.current_frame)
    app._play_window_buffered = lambda *_: True
    for name in (
        "_start_playback", "_play_tick", "_end_play_chain", "_frame_interval_s",
        "_apply_play_advance", "_on_playback_boundary", "stop_video",
        "_cancel_arrow_hold_state", "_annotation_frame_ready", "display_first_frame",
        "_refresh_frame_controls", "_refresh_playback_ui", "_flush_playback_ui",
        "_on_arrow_press", "_begin_hold_playback", "next_frame",
        "_request_buffered_step", "_buffered_step_tick", "_display_pump",
    ):
        if hasattr(LabelingApp, name):
            setattr(app, name, MethodType(getattr(LabelingApp, name), app))
    app._next_deadline = LabelingApp._next_deadline
    if hasattr(LabelingApp, "_next_playback_deadline"):
        app._next_playback_deadline = LabelingApp._next_playback_deadline
    return app


def tick(app, late_s=0):
    delay, callback = app.queue.pop(0)
    app.now[0] += delay / 1000 + late_s
    callback()


def test_every_video_frame_is_painted_while_controls_refresh_at_25hz(app):
    app._start_playback(1)
    for _ in range(19):
        tick(app)

    assert app.painted == list(range(1, 21))
    assert app.displayed_frame == app.video.current_frame == 20
    assert len(app.controls) <= 6
    assert app.controls[0] == 1


@pytest.mark.parametrize("stop", ["pause", "arrow_release", "boundary", "annotation"])
def test_stopping_synchronizes_controls_to_the_last_painted_frame(app, stop):
    app._start_playback(1)
    tick(app)
    assert app.controls[-1] == 1
    if stop == "pause":
        app.stop_video()
    elif stop == "arrow_release":
        app._hold_play_active = True
        app._cancel_arrow_hold_state()
    elif stop == "boundary":
        app._on_playback_boundary(app.video.current_frame, 1)
    else:
        assert app._annotation_frame_ready()
    assert app.controls[-1] == app.displayed_frame == 2
    assert app.note == "note 2"
    assert not app.play


def test_stopping_preserves_an_unsaved_note_on_an_already_synchronized_frame(app):
    app._start_playback(1)
    app.note = "unsaved draft"
    app.stop_video()
    assert app.note == "unsaved draft"


def test_exact_navigation_refreshes_controls_during_a_throttled_interval(app):
    app._start_playback(1)
    tick(app)
    app.display_first_frame(100)
    assert app.controls[-1] == app.displayed_frame == 100
    assert app.note == "note 100"


def test_short_callback_delay_is_recovered_without_skipping_a_frame(app):
    app._start_playback(1)
    tick(app, late_s=.023)
    assert app.queue[0][0] == 1
    tick(app)
    assert app.painted == [1, 2, 3]
    assert app.now[0] < 10.040


def test_long_pause_resets_the_clock_instead_of_creating_a_catchup_burst(app):
    app._start_playback(1)
    tick(app, late_s=2)
    assert app.queue[0][0] == 10
    assert app.painted == [1, 2]


def test_direction_change_resets_a_late_playback_clock(app):
    app.video.current_frame = 100
    app._start_playback(1)
    app.now[0] += .040
    app._start_playback(-1)
    tick(app)
    assert app.painted == [101, 100]
    assert app.queue[0][0] == 10


def test_a_buffer_stall_synchronizes_controls_and_resumes_with_a_fresh_clock(app):
    app._start_playback(1)
    tick(app)
    ready = [False]
    app._play_window_buffered = lambda *_: ready[0]
    priorities = []
    app.frame_buffer.request_priority = priorities.append
    tick(app)
    assert priorities == [3]
    assert app.controls[-1] == app.displayed_frame == 2
    for _ in range(20):
        tick(app)
    ready[0] = True
    tick(app)
    assert app.painted == [1, 2, 3]
    assert app.queue[0][0] == 10


def test_explicit_navigation_restarts_a_late_playback_clock(app):
    app._start_playback(1)
    app.now[0] += .050
    app.display_first_frame(100)
    tick(app)
    assert app.painted == [1, 100, 101]
    assert app.queue[0][0] == 10


def test_a_pending_tick_can_resume_with_a_fresh_clock_after_stop(app):
    app._start_playback(1)
    app.stop_video()
    app.now[0] += .100
    app._start_playback(1)
    assert len(app.queue) == 1
    tick(app)
    assert app.painted == [1, 2]
    assert app.queue[0][0] == 10


def test_renderer_repaint_preserves_an_unsaved_note_until_successful_paint(app):
    app.note = "unsaved draft"
    app._get_note_entry_text = lambda: app.note
    app._set_note_entry_text = lambda value: setattr(app, "note", value)
    app._preserve_note_on_paint = (app.video, 0)
    app.display_first_frame()
    assert app.note == "unsaved draft"
    assert app.displayed_frame == 0
    assert app._preserve_note_on_paint is None


def test_renderer_switch_keeps_draft_when_old_frame_id_matches_but_new_image_is_missing(app):
    app.note = "unsaved renderer-switch draft"
    app._get_note_entry_text = lambda: app.note
    app._set_note_entry_text = lambda value: setattr(app, "note", value)
    app.displayed_frame = app.video.current_frame = 0
    app._displayed_image = None
    app._preserve_note_on_paint = (app.video, 0)
    images = {}
    app.frame_buffer.get = images.get

    app.display_first_frame()
    assert app.note == "unsaved renderer-switch draft"

    images[0] = SimpleNamespace(size=(10, 10))
    app.display_first_frame()
    assert app.note == "unsaved renderer-switch draft"
    assert app._preserve_note_on_paint is None


def test_annotation_is_rejected_when_the_requested_frame_was_not_painted(app):
    app._start_playback(1)
    app.video.current_frame = 20
    assert not app._annotation_frame_ready()
    assert app.displayed_frame == 1


def test_failed_paint_does_not_advance_displayed_frame_or_notify(app):
    app._start_playback(1)
    def fail(_):
        raise RuntimeError("renderer failure")
    app._show_frame_image = fail
    with pytest.raises(RuntimeError, match="renderer failure"):
        tick(app)
    assert app.displayed_frame == 1


@pytest.mark.parametrize("action", ["stop", "annotation"])
def test_stopping_during_arrow_grace_cancels_start_and_repeat_cannot_rearm(app, action):
    app.realtime_arrow_hold = True
    app._request_buffered_step = lambda delta, **_: app.display_first_frame(app.video.current_frame + delta)
    app._on_arrow_press(1)
    assert app._arrow_start_id is not None
    canceled = []
    app.after_cancel = canceled.append
    if action == "stop":
        app.stop_video()
    else:
        assert app._annotation_frame_ready()
    assert canceled
    assert app._arrow_start_id is None
    app._on_arrow_press(1)
    assert app._arrow_start_id is None
    assert app.video.current_frame == 1


def test_stop_from_paint_listener_synchronizes_newly_displayed_frame(app):
    app._start_playback(1)
    app.frame_paint_listeners.append(lambda *_: app.stop_video())
    tick(app)
    assert app.controls[-1] == app.displayed_frame == 2
    assert not app.play


def test_stop_cancels_an_initial_arrow_step_that_is_still_waiting_for_decode(app):
    class Buffer:
        def __init__(self):
            self.images = {0: SimpleNamespace(size=(10, 10))}

        def __contains__(self, frame):
            return frame in self.images

        def get(self, frame):
            return self.images.get(frame)

        def request_priority(self, frame):
            pass

    app.frame_buffer = Buffer()
    app.realtime_arrow_hold = True
    app._on_arrow_press(1)
    assert app.video.current_frame == 0
    app.stop_video()
    app.note = "draft typed after stopping"
    app.frame_buffer.images[1] = SimpleNamespace(size=(10, 10))
    app._buffered_step_tick()
    assert app.video.current_frame == app.displayed_frame == 0
    assert app.note == "draft typed after stopping"


def test_async_video_repaint_keeps_both_timeline_cursors_synchronized_on_stop(app):
    app._start_playback(1)
    tick(app)
    assert app.displayed_frame == 2
    assert app.timelines[-1] == app.timelines2[-1] == 1
    # A resize or renderer fallback replaces the image for the same frame.
    app._displayed_image = None
    app._display_pump()
    app.stop_video()
    assert app.controls[-1] == app.displayed_frame == 2
    assert app.timelines[-1] == app.timelines2[-1] == 2
