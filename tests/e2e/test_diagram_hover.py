"""Hovering the diagram highlights the zone under the pointer and names it.

The highlight lives in canvas items of its own (`hover`, `hover-tip`): it must
never disturb the `diagram` and `dot` items, and its animation timer must be
gone as soon as nothing moves, so an idle or steadily hovered diagram costs
nothing during playback.
"""

import pytest

from conftest import ZONE_I_CANVAS_XY, ZONE_I_NAME
from gui_driver import click_canvas, goto_frame, pending_timers, pump, select_radio

pytestmark = pytest.mark.gui

HOVER_TAG = "hover"
TIP_TAG = "hover-tip"
TICK_NAME = "_hover_tick"


def _hover_timers(app):
    return [entry for entry in pending_timers(app) if TICK_NAME in entry[1]]


def _tooltip_text(canvas):
    items = [item for item in canvas.find_withtag(TIP_TAG) if canvas.type(item) == "text"]
    if not items or canvas.itemcget(items[0], "state") == "hidden":
        return None
    return canvas.itemcget(items[0], "text")


def _move(canvas, x, y):
    canvas.event_generate("<Motion>", when="now", x=x, y=y)


def test_hover_highlights_and_names_the_zone_then_fades_out(loaded_app):
    app = loaded_app
    canvas = app.diagram_canvas
    diagram_item = canvas.find_withtag("diagram")

    _move(canvas, *ZONE_I_CANVAS_XY)
    pump(app, 0.3)
    assert len(canvas.find_withtag(HOVER_TAG)) == 1, "the hovered zone gets one overlay"
    assert _tooltip_text(canvas) == ZONE_I_NAME
    assert not _hover_timers(app), "a steady hover must not keep a timer alive"

    canvas.event_generate("<Leave>", when="now")
    pump(app, 0.8)
    assert not canvas.find_withtag(HOVER_TAG), "the overlay fades out after the pointer leaves"
    assert _tooltip_text(canvas) is None
    assert not _hover_timers(app)
    assert canvas.find_withtag("diagram") == diagram_item, "the diagram image is never rebuilt"


def test_hover_survives_frame_changes_and_clicks_leave_dots_alone(loaded_app):
    app = loaded_app
    canvas = app.diagram_canvas
    select_radio(app, "Left Hand")
    goto_frame(app, 2)

    _move(canvas, *ZONE_I_CANVAS_XY)
    pump(app, 0.3)
    overlay = canvas.find_withtag(HOVER_TAG)
    goto_frame(app, 3)  # a dots-only repaint
    assert canvas.find_withtag(HOVER_TAG) == overlay, "frame changes keep the overlay"

    click_canvas(canvas, "<Button-1>", *ZONE_I_CANVAS_XY)
    assert len(canvas.find_withtag("dot")) == 2, "the click still records normally"
    pump(app, 0.8)
    assert canvas.find_withtag(HOVER_TAG) == overlay, "the click flash reuses the overlay"
    assert not _hover_timers(app), "the flash must settle and release its timer"

    select_radio(app, "Right Hand")  # a full repaint drops every canvas item
    assert not canvas.find_withtag(HOVER_TAG)
    _move(canvas, ZONE_I_CANVAS_XY[0] + 1, ZONE_I_CANVAS_XY[1])
    pump(app, 0.3)
    assert canvas.find_withtag(HOVER_TAG), "the next motion recreates it"


def test_hover_effects_can_be_switched_off(loaded_app):
    app = loaded_app
    canvas = app.diagram_canvas
    _move(canvas, *ZONE_I_CANVAS_XY)
    pump(app, 0.3)
    assert canvas.find_withtag(HOVER_TAG)

    app._highlighter.set_enabled(False)
    pump(app, 0.8)
    assert not canvas.find_withtag(HOVER_TAG)
    assert _tooltip_text(canvas) is None
    _move(canvas, ZONE_I_CANVAS_XY[0] + 1, ZONE_I_CANVAS_XY[1])
    pump(app, 0.3)
    assert not canvas.find_withtag(HOVER_TAG)
    assert not _hover_timers(app)
