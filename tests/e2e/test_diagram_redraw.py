"""The diagram repaints on events, not on a timer.

It used to be rebuilt every 300 ms (`periodic_print_dot`), which is what
quietly moved the dots on frame changes, showed them after a limb switch and
refreshed the timelines after an edit. This test pins each of those events
down through the real GUI, and checks that nothing rebuilds the canvas on its
own any more (items that should outlive one repaint, such as a hover
highlight, would otherwise be wiped).
"""

import pytest

from conftest import ZONE_I_CANVAS_XY
from gui import theme
from gui_driver import click_canvas, goto_frame, pump, select_radio

pytestmark = pytest.mark.gui

DOT_TAG = "dot"


def _dots(app):
    return app.diagram_canvas.find_withtag(DOT_TAG)


def test_dots_follow_frames_limbs_and_edits_without_a_timer(loaded_app):
    app = loaded_app
    select_radio(app, "Left Hand")

    goto_frame(app, 2)
    assert not _dots(app)
    click_canvas(app.diagram_canvas, "<Button-1>", *ZONE_I_CANVAS_XY)
    # The onset frame shows the filled dot plus the open-onset ghost on it.
    assert len(_dots(app)) == 2, "the onset dot should appear at once"
    assert any(
        app.timeline_canvas.type(item) == "rectangle"
        and app.timeline_canvas.itemcget(item, "fill") == theme.TL_ON
        for item in app.timeline_canvas.find_all()
    ), "an edit should show its onset cell in the detail timeline right away"
    assert any(
        app.timeline2_canvas.type(item) == "line"
        and app.timeline2_canvas.itemcget(item, "fill") == theme.TL_ONSET_MARK
        for item in app.timeline2_canvas.find_all()
    ), "an edit should show its onset marker in the overview right away"

    goto_frame(app, 3)
    assert len(_dots(app)) == 1, "the open onset shows as a ghost on later frames"
    goto_frame(app, 5)
    click_canvas(app.diagram_canvas, "<Button-3>", *ZONE_I_CANVAS_XY)
    assert len(_dots(app)) == 1, "the offset dot replaces the ghost"
    goto_frame(app, 6)
    assert not _dots(app), "the touch is closed: no ghost after the offset"

    goto_frame(app, 2)
    assert len(_dots(app)) == 2
    select_radio(app, "Right Hand")
    assert not _dots(app), "another limb has no dots on this frame"
    select_radio(app, "Left Hand")
    assert len(_dots(app)) == 2

    # Nothing rebuilds the diagram while the app sits idle.
    diagram_item = app.diagram_canvas.find_withtag("diagram")
    dot_items = _dots(app)
    pump(app, 0.7)
    assert app.diagram_canvas.find_withtag("diagram") == diagram_item
    assert _dots(app) == dot_items

    click_canvas(app.diagram_canvas, "<Button-2>", *ZONE_I_CANVAS_XY)
    assert not _dots(app), "a deleted dot disappears at once"
