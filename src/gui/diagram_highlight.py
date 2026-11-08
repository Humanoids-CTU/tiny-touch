"""
gui/diagram_highlight.py
Hover feedback for the annotation diagram: the zone under the pointer fades in
with an amber tint, a soft glow and an outline, a small tag next to the pointer
names it, and a click flashes the zone in the dot's colour.

Visual only. The zone shown is the zone a click would record: the per-pixel
map comes from `domain.touch.zone_label_map`, which applies the same
precedence rule as `zones_at`, and the pointer is converted to native pixels
exactly as `LabelingApp.on_diagram_click` does.

The highlighter owns a few canvas items of its own (tagged HOVER_TAG and
TOOLTIP_TAG). It never touches the `diagram`, zone-label or `dot` items, and
the app's dots-only repaint never touches these. A full repaint deletes every
item on the canvas, so the app tells the highlighter with `canvas_cleared()`.

Animation runs on a single `after` loop that only exists while a level is
still moving: a steady hover and an idle diagram cost nothing.
"""

import logging
import time
import tkinter as tk

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageTk

from domain.touch import LINE_ZONE, NO_ZONE, OUTSIDE_ZONE, zone_label_map


logger = logging.getLogger(__name__)

# --- look --------------------------------------------------------------------
# The selected limb is painted blue in the limb images, so the hover is amber.
# The fill is MULTIPLIED into the diagram (white -> tint, black lines stay
# black, the blue limb keeps its hue), so the line art stays crisp.
FILL_COLOR = (255, 170, 60)
GLOW_COLOR = (255, 196, 110)
EDGE_COLOR = (205, 112, 14)
FILL_STRENGTH = 0.42            # 0 = no tint, 1 = the full FILL_COLOR
GLOW_ALPHA = 0.5
EDGE_ALPHA = 0.95
FLASH_STRENGTH = 0.6            # click flash in the dot's colour

# --- timing (seconds) ----------------------------------------------------------
# Fixed durations with a smoothstep ease, so a fade is finished (and its timer
# gone) after exactly this long, instead of creeping toward the target.
FADE_IN_S = 0.12
FADE_OUT_S = 0.25               # slower out leaves a short trail
FLASH_DECAY_S = 0.45
FRAME_MS = 16                   # ~60 fps while something is moving

# --- geometry (native diagram pixels; scaled to the display) ------------------
EDGE_GROW_PX = 2
GLOW_BLUR_SIGMA = 5
BBOX_PAD = 16

# --- tooltip ------------------------------------------------------------------
TOOLTIP_BG = "#1f2430"
TOOLTIP_FG = "#ffffff"
TOOLTIP_FONT = ("Segoe UI", 9, "bold")
TOOLTIP_OFFSET = (14, -14)      # from the pointer to the tag's left-middle
TOOLTIP_PAD = (7, 3)            # horizontal, vertical padding of the tag
TOOLTIP_MARGIN = 4              # keep the tag this far inside the canvas

HOVER_TAG = "hover"
TOOLTIP_TAG = "hover-tip"
DIAGRAM_TAG = "diagram"

#: Zones that are reported in the tooltip but never painted: the boundary
#: lines, the off-body area and the "nothing" sentinel.
NO_SPRITE = frozenset({LINE_ZONE, OUTSIDE_ZONE, NO_ZONE})


def _lut(alpha):
    """Point table scaling an 8-bit mask by `alpha`."""
    return [int(v * alpha) for v in range(256)]


def _rgb(color):
    """`#rrggbb` or an (r, g, b) tuple -> (r, g, b)."""
    if isinstance(color, str):
        return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    return tuple(color)


def _tint(color, strength):
    """Multiply colour lerped from white (no change) toward `color`."""
    return tuple(int(round(255 - (255 - c) * strength)) for c in color)


def _blend(color_a, color_b, amount):
    """Linear mix: `amount` 0 = color_a, 1 = color_b."""
    return tuple(int(round(a + (b - a) * amount)) for a, b in zip(color_a, color_b))


class ZoneSprite:
    """Cropped fill / edge / glow masks of one zone at display scale."""

    def __init__(self, name, region, display_size, scale):
        w, h = display_size
        soft = cv2.resize(region.astype(np.uint8) * 255, (w, h), interpolation=cv2.INTER_AREA)
        ys, xs = np.nonzero(soft)
        pad = max(1, int(round(BBOX_PAD * scale)))
        x0, y0 = max(int(xs.min()) - pad, 0), max(int(ys.min()) - pad, 0)
        x1, y1 = min(int(xs.max()) + pad + 1, w), min(int(ys.max()) + pad + 1, h)
        crop = soft[y0:y1, x0:x1]
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        grown = cv2.dilate(crop, kernel, iterations=max(1, int(round(EDGE_GROW_PX * scale))))
        edge = cv2.subtract(grown, cv2.erode(crop, kernel, iterations=1))
        glow = cv2.GaussianBlur(grown, (0, 0), max(1.0, GLOW_BLUR_SIGMA * scale))
        glow = cv2.subtract(glow, crop // 2)  # a halo around the zone, lighter inside
        self.name = name
        self.box = (x0, y0, x1, y1)
        self.fill = Image.fromarray(crop)
        self.edge = Image.fromarray(edge)
        self.glow = Image.fromarray(glow)


class DiagramHighlighter:
    """Hover highlight, click flash and zone tag on one diagram canvas.

    `tooltip_for(zone, x, y)` is the app's say on what the tag reads for the
    zone under the pointer at native pixel (x, y); `None` hides the tag. That
    keeps zone naming and channel selectors out of this module.
    """

    def __init__(self, canvas, masks, scale, display_size, tooltip_for):
        started = time.perf_counter()
        self.canvas = canvas
        self.scale = float(scale)
        self.display_size = tuple(display_size)
        self._tooltip_for = tooltip_for
        self._label_map, self._names = zone_label_map(masks)
        self._sprites = {}
        for index, name in enumerate(self._names):
            region = self._label_map == index
            if name not in NO_SPRITE and region.any():
                self._sprites[name] = ZoneSprite(name, region, self.display_size, self.scale)
        self._base = None               # display-scale RGB copy of the drawn diagram
        self._enabled = True
        self._hover = None              # zone under the pointer, sprite zones only
        self._level = {}                # zone -> 0..1 hover level (only zones in motion or lit)
        self._flash = {}                # zone -> (0..1 flash level, (r, g, b))
        self._items = {}                # zone -> (canvas item id, PhotoImage)
        self._tip_items = None          # (background id, text id) or None
        self._after_id = None
        self._last_tick = None
        logger.debug(
            "diagram highlighter built: %d sprites scale=%s display=%sx%s in %.1f ms",
            len(self._sprites), self.scale, *self.display_size,
            (time.perf_counter() - started) * 1000,
        )

    # --- app-facing surface ------------------------------------------------------
    def set_base(self, image):
        """Display-scale RGB image of the diagram as drawn (the fill multiplies into it)."""
        if image.size != self.display_size:
            raise ValueError(f"base image {image.size} does not match display size {self.display_size}")
        self._base = image

    def canvas_cleared(self):
        """The app deleted every canvas item; forget ours and redraw on the next tick."""
        self._items.clear()
        self._tip_items = None
        if self._level or self._flash:
            self._schedule()

    def set_enabled(self, enabled):
        enabled = bool(enabled)
        if enabled == self._enabled:
            return
        self._enabled = enabled
        logger.debug("diagram hover effects %s", "enabled" if enabled else "disabled")
        if not enabled:
            self.on_leave()

    def zone_at(self, x, y):
        """Zone name the labeler would record for display pixel (x, y)."""
        # Same conversion as LabelingApp.on_diagram_click, so the answer matches.
        nx, ny = int(x * (1.0 / self.scale)), int(y * (1.0 / self.scale))
        h, w = self._label_map.shape
        if not (0 <= nx < w and 0 <= ny < h):
            return NO_ZONE
        index = int(self._label_map[ny, nx])
        return self._names[index] if index >= 0 else NO_ZONE

    def on_motion(self, x, y):
        if not self._enabled or self._base is None:
            return
        zone = self.zone_at(x, y)
        hover = zone if zone in self._sprites else None
        if hover != self._hover:
            self._hover = hover
            if hover is not None:
                self._level.setdefault(hover, 0.0)
            self._schedule()
        nx, ny = x * (1.0 / self.scale), y * (1.0 / self.scale)
        self._place_tooltip(x, y, self._tooltip_for(zone, nx, ny))

    def on_leave(self):
        self._hide_tooltip()
        if self._hover is not None:
            self._hover = None
            self._schedule()

    def flash(self, zone, color):
        """Flash `zone` in `color` (hex or rgb), fading out over FLASH_DECAY_S."""
        if not self._enabled or zone not in self._sprites:
            return
        self._flash[zone] = (1.0, _rgb(color))
        self._level.setdefault(zone, 0.0)
        self._schedule()

    def destroy(self):
        if self._after_id is not None:
            try:
                self.canvas.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        self._hover = None
        self._level.clear()
        self._flash.clear()
        self._delete_items()

    # --- animation ---------------------------------------------------------------
    def _schedule(self):
        if self._after_id is None:
            self._last_tick = time.perf_counter()
            self._after_id = self.canvas.after(FRAME_MS, self._hover_tick)

    def _hover_tick(self):
        self._after_id = None
        now = time.perf_counter()
        dt = min(now - self._last_tick, 0.1)
        self._last_tick = now
        moving = False
        for zone in list(self._level):
            target = 1.0 if zone == self._hover else 0.0
            current = self._level[zone]
            level = self._step(current, target, FADE_IN_S if target > current else FADE_OUT_S, dt)
            flash, color = self._flash.get(zone, (0.0, None))
            if flash:
                flash = self._step(flash, 0.0, FLASH_DECAY_S, dt)
                if flash:
                    self._flash[zone] = (flash, color)
                else:
                    del self._flash[zone]
            self._level[zone] = level
            if level == 0.0 and not flash:
                del self._level[zone]
                self._delete_item(zone)
                continue
            if level != target or flash:
                moving = True
            try:
                self._paint(zone, level, flash, color)
            except tk.TclError:  # canvas destroyed mid-animation
                return
        if moving:
            self._schedule()

    @staticmethod
    def _step(current, target, duration, dt):
        """Move `current` toward `target` at 1/duration per second, never past it."""
        if target > current:
            return min(current + dt / duration, target)
        return max(current - dt / duration, target)

    @staticmethod
    def _ease(level):
        """Smoothstep: gentle start and finish of a fade."""
        return level * level * (3.0 - 2.0 * level)

    def _paint(self, zone, level, flash, flash_color):
        sprite = self._sprites[zone]
        overlay = self._compose(sprite, level, flash, flash_color)
        item = self._items.get(zone)
        if item is None:
            photo = ImageTk.PhotoImage(overlay)
            item_id = self.canvas.create_image(
                sprite.box[0], sprite.box[1], anchor="nw", image=photo, tags=(HOVER_TAG,),
            )
            if self.canvas.find_withtag(DIAGRAM_TAG):
                # Above the diagram, below the zone labels and the dots.
                self.canvas.tag_raise(item_id, DIAGRAM_TAG)
            self._items[zone] = (item_id, photo)
        else:
            item[1].paste(overlay)

    def _compose(self, sprite, level, flash, flash_color):
        x0, y0, x1, y1 = sprite.box
        size = (x1 - x0, y1 - y0)
        level = self._ease(level)
        tint = _tint(FILL_COLOR, level * FILL_STRENGTH)
        if flash:
            # Blend toward the dot's colour (not into the amber, which goes olive).
            tint = _blend(tint, _tint(flash_color, FLASH_STRENGTH), self._ease(flash))
        fill = ImageChops.multiply(self._base.crop(sprite.box), Image.new("RGB", size, tint))
        fill = fill.convert("RGBA")
        fill.putalpha(sprite.fill)
        glow = Image.new("RGBA", size, GLOW_COLOR + (0,))
        glow.putalpha(sprite.glow.point(_lut(level * GLOW_ALPHA)))
        edge = Image.new("RGBA", size, EDGE_COLOR + (0,))
        edge.putalpha(sprite.edge.point(_lut(level * EDGE_ALPHA)))
        return Image.alpha_composite(Image.alpha_composite(fill, glow), edge)

    # --- canvas items --------------------------------------------------------------
    def _delete_item(self, zone):
        item = self._items.pop(zone, None)
        if item is not None:
            try:
                self.canvas.delete(item[0])
            except tk.TclError:
                pass

    def _delete_items(self):
        for zone in list(self._items):
            self._delete_item(zone)
        self._hide_tooltip()

    def _place_tooltip(self, x, y, text):
        if not text:
            self._hide_tooltip()
            return
        if self._tip_items is None:
            background = self.canvas.create_rectangle(
                0, 0, 0, 0, fill=TOOLTIP_BG, outline="", tags=(TOOLTIP_TAG,),
            )
            label = self.canvas.create_text(
                0, 0, text="", fill=TOOLTIP_FG, font=TOOLTIP_FONT, anchor="w", tags=(TOOLTIP_TAG,),
            )
            self._tip_items = (background, label)
        background, label = self._tip_items
        self.canvas.itemconfigure(label, text=text, state="normal")
        pad_x, pad_y = TOOLTIP_PAD
        width, height = self.display_size
        tx, ty = x + TOOLTIP_OFFSET[0], y + TOOLTIP_OFFSET[1]
        self.canvas.coords(label, tx, ty)
        left, top, right, bottom = self.canvas.bbox(label)
        if right + pad_x + TOOLTIP_MARGIN > width:  # flip to the left near the right edge
            tx = x - TOOLTIP_OFFSET[0] - (right - left)
        half = (bottom - top) / 2 + pad_y + TOOLTIP_MARGIN
        ty = min(max(ty, half), height - half)
        self.canvas.coords(label, tx, ty)
        left, top, right, bottom = self.canvas.bbox(label)
        self.canvas.coords(background, left - pad_x, top - pad_y, right + pad_x, bottom + pad_y)
        self.canvas.itemconfigure(background, state="normal")
        self.canvas.tag_raise(TOOLTIP_TAG)

    def _hide_tooltip(self):
        if self._tip_items is None:
            return
        for item in self._tip_items:
            try:
                self.canvas.itemconfigure(item, state="hidden")
            except tk.TclError:
                self._tip_items = None
                return
