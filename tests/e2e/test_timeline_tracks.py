"""Each timeline shows its static content as ONE image, in a real Tk window."""

import pytest

from conftest import ZONE_I_CANVAS_XY
from gui import theme, timeline
from gui.timeline_raster import rgb
from gui_driver import click_canvas, goto_frame, pump, select_radio

pytestmark = pytest.mark.gui


def shows(canvas, color):
    return bool((timeline.track_pixels(canvas) == rgb(color)).all(axis=-1).any())


def assert_one_track_image(canvas):
    """The track image lies at the bottom, sized like the canvas; nothing but
    the playhead image and note markers lies above it."""
    track, = canvas.find_withtag(timeline.TRACK_TAG)
    assert canvas.find_all()[0] == track
    assert timeline.track_pixels(canvas).shape == (canvas.winfo_height(), canvas.winfo_width(), 3)
    others = [item for item in canvas.find_all() if item != track]
    assert sorted(canvas.type(item) for item in others if "note_marker" not in canvas.gettags(item)) == ["image"]


def test_tracks_survive_edits_resize_and_appearance_changes(loaded_app):
    app = loaded_app
    canvases = (app.timeline_canvas, app.timeline2_canvas)
    select_radio(app, "Left Hand")
    goto_frame(app, 2)
    click_canvas(app.diagram_canvas, "<Button-1>", *ZONE_I_CANVAS_XY)
    pump(app)
    for canvas in canvases:
        assert_one_track_image(canvas)
    assert shows(app.timeline_canvas, theme.TL_ON)

    # A resize repaints both tracks at the new size, content included.
    before = [canvas.winfo_width() for canvas in canvases]
    # Wider, not narrower: the window already sits at its minimum size.
    app.geometry(f"{app.winfo_width() + 240}x{app.winfo_height()}+{app.winfo_x()}+{app.winfo_y()}")
    pump(app, 0.4)
    assert [canvas.winfo_width() for canvas in canvases] != before
    for canvas in canvases:
        assert_one_track_image(canvas)
    assert shows(app.timeline_canvas, theme.TL_ON)

    # A playhead move leaves the track image alone.
    photos = [canvas.itemcget(canvas.find_withtag(timeline.TRACK_TAG)[0], "image") for canvas in canvases]
    goto_frame(app, 4)
    for canvas, photo in zip(canvases, photos):
        assert_one_track_image(canvas)
        assert canvas.itemcget(canvas.find_withtag(timeline.TRACK_TAG)[0], "image") == photo

    # Dark mode repaints the same content in the dark palette.
    light_empty, light_on = theme.TL_EMPTY, theme.TL_ON
    try:
        theme.apply_appearance(app, app.style, "dark")
        assert theme.TL_EMPTY != light_empty
        app._detail_timeline.invalidate()
        app._overview_timeline.invalidate()
        app.draw_timeline()
        app.draw_timeline2()
        pump(app)
        for canvas in canvases:
            assert_one_track_image(canvas)
            assert shows(canvas, theme.TL_EMPTY) and not shows(canvas, light_empty)
        assert shows(app.timeline_canvas, theme.TL_ON)
    finally:
        theme.apply_appearance(app, app.style, "light")
    assert theme.TL_ON == light_on
