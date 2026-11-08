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


def test_special_zones_window_highlights_names_and_marks_in_green(loaded_app):
    from gui import theme
    from gui_driver import click

    app = loaded_app
    click(app, "Special Zones")
    special = app._special_zones_app
    canvas = special.canvas2
    pump(app, 0.3)  # Tk delivers synthetic pointer events only to a mapped window
    assert canvas.winfo_ismapped()
    assert special.top_level.grab_current() is special.top_level, "the window is modal"
    # Tk drops SYNTHETIC pointer events while a grab is held (real ones pass),
    # so release it for the rest of this test (and let Tk process the release).
    special.top_level.grab_release()
    pump(app, 0.1)
    scale = special.diagram_scale / app.diagram_scale  # its own scale, same native masks
    x, y = int(ZONE_I_CANVAS_XY[0] * scale), int(ZONE_I_CANVAS_XY[1] * scale)

    _move(canvas, x, y)
    pump(app, 0.3)
    assert len(canvas.find_withtag(HOVER_TAG)) == 1
    assert _tooltip_text(canvas) == ZONE_I_NAME
    assert not _hover_timers(app)

    click_canvas(canvas, "<Button-1>", x, y)
    assert len(special.dots) == 1
    dot_id = next(iter(special.dots))
    assert str(canvas.itemcget(dot_id, "image")) == str(theme.dot_sprite(theme.DOT_ONSET, special.dot_radius)), (
        "special zone dots are green"
    )
    pump(app, 0.8)
    assert not _hover_timers(app), "the click flash settles"

    click_canvas(canvas, "<Button-2>", x, y)
    assert not special.dots, "middle-click on the dot still removes it with the overlay underneath"
    special.on_close()
    pump(app, 0.3)
    assert not _hover_timers(app), "closing the window stops its timer"


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


def test_hover_shows_only_user_label(loaded_app):
    from domain.zone_display import ZoneDisplaySettings
    loaded_app.zone_display = ZoneDisplaySettings({ZONE_I_NAME: "Head"})
    _move(loaded_app.diagram_canvas, *ZONE_I_CANVAS_XY)
    pump(loaded_app, 0.3)
    assert _tooltip_text(loaded_app.diagram_canvas) == "Head"
