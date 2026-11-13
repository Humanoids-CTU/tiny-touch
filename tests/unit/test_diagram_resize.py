"""Diagram resize grip: the drag shows a floating preview, the layout changes once on release.

Nothing shows on screen: the root sits off-screen at alpha 0, the floating
window and the screen copy are replaced by fakes that record what would be
shown, and ``content_swap.swap_content`` is recorded instead of covering.
"""
import tkinter as tk
from types import SimpleNamespace

import pytest
from PIL import Image

from gui import content_swap, diagram_resize, floating_image, theme, widgets
from gui.diagram_resize import DiagramCanvas, DiagramResizeGrip

NATIVE = (450, 696)
START_SCALE = 0.6
CARD_X, CARD_Y = 400, 10


@pytest.fixture(scope="module")
def root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    root.geometry("1200x900+6000+6000")
    root.attributes("-alpha", 0.0)
    theme.init_style(root, "light")
    root.update()
    yield root
    root.destroy()


class FakeFloating:
    """Records what FloatingImage would show."""

    def __init__(self, window):
        self.shown = []
        self.closed = False
        FakeFloating.last = self

    def show(self, image, x, y, opacity=1.0):
        self.shown.append((image.copy(), x, y))

    def close(self):
        self.closed = True


@pytest.fixture
def grip_setup(root, monkeypatch):
    card = widgets.RoundedCard(root, fill="DIAGRAM", shadow="card", pad=theme.px(4))
    card.place(x=CARD_X, y=CARD_Y)
    w, h = (int(v * START_SCALE) for v in NATIVE)
    canvas = DiagramCanvas(card.inner, width=w, height=h, bd=0, highlightthickness=0)
    canvas.pack()
    state = SimpleNamespace(scale=START_SCALE, previews=[], commits=[], swaps=[])

    def on_commit(scale):
        state.commits.append(scale)
        state.scale = scale
        canvas.configure(width=int(NATIVE[0] * scale), height=int(NATIVE[1] * scale))

    grip = DiagramResizeGrip(
        canvas, native_size=lambda: NATIVE, get_scale=lambda: state.scale, max_scale=lambda: 1.2,
        on_preview=state.previews.append, on_commit=on_commit, card=card)
    monkeypatch.setattr(floating_image, "available", lambda: True)
    monkeypatch.setattr(floating_image, "grab", lambda widget: Image.new(
        "RGB", (widget.winfo_width(), widget.winfo_height()), (10, 200, 30)))
    monkeypatch.setattr(floating_image, "FloatingImage", FakeFloating)

    def swap(widget, build, **kwargs):
        state.swaps.append(kwargs)
        return build()
    monkeypatch.setattr(content_swap, "swap_content", swap)
    root.update()
    yield SimpleNamespace(grip=grip, canvas=canvas, card=card, state=state)
    card.destroy()


def _drag(setup, dx):
    """Press on the grip, move ``dx`` px left/down (positive grows), flush one preview."""
    grip, canvas = setup.grip, setup.canvas
    x, y = grip._origin()
    press = SimpleNamespace(x=x + 2, y=y + 2, x_root=1000, y_root=1000)
    assert grip.handle_press(press)
    move = SimpleNamespace(x=0, y=0, x_root=1000 - dx, y_root=1000 + dx)
    grip._on_motion(move)
    canvas.after_cancel(grip._preview_id)
    grip._flush_preview()
    return move


def _card_box(card):
    return card.winfo_rootx(), card.winfo_rooty(), card.winfo_width(), card.winfo_height()


@pytest.mark.parametrize("dx", [150, -120], ids=["grow", "shrink"])
def test_drag_moves_only_a_floating_preview_anchored_at_the_cards_top_right(grip_setup, dx):
    s = grip_setup
    old_canvas = (s.canvas.winfo_width(), s.canvas.winfo_height())
    x0, y0, w0, h0 = _card_box(s.card)
    _drag(s, dx)
    s.card.update_idletasks()
    assert s.state.previews == [], "the real canvas is not redrawn during the drag"
    assert (s.canvas.winfo_width(), s.canvas.winfo_height()) == old_canvas
    image, x, y = FakeFloating.last.shown[-1]
    scale = s.grip._scale_for(SimpleNamespace(x_root=1000 - dx, y_root=1000 + dx))
    new_w, new_h = s.grip._display_size(scale)
    pad_w, pad_h = w0 - old_canvas[0], h0 - old_canvas[1]
    assert image.size == (max(new_w + pad_w, w0), max(new_h + pad_h, h0))
    assert (x + image.width, y) == (x0 + w0, y0), "the card's top-right corner stays put"
    assert s.canvas.itemcget(diagram_resize.GRIP_TAG, "state") == "hidden"


def test_grown_preview_fades_out_over_the_video_without_a_hard_edge(grip_setup):
    s = grip_setup
    _drag(s, 150)
    image, _, _ = FakeFloating.last.shown[-1]
    alpha = image.getchannel("A")
    assert alpha.getpixel((0, image.height - 1)) == 0, "outside the card: transparent, not window-coloured"
    assert alpha.getpixel((image.width // 2, image.height // 2)) == 255, "the diagram itself is opaque"


def test_shrunk_preview_covers_the_old_card(grip_setup):
    s = grip_setup
    _, _, w0, h0 = _card_box(s.card)
    _drag(s, -120)
    image, _, _ = FakeFloating.last.shown[-1]
    alpha = image.getchannel("A")
    assert image.size == (w0, h0)
    assert min(alpha.getpixel((0, 0)), alpha.getpixel((0, h0 - 1))) == 255, "the old card never shows beside it"


def test_release_commits_once_behind_a_screen_copy_and_drops_the_preview(grip_setup):
    s = grip_setup
    move = _drag(s, 150)
    floating = FakeFloating.last
    s.grip._on_release(move)
    assert s.state.swaps == [{"from_screen": True}]
    assert len(s.state.commits) == 1 and s.state.commits[0] > START_SCALE
    assert floating.closed
    assert s.grip._preview is None
    assert s.canvas.itemcget(diagram_resize.GRIP_TAG, "state") != "hidden"


def test_without_a_floating_window_the_canvas_is_redrawn_in_place(grip_setup, monkeypatch):
    s = grip_setup
    monkeypatch.setattr(floating_image, "available", lambda: False)
    move = _drag(s, 150)
    assert len(s.state.previews) == 1
    s.grip._on_release(move)
    assert s.state.swaps == [] and len(s.state.commits) == 1


def test_rounded_card_render_is_transparent_outside_and_filled_inside(root):
    card = widgets.RoundedCard(root, fill="DIAGRAM", shadow="card")
    try:
        image = card.render(200, 300)
        assert image.mode == "RGBA" and image.size == (200, 300)
        assert image.getpixel((0, 0))[3] == 0
        fill = Image.new("RGB", (1, 1), theme.color("DIAGRAM")).getpixel((0, 0))
        assert image.getpixel((100, 150)) == (*fill, 255)
    finally:
        card.destroy()
