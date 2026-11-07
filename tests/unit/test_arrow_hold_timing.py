"""Tap/hold behavior with a deterministic Tk-style callback queue."""
from types import MethodType, SimpleNamespace

import pytest

from labeling_app import LabelingApp


@pytest.fixture
def app():
    app = SimpleNamespace(
        video=SimpleNamespace(current_frame=10), realtime_arrow_hold=True,
        _arrow_held_dir=None, _arrow_release_id=None, _arrow_start_id=None,
        _hold_play_active=False, play=False, play_dir=1, frame_rate=100,
        now=0, callbacks={}, serial=0,
    )

    def after(delay, callback):
        app.serial += 1
        app.callbacks[app.serial] = (app.now + delay, callback)
        return app.serial

    def advance(milliseconds):
        end = app.now + milliseconds
        while app.callbacks:
            key = min(app.callbacks, key=lambda key: app.callbacks[key][0])
            due, callback = app.callbacks[key]
            if due > end:
                break
            del app.callbacks[key]
            app.now = due
            callback()
        app.now = end

    def step(direction):
        app.video.current_frame += direction

    def play(direction):
        app.play = True
        app.play_dir = direction
        step(direction)

    app.after = after
    app.after_idle = lambda callback: after(0, callback)
    app.after_cancel = lambda key: app.callbacks.pop(key, None)
    app.advance = advance
    app._request_buffered_step = step
    app._start_playback = play
    for name in ('_on_arrow_press', '_on_arrow_release', '_cancel_arrow_hold_state',
                 '_begin_hold_playback'):
        if hasattr(LabelingApp, name):
            setattr(app, name, MethodType(getattr(LabelingApp, name), app))
    return app


@pytest.mark.parametrize('direction', [-1, 1])
def test_short_tap_moves_exactly_one_frame(app, direction):
    app._on_arrow_press(direction)
    assert app.video.current_frame == 10 + direction
    app.advance(100)
    assert not app.play
    app._on_arrow_release(direction)
    app.advance(1000)
    assert app.video.current_frame == 10 + direction
    assert not app.play


def test_hold_starts_after_150ms_without_keyboard_repeat(app):
    app._on_arrow_press(1)
    app.advance(149)
    assert app.video.current_frame == 11
    assert not app.play
    app.advance(1)
    assert app.play
    assert app.video.current_frame == 12


def test_repeat_pairs_do_not_restart_grace_period_or_add_steps(app):
    app._on_arrow_press(1)
    app.advance(70)
    app._on_arrow_release(1)
    app._on_arrow_press(1)
    app.advance(80)
    assert app.play
    assert app.video.current_frame == 12
    app._on_arrow_release(1)
    app._on_arrow_press(1)
    app.advance(0)
    assert app.play
    assert app.video.current_frame == 12
    app._on_arrow_release(1)
    app.advance(0)
    assert not app.play


def test_reversal_cancels_old_start_and_ignores_old_release(app):
    app._on_arrow_press(1)
    app.advance(100)
    app._on_arrow_press(-1)
    app._on_arrow_release(1)
    app.advance(50)
    assert not app.play
    assert app.video.current_frame == 10
    app.advance(100)
    assert app.play
    assert app.play_dir == -1
    assert app.video.current_frame == 9


def test_focus_loss_or_reload_cancels_pending_start(app):
    app._on_arrow_press(1)
    app._cancel_arrow_hold_state()
    app.advance(1000)
    assert not app.play
    assert app.video.current_frame == 11


def test_disabled_setting_steps_only_on_keypress(app):
    app.realtime_arrow_hold = False
    app._on_arrow_press(1)
    app.advance(1000)
    assert not app.play
    assert app.video.current_frame == 11
    app._on_arrow_press(1)
    assert app.video.current_frame == 12
