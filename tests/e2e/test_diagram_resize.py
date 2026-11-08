"""Dragging the diagram's corner grip rescales the display, never the data."""
import pytest

from adapters import config
from domain.templates import get_template
from gui import theme
from gui.diagram_resize import RESIZE_CURSOR
from gui_driver import click, click_canvas, find_toplevel, find_widget, pump

from conftest import DIAGRAM_SCALE, ZONE_I_DATA_XY, ZONE_I_NAME


pytestmark = pytest.mark.gui


def _drag_grip(app, dx, dy):
    """Drag the grip by (dx, dy) in 'growth' pixels: positive values enlarge.

    The grip sits at the bottom-left corner, so growing means moving the
    pointer LEFT and down; the horizontal sign is flipped here.
    """
    dx = -dx
    grip = app.diagram_grip.widget
    x0, y0 = 400, 400  # any root position; only the delta matters
    grip.event_generate("<ButtonPress-1>", x=4, y=4, rootx=x0, rooty=y0)
    grip.event_generate("<B1-Motion>", x=4 + dx // 2, y=4 + dy // 2,
                        rootx=x0 + dx // 2, rooty=y0 + dy // 2)
    pump(app, 0.1)  # let the coalesced preview run
    grip.event_generate("<B1-Motion>", x=4 + dx, y=4 + dy, rootx=x0 + dx, rooty=y0 + dy)
    grip.event_generate("<ButtonRelease-1>", x=4 + dx, y=4 + dy, rootx=x0 + dx, rooty=y0 + dy)
    pump(app, 0.1)


def test_grip_drag_rescales_display_keeps_native_coordinates_and_persists(loaded_app):
    app = loaded_app
    base_w, base_h = get_template(app.template).native_size
    assert app.diagram_scale == DIAGRAM_SCALE
    assert int(app.diagram_canvas.cget("width")) == int(base_w * DIAGRAM_SCALE)

    # Hovering the grip shows the affordance: resize cursor and accent lines.
    grip = app.diagram_grip.widget
    grip.event_generate("<Enter>")
    pump(app)
    assert grip.cget("cursor") == RESIZE_CURSOR
    assert all(grip.itemcget(item, "fill") == theme.ACCENT for item in grip.find_all())
    grip.event_generate("<Leave>")
    pump(app)
    assert grip.cget("cursor") == ""
    assert all(grip.itemcget(item, "fill") == theme.BORDER for item in grip.find_all())

    # A drag along the diagonal of 0.2 x the native size grows the scale by 0.2.
    _drag_grip(app, int(base_w * 0.2), int(base_h * 0.2))
    new_scale = app.diagram_scale
    assert new_scale == pytest.approx(DIAGRAM_SCALE + 0.2, abs=0.01)
    assert int(app.diagram_canvas.cget("width")) == int(base_w * new_scale)
    assert int(app.diagram_canvas.cget("height")) == int(base_h * new_scale)
    assert app.diagram_canvas.find_withtag("diagram"), "limb image redrawn at the new size"
    assert app._highlighter is not None and app._highlighter.scale == new_scale

    # Persisted for the next launch, and the in-memory snapshot agrees.
    assert config.load_config()["diagram_scale"] == pytest.approx(new_scale, abs=0.001)
    assert app.config.diagram_scale == pytest.approx(new_scale, abs=0.001)

    # A click at the SAME native point, now at the new display scale, records
    # the same zone: stored coordinates never depend on the display size.
    click_canvas(app.diagram_canvas, "<Button-1>",
                 int(ZONE_I_DATA_XY[0] * new_scale), int(ZONE_I_DATA_XY[1] * new_scale))
    record = app.video.frames[app.video.current_frame]["RH"]
    assert record["Zones"] == [[ZONE_I_NAME]]
    assert abs(record["X"][0] - ZONE_I_DATA_XY[0]) <= 2
    assert abs(record["Y"][0] - ZONE_I_DATA_XY[1]) <= 2

    # Dragging back shrinks it again and the canvas is repainted.
    _drag_grip(app, -int(base_w * 0.3), -int(base_h * 0.3))
    assert app.diagram_scale == pytest.approx(new_scale - 0.3, abs=0.01)
    assert app.diagram_canvas.find_all(), "canvas repainted after shrinking"


def test_settings_no_longer_offers_diagram_scale_and_keeps_dragged_value(loaded_app):
    app = loaded_app
    click(app, "Settings")
    settings = find_toplevel(app, "Settings")
    assert find_widget(settings, text="Diagram scale") is None
    assert find_widget(settings, text="Dot size") is not None

    # A drag while the dialog is open must survive Save.
    base_w, base_h = get_template(app.template).native_size
    _drag_grip(app, int(base_w * 0.1), int(base_h * 0.1))
    dragged = app.diagram_scale
    assert dragged == pytest.approx(DIAGRAM_SCALE + 0.1, abs=0.01)
    click(settings, "Save")  # applies and closes the window
    pump(app, 0.2)
    assert not settings.winfo_exists()
    assert app.diagram_scale == pytest.approx(dragged, abs=0.001)
    assert config.load_config()["diagram_scale"] == pytest.approx(dragged, abs=0.001)
    assert int(app.diagram_canvas.cget("width")) == int(base_w * dragged)


def test_grip_works_before_a_video_is_loaded(app):
    """No video: the neutral startup diagram is redrawn at the new size."""
    base_w, base_h = get_template(app.template).native_size
    assert app.video is None
    _drag_grip(app, int(base_w * 0.2), int(base_h * 0.2))
    assert app.diagram_scale == pytest.approx(DIAGRAM_SCALE + 0.2, abs=0.01)
    assert int(app.diagram_canvas.cget("width")) == int(base_w * app.diagram_scale)
    images = [item for item in app.diagram_canvas.find_all() if app.diagram_canvas.type(item) == "image"]
    assert len(images) == 1, "startup diagram drawn once at the new size"
    assert config.load_config()["diagram_scale"] == pytest.approx(app.diagram_scale, abs=0.001)
