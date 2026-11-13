"""Corner grip that rescales the diagram by dragging, aspect ratio kept.

The grip is a small rounded corner bracket drawn *on* the diagram canvas, in
its bottom-left corner, as a transparent image: only the bracket shows, the
diagram stays visible around it. It owns only the pointer handling: it turns
a drag into a scale factor and hands that to the controller, which draws the
diagram (`on_commit` on release). Every stored coordinate stays in native
diagram pixels, so the scale is purely a display choice.

The diagram's width sets the width of the whole right column, so resizing the
real canvas re-lays out the entire window (hundreds of ms per step). During
the drag the window therefore stays as it is and a picture of the diagram card
at the dragged size floats over it (`gui.floating_image`); on release the real
layout changes once, behind a still picture of that preview
(`content_swap.swap_content`), so the screen goes from the preview straight to
the finished layout. Where the floating picture is unavailable (off Windows),
`on_preview` redraws the real canvas during the drag instead.
"""

import logging
import sys
import tkinter as tk
from tkinter import TclError

from PIL import Image, ImageDraw, ImageTk

from gui import content_swap, floating_image, theme

logger = logging.getLogger(__name__)

GRIP_SIZE_PX = 16           # square bracket in the diagram's bottom-left corner
GRIP_INSET_PX = 3           # gap between the bracket and the diagram's corner
GRIP_HIT_SLOP_PX = 4        # extra grab area around the bracket
GRIP_STROKE_PX = 1.5
GRIP_CORNER_RADIUS_PX = 9   # bend of the bracket (follows the card corner)
GRIP_SUPERSAMPLE = 8
GRIP_REST_COLOR_ROLE = "DIAGRAM_LINE"  # faint on the white diagram in both themes
GRIP_HOVER_COLOR_ROLE = "ACCENT"  # lit while the pointer is over it or dragging
GRIP_TAG = "resize_grip"
PREVIEW_INTERVAL_MS = 30    # drag motion is coalesced into one preview per interval
FLOATING_PREVIEW = True     # False: resize the real canvas during the drag (slow relayout)
FLOATING_PREVIEW_INTERVAL_MS = 8   # the floating picture is cheap: follow the pointer closely
MIN_DIAGRAM_SCALE = 0.25
MAX_DIAGRAM_SCALE = 3.0

# Tk names the diagonal resize cursor differently per windowing system.
RESIZE_CURSOR = "size_ne_sw" if sys.platform == "win32" else "bottom_left_corner"


def clamp_scale(scale, upper=MAX_DIAGRAM_SCALE):
    """Keep a diagram scale inside the allowed range (`upper` may tighten the max)."""
    return max(MIN_DIAGRAM_SCALE, min(float(scale), float(upper)))


class DiagramCanvas(tk.Canvas):
    """The diagram canvas: puts overlays (the grip) back after a full clear.

    The controller repaints with ``delete("all")`` in several places; this
    keeps the grip without each of them knowing about it.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._after_clear = []
        self._restore_id = None

    def on_clear(self, callback):
        self._after_clear.append(callback)

    def delete(self, *args):
        super().delete(*args)
        if "all" in args and self._after_clear and self._restore_id is None:
            # After the caller has drawn its new content, so overlays end on top.
            self._restore_id = self.after_idle(self._restore)

    def _restore(self):
        self._restore_id = None
        for callback in self._after_clear:
            callback()


class DiagramResizeGrip:
    """Drag handle in the diagram's bottom-left corner; keeps the aspect ratio.

    `canvas` is the diagram's DiagramCanvas. `native_size()` returns the
    template's native (width, height); `get_scale()` the current display
    scale; `max_scale()` / `min_scale()` the allowed range. `on_preview(scale)`
    runs during the drag and should be cheap; `on_commit(scale)` runs once on
    release and may do the full redraw. The owner routes button-1 presses
    through `handle_press(event)` and skips its own click handling when it
    returns True.
    """

    def __init__(self, canvas, *, native_size, get_scale, max_scale, on_preview, on_commit,
                 min_scale=None, card=None):
        self.canvas = canvas
        self._native_size = native_size
        self._get_scale = get_scale
        self._max_scale = max_scale
        self._min_scale = min_scale
        self._on_preview = on_preview
        self._on_commit = on_commit
        self._card = card           # the RoundedCard around the canvas (floating preview)
        self._preview = None        # _FloatingPreview while dragging, if available
        self._drag = None           # (x_root, y_root, scale) at button press
        self._pending = None        # latest scale not previewed yet
        self._preview_id = None
        self._hover = False
        self._photos = {}
        self._size = theme.px(GRIP_SIZE_PX)
        canvas.on_clear(self._place)
        canvas.bind("<Configure>", lambda _e: self._place(), add="+")
        canvas.bind("<Motion>", self._on_motion_hover, add="+")
        canvas.bind("<Leave>", self._on_leave, add="+")
        canvas.bind("<B1-Motion>", self._on_motion, add="+")
        canvas.bind("<ButtonRelease-1>", self._on_release, add="+")
        self._place()

    # --- appearance ------------------------------------------------------------
    @property
    def active(self):
        """True while the pointer is over the grip or a drag is in progress."""
        return self._hover or self._drag is not None

    def _photo(self):
        role = GRIP_HOVER_COLOR_ROLE if self.active else GRIP_REST_COLOR_ROLE
        color = theme.color(role)
        key = (color, self._size)
        if key not in self._photos:
            self._photos[key] = ImageTk.PhotoImage(self._image(color), master=self.canvas)
        return self._photos[key]

    def _image(self, color):
        """The bracket in ``color`` as an RGBA PIL image, transparent around it."""
        s, n = GRIP_SUPERSAMPLE, self._size
        stroke = max(1.0, GRIP_STROKE_PX * theme.SCALE) * s
        radius = theme.px(GRIP_CORNER_RADIUS_PX) * s
        # An "L" with a rounded bend: the bottom-left corner of one rounded
        # rectangle outline (twice the grip's size), so lines and arc share
        # one stroke and join without a step. Transparent elsewhere.
        big = Image.new("RGBA", (2 * n * s, 2 * n * s), (0, 0, 0, 0))
        ImageDraw.Draw(big).rounded_rectangle(
            [0, 0, 2 * n * s - 1, 2 * n * s - 1], radius=radius, outline=color, width=round(stroke))
        return big.crop((0, n * s, n * s, 2 * n * s)).resize((n, n), Image.Resampling.LANCZOS)

    def _origin(self):
        """Top-left of the grip image in canvas coordinates."""
        inset = theme.px(GRIP_INSET_PX)
        height = int(self.canvas.cget("height"))
        return inset, height - inset - self._size

    def _place(self):
        try:
            self.canvas.delete(GRIP_TAG)
            x, y = self._origin()
            self.canvas.create_image(x, y, image=self._photo(), anchor="nw", tags=GRIP_TAG)
            self.canvas.tag_raise(GRIP_TAG)
        except TclError:
            pass   # canvas destroyed

    def _repaint(self):
        self.canvas.itemconfigure(GRIP_TAG, image=self._photo())

    def hit(self, event):
        x, y = self._origin()
        slop = theme.px(GRIP_HIT_SLOP_PX)
        return x - slop <= event.x <= x + self._size + slop and y - slop <= event.y <= y + self._size + slop

    def _set_cursor(self, name):
        try:
            self.canvas.configure(cursor=name)
        except TclError:
            self.canvas.configure(cursor="")

    def _on_motion_hover(self, event):
        if self._drag is not None:
            return
        hover = self.hit(event)
        if hover != self._hover:
            self._hover = hover
            self._set_cursor(RESIZE_CURSOR if hover else "")
            self._repaint()

    def _on_leave(self, _event):
        if self._hover and self._drag is None:
            self._hover = False
            self._set_cursor("")
            self._repaint()

    # --- dragging --------------------------------------------------------------
    def _scale_for(self, event):
        x0, y0, scale0 = self._drag
        base_w, base_h = self._native_size()
        # Project the drag onto the diagram's diagonal so width and height grow
        # together whichever way the pointer moves. The grip sits at the
        # bottom-left corner, so moving left (and down) enlarges the diagram.
        delta = ((x0 - event.x_root) * base_w + (event.y_root - y0) * base_h) / float(
            base_w * base_w + base_h * base_h
        )
        upper = self._max_scale()
        scale = clamp_scale(scale0 + delta, upper)
        if self._min_scale is not None:
            scale = max(scale, min(self._min_scale(), upper))
        return scale

    def handle_press(self, event):
        """Start a drag when button 1 goes down on the grip (True: event consumed)."""
        if not self.hit(event):
            return False
        self._drag = (event.x_root, event.y_root, float(self._get_scale()))
        self._repaint()
        return True

    def _on_motion(self, event):
        if self._drag is None:
            return
        self._pending = self._scale_for(event)
        if self._preview_id is None:
            floating = self._preview is not None or self._floating_wanted()
            interval = FLOATING_PREVIEW_INTERVAL_MS if floating else PREVIEW_INTERVAL_MS
            self._preview_id = self.canvas.after(interval, self._flush_preview)

    def _floating_wanted(self):
        return FLOATING_PREVIEW and self._card is not None and floating_image.available()

    def _display_size(self, scale):
        base_w, base_h = self._native_size()
        return int(base_w * scale), int(base_h * scale)

    def _flush_preview(self):
        self._preview_id = None
        scale, self._pending = self._pending, None
        if scale is None or self._drag is None:
            return
        if self._preview is None and self._floating_wanted():
            try:
                grip = self._image(theme.color(GRIP_HOVER_COLOR_ROLE))
                self._preview = _FloatingPreview(self.canvas, self._card, grip, self._origin())
            except (OSError, TclError, ValueError):
                logger.debug("floating diagram preview unavailable; resizing in place", exc_info=True)
                self._card = None   # do not retry on every motion
        if self._preview is not None:
            try:
                self._preview.update(*self._display_size(scale))
                return
            except (OSError, TclError, ValueError):
                logger.debug("floating diagram preview failed; resizing in place", exc_info=True)
                self._preview.close()
                self._preview, self._card = None, None
        self._on_preview(scale)

    def _on_release(self, event):
        if self._drag is None:
            return
        if self._preview_id is not None:
            self.canvas.after_cancel(self._preview_id)
            self._preview_id = None
        self._pending = None
        scale = self._scale_for(event)
        self._drag = None
        preview, self._preview = self._preview, None
        if preview is None:
            self._commit(scale, event)
            return
        try:
            preview.update(*self._display_size(scale))   # the released size, not the last coalesced one
        except (OSError, TclError, ValueError):
            logger.debug("floating diagram preview failed on release", exc_info=True)

        def build():
            preview.close()
            self._commit(scale, event)

        # One step from the preview to the finished layout: the cover is a copy
        # of the screen (the preview and the GPU-drawn video included) while
        # the window re-lays out underneath.
        content_swap.swap_content(self.canvas, build, from_screen=True)

    def _commit(self, scale, event):
        self._hover = self.hit(event)
        if not self._hover:
            self._set_cursor("")
        self._on_commit(scale)
        self._place()


class _FloatingPreview:
    """The diagram card at a dragged size, floating over its top-right corner.

    The right column is anchored at its top-right, so that corner of the card
    stays put whatever the scale. The picture covers the old card too (in the
    window colour where the smaller new card does not reach), so the real card
    never shows beside it. The diagram is a snapshot taken at the press,
    scaled (labels and dots included); the grip is redrawn crisp at its corner.
    """

    def __init__(self, canvas, card, grip_image, grip_origin):
        self.canvas, self.card = canvas, card
        canvas.itemconfigure(GRIP_TAG, state="hidden")   # redrawn crisp on the picture
        canvas.update_idletasks()
        try:
            self.diagram = floating_image.grab(canvas)
            self.window = floating_image.FloatingImage(canvas)
        except BaseException:
            canvas.itemconfigure(GRIP_TAG, state="normal")
            raise
        card_x, card_y = card.winfo_rootx(), card.winfo_rooty()
        self.old_w, self.old_h = card.winfo_width(), card.winfo_height()
        self.right, self.top = card_x + self.old_w, card_y
        self.pad_left = canvas.winfo_rootx() - card_x
        self.pad_top = canvas.winfo_rooty() - card_y
        self.pad_right = self.right - canvas.winfo_rootx() - canvas.winfo_width()
        self.pad_bottom = card_y + self.old_h - canvas.winfo_rooty() - canvas.winfo_height()
        self.grip = grip_image
        self.grip_inset = grip_origin[0]
        self.background = theme.color(card.outer)
        
    def update(self, width, height):
        """Show the card with a ``width`` x ``height`` diagram."""
        card_w = width + self.pad_left + self.pad_right
        card_h = height + self.pad_top + self.pad_bottom
        full_w, full_h = max(card_w, self.old_w), max(card_h, self.old_h)
        # Transparent except the old card's area (window colour: the real card
        # must not show beside a smaller preview) and the new card, whose
        # shadow fades out over whatever lies below (the video when growing).
        image = Image.new("RGBA", (full_w, full_h), (0, 0, 0, 0))
        image.paste(self.background, (full_w - self.old_w, 0, full_w, self.old_h))
        image.alpha_composite(self.card.render(card_w, card_h), (full_w - card_w, 0))
        left = full_w - card_w + self.pad_left
        image.paste(self.diagram.resize((width, height), Image.Resampling.BILINEAR), (left, self.pad_top))
        grip_y = self.pad_top + height - self.grip_inset - self.grip.height
        image.paste(self.grip, (left + self.grip_inset, grip_y), self.grip)
        self.window.show(image, self.right - full_w, self.top)

    def close(self):
        self.window.close()
        try:
            self.canvas.itemconfigure(GRIP_TAG, state="normal")
        except TclError:
            pass
