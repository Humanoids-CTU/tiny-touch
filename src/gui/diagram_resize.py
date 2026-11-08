"""Corner grip that rescales the diagram by dragging, aspect ratio kept.

The grip is a tiny canvas sitting in the gutter just outside the diagram's
bottom-left corner, so it never covers the diagram. It owns only the pointer
handling: it turns a drag into a scale factor and hands that to the
controller, which draws the diagram (`on_preview` during the drag, `on_commit`
on release). Every stored coordinate stays in native diagram pixels, so the
scale is purely a display choice.
"""

import sys
import tkinter as tk
from tkinter import TclError

from gui import theme

GRIP_WIDTH_PX = 10          # fits the gutter left of the diagram frame
GRIP_HEIGHT_PX = 24
GRIP_LINE_SPACING_PX = 5    # distance between the diagonal grip lines
GRIP_LINE_COUNT = 3
GRIP_REST_COLOR_ROLE = "BORDER"   # faint at rest, so the panel stays clean
GRIP_HOVER_COLOR_ROLE = "ACCENT"  # lit while the pointer is over it or dragging
PREVIEW_INTERVAL_MS = 30    # drag motion is coalesced into one preview per interval
MIN_DIAGRAM_SCALE = 0.25
MAX_DIAGRAM_SCALE = 3.0

# Tk names the diagonal resize cursor differently per windowing system.
RESIZE_CURSOR = "size_ne_sw" if sys.platform == "win32" else "bottom_left_corner"


def clamp_scale(scale, upper=MAX_DIAGRAM_SCALE):
    """Keep a diagram scale inside the allowed range (`upper` may tighten the max)."""
    return max(MIN_DIAGRAM_SCALE, min(float(scale), float(upper)))


class _GripCanvas(tk.Canvas):
    """Canvas that repaints its lines whenever the theme reconfigures its colors."""

    def configure(self, cnf=None, **kw):
        result = super().configure(cnf, **kw)
        owner = getattr(self, "_grip", None)
        if owner is not None and (cnf or kw):
            owner._paint()
        return result


class DiagramResizeGrip:
    """Drag handle beside the diagram's bottom-left corner; keeps the aspect ratio.

    `native_size()` returns the template's native (width, height); `get_scale()`
    the current display scale; `max_scale()` the largest scale that still fits
    the screen. `on_preview(scale)` runs during the drag and should be cheap;
    `on_commit(scale)` runs once on release and may do the full redraw.
    """

    def __init__(self, parent, beside, *, native_size, get_scale, max_scale,
                 on_preview, on_commit):
        self._native_size = native_size
        self._get_scale = get_scale
        self._max_scale = max_scale
        self._on_preview = on_preview
        self._on_commit = on_commit
        self._drag = None           # (x_root, y_root, scale) at button press
        self._pending = None        # latest scale not previewed yet
        self._preview_id = None
        self._hover = False
        self.widget = _GripCanvas(
            parent,
            width=GRIP_WIDTH_PX,
            height=GRIP_HEIGHT_PX,
            bd=0,
            highlightthickness=0,
            takefocus=0,
        )
        self.widget._grip = self
        theme.bind_colors(self.widget, bg="SURFACE")
        # Bottom-right corner of the grip meets the bottom-left corner of the
        # diagram frame: it hangs in the gutter and follows the diagram's size.
        self.widget.place(in_=beside, relx=0.0, rely=1.0, anchor="se")
        self.widget.bind("<Enter>", self._on_enter)
        self.widget.bind("<Leave>", self._on_leave)
        self.widget.bind("<ButtonPress-1>", self._on_press)
        self.widget.bind("<B1-Motion>", self._on_motion)
        self.widget.bind("<ButtonRelease-1>", self._on_release)
        self._paint()

    # --- appearance ------------------------------------------------------------
    @property
    def active(self):
        """True while the pointer is over the grip or a drag is in progress."""
        return self._hover or self._drag is not None

    def _paint(self):
        role = GRIP_HOVER_COLOR_ROLE if self.active else GRIP_REST_COLOR_ROLE
        color = getattr(theme, role)
        self.widget.delete("all")
        right, bottom = GRIP_WIDTH_PX - 1, GRIP_HEIGHT_PX - 1
        # Short "/" strokes stacked up the gutter, pointing at the corner.
        for index in range(GRIP_LINE_COUNT):
            y = bottom - index * GRIP_LINE_SPACING_PX
            self.widget.create_line(0, y, right, y - right, fill=color, width=1)

    def _set_cursor(self, name):
        try:
            self.widget.configure(cursor=name)
        except TclError:
            self.widget.configure(cursor="")

    def _on_enter(self, _event):
        self._hover = True
        self._set_cursor(RESIZE_CURSOR)
        self._paint()

    def _on_leave(self, _event):
        self._hover = False
        if self._drag is None:
            self._set_cursor("")
            self._paint()

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
        return clamp_scale(scale0 + delta, self._max_scale())

    def _on_press(self, event):
        self._drag = (event.x_root, event.y_root, float(self._get_scale()))
        self._paint()
        return "break"

    def _on_motion(self, event):
        if self._drag is None:
            return "break"
        self._pending = self._scale_for(event)
        if self._preview_id is None:
            self._preview_id = self.widget.after(PREVIEW_INTERVAL_MS, self._flush_preview)
        return "break"

    def _flush_preview(self):
        self._preview_id = None
        scale, self._pending = self._pending, None
        if scale is not None and self._drag is not None:
            self._on_preview(scale)

    def _on_release(self, event):
        if self._drag is None:
            return "break"
        if self._preview_id is not None:
            self.widget.after_cancel(self._preview_id)
            self._preview_id = None
        self._pending = None
        scale = self._scale_for(event)
        self._drag = None
        if not self._hover:
            self._set_cursor("")
        self._paint()
        self._on_commit(scale)
        return "break"
