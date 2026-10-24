"""Resizing the video panel rebuilds the frame buffer once, not per event.

Every rebuild throws away all decoded frames. Tk sends `<Configure>` for
moves and re-layouts that do not change the size, and a window-edge drag
sends dozens of size changes per second; rebuilding on each one cost
276-926 decodes per resize burst in the baseline (SMOOTHNESS_PLAN.md step 5).
"""

from types import MethodType, SimpleNamespace

from labeling_app import LabelingApp


def _resize_app(display=(900, 700)):
    app = SimpleNamespace(
        video=SimpleNamespace(current_frame=10, total_frames=99),
        _display_w=display[0],
        _display_h=display[1],
        _resize_target=display,
        _resize_after_id=None,
        scheduled={},           # after id -> (delay_ms, callback)
        resets=[],              # display size at each buffer reset
        repaints=0,
    )

    def after(delay, callback):
        after_id = len(app.scheduled) + 1
        app.scheduled[after_id] = (delay, callback)
        return after_id

    def after_cancel(after_id):
        app.scheduled.pop(after_id, None)

    def buffer_reset():
        app.resets.append((app._display_w, app._display_h))

    def display_first_frame():
        app.repaints += 1

    app.after = after
    app.after_cancel = after_cancel
    app._buffer_reset = buffer_reset
    app.display_first_frame = display_first_frame
    app.on_resize = MethodType(LabelingApp.on_resize, app)
    app._apply_resize = MethodType(LabelingApp._apply_resize, app)
    return app


def _configure(app, width, height):
    app.on_resize(SimpleNamespace(width=width, height=height))


def _fire_timers(app):
    while app.scheduled:
        after_id = min(app.scheduled)
        _, callback = app.scheduled.pop(after_id)
        callback()


def test_an_event_with_an_unchanged_size_keeps_the_buffer():
    app = _resize_app(display=(900, 700))
    _configure(app, 900, 700)
    _fire_timers(app)

    assert app.resets == []


def test_a_burst_of_resizes_rebuilds_the_buffer_once_at_the_final_size():
    app = _resize_app(display=(900, 700))
    for i in range(1, 21):                       # a window-edge drag
        _configure(app, 900 - 10 * i, 700 - 5 * i)
    _fire_timers(app)

    assert app.resets == [(700, 600)]
    assert (app._display_w, app._display_h) == (700, 600)
    assert app.repaints == 1


def test_a_drag_that_ends_at_the_original_size_keeps_the_buffer():
    app = _resize_app(display=(900, 700))
    _configure(app, 880, 690)
    _configure(app, 900, 700)
    _fire_timers(app)

    assert app.resets == []
