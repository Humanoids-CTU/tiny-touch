"""
Zone hover / click demo — standalone, does not touch projects or the main app.

Run from the repository root:

    uv run demos/zone_hover_demo.py

Move the mouse over the body diagram: the zone under the cursor fades in with a
tinted fill, a soft glow and a breathing outline, and fades out with a short
trail as you move on. Left-click drops a green dot, right-click a red dot (each
with a small pulse and a zone flash); middle-click a dot to delete it.
Keys: 1/2/3 switch template, C clears dots.

Hit testing reuses the real mask loader and `domain.touch.zone_precedence`, so
the highlighted zone is the zone the labeler would record for that pixel.
"""

import math
import sys
import time
import tkinter as tk
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageTk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adapters.zone_masks import load_zone_masks, zones_dir  # noqa: E402
from domain.templates import TEMPLATES, get_template  # noqa: E402
from domain.touch import LINE_ZONE, NO_ZONE, OUTSIDE_ZONE, zone_precedence  # noqa: E402
from gui.resource_utils import asset_path  # noqa: E402

# --- configuration ---------------------------------------------------------
TEMPLATE = "default"            # "default", "alternate" or "general"
DISPLAY_SCALE = 1.0             # 1.0 = native 450x696
FRAME_MS = 16                   # animation tick (~60 fps)

FILL_COLOR = (90, 150, 255)     # hover tint (multiplied under the line art)
GLOW_COLOR = (120, 175, 255)
EDGE_COLOR = (30, 95, 230)
LEFT_DOT_COLOR = "#30a46c"      # green
RIGHT_DOT_COLOR = "#e5484d"     # red
CANVAS_BG = "#1d1f24"

FILL_ALPHA = 0.38
GLOW_ALPHA = 0.55
EDGE_ALPHA = 0.95
FLASH_ALPHA = 0.55
FADE_IN_S = 0.08                # time constant of the exponential ease
FADE_OUT_S = 0.22               # slower out = visible trail
FLASH_DECAY_S = 0.45
BREATHE_HZ = 0.9
BREATHE_DEPTH = 0.18

DOT_RADIUS = 6
DOT_PULSE_S = 0.3               # one gentle swell and settle
DOT_PULSE_GROW = 0.4            # peak extra size (0.4 = +40 %)
DOT_REMOVE_S = 0.18
DOT_HIT_RADIUS = 10
STATUS_HEIGHT = 48              # fixed so changing text never resizes the window

EDGE_GROW_PX = 2
GLOW_BLUR_SIGMA = 5
BBOX_PAD = 16

NON_HIGHLIGHT = {LINE_ZONE, OUTSIDE_ZONE, NO_ZONE}
TEMPLATE_KEYS = {"1": "default", "2": "alternate", "3": "general"}


def _lut(alpha):
    return [int(v * alpha) for v in range(256)]


def _rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


class ZoneSprite:
    """Cropped per-zone fill / edge / glow masks, ready to paste."""

    def __init__(self, name, region, shape):
        h, w = shape
        ys, xs = np.nonzero(region)
        x0, y0 = max(xs.min() - BBOX_PAD, 0), max(ys.min() - BBOX_PAD, 0)
        x1, y1 = min(xs.max() + BBOX_PAD + 1, w), min(ys.max() + BBOX_PAD + 1, h)
        crop = region[y0:y1, x0:x1].astype(np.uint8) * 255
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        grown = cv2.dilate(crop, kernel, iterations=EDGE_GROW_PX)
        edge = cv2.subtract(grown, cv2.erode(crop, kernel, iterations=1))
        glow = cv2.GaussianBlur(grown, (0, 0), GLOW_BLUR_SIGMA)
        glow = cv2.subtract(glow, crop // 2)  # glow mostly around, not inside
        self.name = name
        self.box = (int(x0), int(y0))
        self.fill = Image.fromarray(crop, "L")
        self.edge = Image.fromarray(edge, "L")
        self.glow = Image.fromarray(glow, "L")


class ZoneHoverDemo:
    def __init__(self, root):
        self.root = root
        root.title("TinyTouch — zone hover demo")
        root.configure(bg=CANVAS_BG)
        self.canvas = tk.Canvas(root, bg=CANVAS_BG, highlightthickness=0, cursor="crosshair")
        self.canvas.pack(padx=16, pady=(16, 8))
        self.status_frame = tk.Frame(root, bg=CANVAS_BG, height=STATUS_HEIGHT)
        self.status_frame.pack(fill="x", padx=16, pady=(0, 12))
        self.status_frame.pack_propagate(False)
        self.status = tk.Label(self.status_frame, bg=CANVAS_BG, fg="#e6e8ee",
                               font=("Segoe UI", 11), anchor="w")
        self.status.pack(fill="x")
        tk.Label(self.status_frame, bg=CANVAS_BG, fg="#80838d", font=("Segoe UI", 9), anchor="w",
                 text="left = green · right = red · middle = delete · [1/2/3] template · [C] clear"
                 ).pack(fill="x")

        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Leave>", self.on_leave)
        self.canvas.bind("<Button-1>", lambda e: self.add_dot(e, LEFT_DOT_COLOR))
        self.canvas.bind("<Button-3>", lambda e: self.add_dot(e, RIGHT_DOT_COLOR))
        self.canvas.bind("<Button-2>", self.on_middle_click)
        root.bind("<Key>", self.on_key)

        self.load_template(TEMPLATE)
        self.last_tick = time.perf_counter()
        self.root.after(FRAME_MS, self.tick)

    # --- setup ---------------------------------------------------------------
    def load_template(self, template):
        self.template = template
        definition = get_template(template)
        base = Image.open(asset_path(definition.diagram)).convert("RGBA")
        white = Image.new("RGBA", base.size, (255, 255, 255, 255))
        self.base = Image.alpha_composite(white, base).convert("RGB")

        masks = load_zone_masks(zones_dir(template))
        h, w = self.base.size[1], self.base.size[0]
        # Same rule as domain.touch.zones_at: lower tier wins, then name order.
        ordered = sorted(masks, key=lambda item: (zone_precedence(item[0]), item[0]))
        self.names = [name for name, _ in ordered]
        self.label_map = np.full((h, w), -1, dtype=np.int16)
        self.sprites = {}
        for index, (name, mask) in enumerate(ordered):
            if mask.shape != (h, w):
                mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
            free = (mask == 0) & (self.label_map < 0)
            self.label_map[free] = index
        for index, name in enumerate(self.names):
            region = self.label_map == index
            if name not in NON_HIGHLIGHT and region.any():
                self.sprites[name] = ZoneSprite(name, region, (h, w))

        self.level = {name: 0.0 for name in self.sprites}
        self.flash = {name: 0.0 for name in self.sprites}
        self.flash_color = {name: _rgb(LEFT_DOT_COLOR) for name in self.sprites}
        self.hover = None
        self.dots = []          # dicts: x, y, zone, born, dying, item
        self.canvas.delete("all")
        self.size = (int(w * DISPLAY_SCALE), int(h * DISPLAY_SCALE))
        self.canvas.configure(width=self.size[0], height=self.size[1])
        self.status_frame.configure(width=self.size[0])
        self.image_item = self.canvas.create_image(0, 0, anchor="nw")
        self.tag_bg = self.canvas.create_rectangle(0, 0, 0, 0, fill="#111318", outline="", state="hidden")
        self.tag_text = self.canvas.create_text(0, 0, text="", fill="#ffffff",
                                                font=("Segoe UI", 10, "bold"), anchor="w", state="hidden")
        self.dirty = True
        self.update_status()

    # --- hit test ------------------------------------------------------------
    def zone_at(self, cx, cy):
        x, y = int(cx / DISPLAY_SCALE), int(cy / DISPLAY_SCALE)
        h, w = self.label_map.shape
        if not (0 <= x < w and 0 <= y < h):
            return NO_ZONE
        index = self.label_map[y, x]
        return self.names[index] if index >= 0 else NO_ZONE

    def dot_near(self, cx, cy):
        best, best_d = None, DOT_HIT_RADIUS
        for dot in self.dots:
            d = math.hypot(dot["x"] - cx, dot["y"] - cy)
            if not dot["dying"] and d <= best_d:
                best, best_d = dot, d
        return best

    # --- events --------------------------------------------------------------
    def on_motion(self, event):
        zone = self.zone_at(event.x, event.y)
        self.hover = zone if zone in self.sprites else None
        self.place_tag(event.x, event.y, zone)
        self.update_status(zone)

    def on_leave(self, _event):
        self.hover = None
        self.canvas.itemconfigure(self.tag_bg, state="hidden")
        self.canvas.itemconfigure(self.tag_text, state="hidden")
        self.update_status()

    def add_dot(self, event, color):
        zone = self.zone_at(event.x, event.y)
        dot = {"x": event.x, "y": event.y, "zone": zone, "born": time.perf_counter(), "dying": None,
               "item": self.canvas.create_oval(0, 0, 0, 0, fill=color, outline="white", width=2)}
        self.dots.append(dot)
        if zone in self.flash:
            self.flash[zone] = 1.0
            self.flash_color[zone] = _rgb(color)
        self.canvas.tag_raise(self.tag_bg)
        self.canvas.tag_raise(self.tag_text)
        self.update_status(zone)

    def on_middle_click(self, event):
        dot = self.dot_near(event.x, event.y)
        if dot:
            dot["dying"] = time.perf_counter()
            self.update_status(self.zone_at(event.x, event.y))

    def on_key(self, event):
        if event.char in TEMPLATE_KEYS and TEMPLATE_KEYS[event.char] in TEMPLATES:
            self.load_template(TEMPLATE_KEYS[event.char])
        elif event.char.lower() == "c":
            now = time.perf_counter()
            for dot in self.dots:
                dot["dying"] = dot["dying"] or now

    # --- UI bits ---------------------------------------------------------------
    def place_tag(self, x, y, zone):
        if zone == NO_ZONE:
            self.canvas.itemconfigure(self.tag_bg, state="hidden")
            self.canvas.itemconfigure(self.tag_text, state="hidden")
            return
        self.canvas.itemconfigure(self.tag_text, text=zone, state="normal")
        tx, ty = x + 16, y - 14
        self.canvas.coords(self.tag_text, tx, ty)
        x0, y0, x1, y1 = self.canvas.bbox(self.tag_text)
        if x1 + 6 > self.size[0]:  # flip to the left near the right edge
            tx = x - 16 - (x1 - x0)
            self.canvas.coords(self.tag_text, tx, ty)
            x0, y0, x1, y1 = self.canvas.bbox(self.tag_text)
        self.canvas.coords(self.tag_bg, x0 - 6, y0 - 3, x1 + 6, y1 + 3)
        self.canvas.itemconfigure(self.tag_bg, state="normal")

    def update_status(self, zone=None):
        alive = [d for d in self.dots if not d["dying"]]
        where = zone if zone and zone != NO_ZONE else "—"
        last = alive[-1]["zone"] if alive else "—"
        self.status.configure(
            text=f"Zone: {where}   ·   dots: {len(alive)}   ·   last: {last}   ·   {self.template}"
        )

    # --- animation -----------------------------------------------------------
    def tick(self):
        now = time.perf_counter()
        dt = min(now - self.last_tick, 0.1)
        self.last_tick = now

        changed = False
        for name in self.level:
            target = 1.0 if name == self.hover else 0.0
            current = self.level[name]
            if abs(target - current) > 0.002:
                tau = FADE_IN_S if target > current else FADE_OUT_S
                self.level[name] = target + (current - target) * math.exp(-dt / tau)
                changed = True
            elif current != target:
                self.level[name] = target
                changed = True
            if self.flash[name] > 0.002:
                self.flash[name] *= math.exp(-dt / (FLASH_DECAY_S / 3))
                changed = True
            elif self.flash[name]:
                self.flash[name] = 0.0
                changed = True

        if changed or self.hover or self.dirty:
            self.render(now)
            self.dirty = False
        self.animate_dots(now)
        self.root.after(FRAME_MS, self.tick)

    def render(self, now):
        self.photo = ImageTk.PhotoImage(self.compose(now))
        self.canvas.itemconfigure(self.image_item, image=self.photo)

    def compose(self, now):
        breathe = 1.0 - BREATHE_DEPTH * (0.5 + 0.5 * math.sin(now * 2 * math.pi * BREATHE_HZ))
        layer = Image.new("RGB", self.base.size, (255, 255, 255))
        edges = []
        for name, sprite in self.sprites.items():
            level, flash = self.level[name], self.flash[name]
            if level < 0.003 and flash < 0.003:
                continue
            if level >= 0.003:
                layer.paste(GLOW_COLOR, sprite.box, sprite.glow.point(_lut(level * GLOW_ALPHA)))
                layer.paste(FILL_COLOR, sprite.box, sprite.fill.point(_lut(level * FILL_ALPHA)))
            if flash >= 0.003:
                layer.paste(self.flash_color[name], sprite.box, sprite.fill.point(_lut(flash * FLASH_ALPHA)))
            pulse = breathe if name == self.hover else 1.0
            edges.append((sprite, level * EDGE_ALPHA * pulse))
        frame = ImageChops.multiply(layer, self.base)  # keeps the line art crisp
        for sprite, alpha in edges:
            if alpha >= 0.003:
                frame.paste(EDGE_COLOR, sprite.box, sprite.edge.point(_lut(alpha)))
        if DISPLAY_SCALE != 1.0:
            frame = frame.resize(self.size, Image.BILINEAR)
        return frame

    def animate_dots(self, now):
        for dot in list(self.dots):
            hovered = self.dot_near(*self.canvas_pointer()) is dot
            if dot["dying"]:
                t = min((now - dot["dying"]) / DOT_REMOVE_S, 1.0)
                r = DOT_RADIUS * (1 - t) ** 2
                if t >= 1.0:
                    self.canvas.delete(dot["item"])
                    self.dots.remove(dot)
                    self.update_status()
                    continue
            else:
                t = min((now - dot["born"]) / DOT_PULSE_S, 1.0)
                pulse = 1.0 + DOT_PULSE_GROW * math.sin(math.pi * t)  # swell once, settle
                r = DOT_RADIUS * pulse * (1.3 if hovered else 1.0)
            self.canvas.coords(dot["item"], dot["x"] - r, dot["y"] - r, dot["x"] + r, dot["y"] + r)

    def canvas_pointer(self):
        return (self.canvas.winfo_pointerx() - self.canvas.winfo_rootx(),
                self.canvas.winfo_pointery() - self.canvas.winfo_rooty())


def main():
    root = tk.Tk()
    ZoneHoverDemo(root)
    root.mainloop()


if __name__ == "__main__":
    main()
