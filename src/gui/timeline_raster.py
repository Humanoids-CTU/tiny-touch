"""Timeline track pictures as pixel arrays: no Tk, no canvas items.

A timeline canvas used to hold one item per cell, tick and separator. Tk
repaints every item under a moved playhead (about 60 us each on Windows), so
a dense track cost several milliseconds per playhead move - most of a 100 FPS
frame. The static content is now painted into one array and shown as a single
opaque image; only the playhead and the note markers remain canvas items.

Coordinates follow the canvas calls these functions replaced: a filled
rectangle covers [x1, x2) x [y1, y2), an outline and a line cover their end
pixels, and positions round to the nearest pixel.
"""
from functools import lru_cache

import numpy as np
from PIL import ImageColor

from gui.video_surface import rounded_corner_mask


@lru_cache(maxsize=256)
def rgb(color):
    """A Tk/CSS colour string as an (r, g, b) tuple."""
    return ImageColor.getrgb(color)[:3]


def _px(value):
    return int(round(value))


class TrackRaster:
    """An RGB picture of one timeline track, `pixels[y, x]` (uint8)."""

    def __init__(self, width, height, background):
        self.width, self.height = max(1, int(width)), max(1, int(height))
        self.pixels = np.empty((self.height, self.width, 3), np.uint8)
        self.pixels[:] = rgb(background)

    def copy(self):
        clone = TrackRaster.__new__(TrackRaster)
        clone.width, clone.height = self.width, self.height
        clone.pixels = self.pixels.copy()
        return clone

    def _span(self, a, b, limit):
        return max(0, min(limit, _px(a))), max(0, min(limit, _px(b)))

    def fill(self, x1, y1, x2, y2, color):
        """A filled rectangle without outline."""
        left, right = self._span(x1, x2, self.width)
        top, bottom = self._span(y1, y2, self.height)
        if right > left and bottom > top:
            self.pixels[top:bottom, left:right] = rgb(color)

    def outline(self, x1, y1, x2, y2, color):
        """A one-pixel rectangle outline through all four corner pixels."""
        left, right = self._span(x1, x2, self.width - 1)
        top, bottom = self._span(y1, y2, self.height - 1)
        value = rgb(color)
        self.pixels[top, left:right + 1] = value
        self.pixels[bottom, left:right + 1] = value
        self.pixels[top:bottom + 1, left] = value
        self.pixels[top:bottom + 1, right] = value

    def vlines(self, xs, top, bottom, color, *, width=1, dash=None):
        """Vertical lines at every x in `xs`, drawn in one array operation.

        `dash` is an (on, off) pixel pattern measured from `top`. A line of
        `width` w covers the w columns ending at its rounded x.
        """
        top, bottom = self._span(top, bottom, self.height)
        if bottom <= top:
            return
        columns = np.rint(np.asarray(list(xs), dtype=float)).astype(int)
        if columns.size == 0:
            return
        if width > 1:
            columns = (columns[:, None] - np.arange(width)[None, :]).ravel()
        columns = np.unique(columns[(columns >= 0) & (columns < self.width)])
        if columns.size == 0:
            return
        rows = np.arange(top, bottom)
        if dash:
            on, off = dash
            rows = rows[(rows - top) % (on + off) < on]
        self.pixels[np.ix_(rows, columns)] = rgb(color)

    def line(self, x1, y1, x2, y2, color):
        """A one-pixel line between two points (any direction)."""
        steps = max(abs(_px(x2) - _px(x1)), abs(_px(y2) - _px(y1))) + 1
        xs = np.rint(np.linspace(x1, x2, steps)).astype(int)
        ys = np.rint(np.linspace(y1, y2, steps)).astype(int)
        keep = (xs >= 0) & (xs < self.width) & (ys >= 0) & (ys < self.height)
        self.pixels[ys[keep], xs[keep]] = rgb(color)

    def rounded(self, radius, color):
        """A copy of the pixels with `color` blended over the four corners."""
        out = self.pixels.copy()
        r = min(int(radius), self.width // 2, self.height // 2)
        if r <= 0:
            return out
        alpha = _corner_alpha(r)
        fill = np.array(rgb(color), dtype=np.float32)
        for rows, columns, mask in (
                (slice(0, r), slice(0, r), alpha),
                (slice(0, r), slice(self.width - r, self.width), alpha[:, ::-1]),
                (slice(self.height - r, self.height), slice(0, r), alpha[::-1, :]),
                (slice(self.height - r, self.height), slice(self.width - r, self.width),
                 alpha[::-1, ::-1])):
            weight = mask[..., None]
            out[rows, columns] = np.rint(out[rows, columns] * (1 - weight) + fill * weight)
        return out


@lru_cache(maxsize=8)
def _corner_alpha(radius):
    """Top-left corner coverage (1 outside the arc, 0 inside) as float32."""
    return np.asarray(rounded_corner_mask(radius), dtype=np.float32) / 255.0
