"""Canvas-drawn controls of the TinyTouch look (ported from demos/design_lab.py).

Every widget paints only with theme roles (read as ``theme.X`` at paint time),
caches the images it draws, and repaints itself in ``theme_changed()``, which
``theme._refresh_colors`` calls after every appearance switch.
"""

import tkinter as tk
import tkinter.font as tkfont
from collections import OrderedDict
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

from gui import theme

# Per-root PhotoImage cache size. Widgets keep references to what they show,
# so evicting an entry never blanks a visible image.
PHOTO_CACHE_SIZE = 256
SWITCH_W, SWITCH_H = 36, 22       # design px
SWITCH_KNOB_INSET = 2
SEG_TEXT_PAD = 11                 # horizontal text padding inside a segment
SEG_ICON_PX, SEG_ICON_GAP = 9, 7
PILL_TEXT_PAD = 12                # ParamPill text inset from the pill edge
PILL_MIN_W = 56                  # long names elide (_fit_text), so pills can stay narrow
TAG_PAD_X, TAG_PAD_Y, TAG_RADIUS = 9, 4, 6
ELLIPSIS = "…"
SEG_CELL_TEXT_PAD = 6             # grid cells: minimum text inset before eliding
SEG_GRID_MIN_W = 60               # requested width of a column grid (design px)


def _elide(font, text, avail):
    """`text` shortened with an ellipsis so it fits `avail` px in `font`."""
    if avail <= 0 or font.measure(text) <= avail:
        return text
    while text and font.measure(text + ELLIPSIS) > avail:
        text = text[:-1]
    return text.rstrip() + ELLIPSIS


class ElidingLabel(ttk.Label):
    """A label that asks for no width and shows its text elided to the width it gets."""

    def __init__(self, parent, text="", **kwargs):
        super().__init__(parent, text=text, width=1, **kwargs)
        self._full = str(text)
        self._font = tkfont.Font(root=self._root(),
                                 font=ttk.Style(self).lookup(kwargs.get("style", "TLabel"), "font") or "TkDefaultFont")
        self.bind("<Configure>", lambda _e: self._apply(), add="+")

    def configure(self, cnf=None, **kw):
        kw = {**(cnf or {}), **kw}
        if "text" in kw:
            self._full = str(kw.pop("text"))
            self._apply()
        return super().configure(**kw) if kw else None

    config = configure

    def cget(self, key):
        return self._full if key == "text" else super().cget(key)

    def _apply(self):
        shown = _elide(self._font, self._full, self.winfo_width())
        if super().cget("text") != shown:
            super().configure(text=shown)
GROUP_BOTTOM_SPACER = 2           # design px below the last GroupedList row


def _photo(widget, key, factory):
    """Cached PhotoImage per Tk root; ``factory`` returns a PIL image."""
    root = widget._root()
    cache = root.__dict__.setdefault("_tt_photo_cache", OrderedDict())
    if key in cache:
        cache.move_to_end(key)
        return cache[key]
    photo = ImageTk.PhotoImage(factory(), master=root)
    cache[key] = photo
    if len(cache) > PHOTO_CACHE_SIZE:
        cache.popitem(last=False)
    return photo


def _rounded_photo(widget, w, h, radius, fill, border=None, depth=None, margin=0, under=None):
    """``under`` makes the image opaque on that colour (much faster for Tk to draw)."""
    w, h = max(1, int(round(w))), max(1, int(round(h)))
    key = ("rounded", w, h, radius, fill, border, depth, margin, theme.SCALE, under)
    return _photo(widget, key, lambda: theme.rounded_image(w, h, radius, fill, border, depth, margin, under))


# --- RoundedCard ----------------------------------------------------------------
class RoundedCard(tk.Canvas):
    """A canvas painting a rounded card (nine-slice) that hosts ``.inner``.

    ``fill``/``border``/``outer`` are palette roles; ``radius`` is in design px,
    ``pad`` in device px (default: half the radius, at least 4 px).
    ``shadow`` None means the "card" shadow when ``fill == "CARD"``, else none;
    pass a DEPTH name to force one or False to disable it. A shadowed card has
    no border (as in the lab). ``fill_height`` makes the inner frame fill the
    canvas (the video) instead of the canvas growing to the content.
    """

    def __init__(self, parent, *, fill="CARD", border="LINE_SOFT", radius=theme.CARD_RADIUS, outer="WIN",
                 pad=None, shadow=None, fill_height=False, fit_width=True):
        super().__init__(parent, highlightthickness=0, bd=0, height=10, width=10)
        self.fill, self.border, self.radius, self.outer = fill, border, radius, outer
        self.fill_height = fill_height
        # fit_width=False: the card never asks for its content's width; it
        # takes whatever its parent gives (content elides to fit).
        self.fit_width = fit_width
        if shadow is None:
            shadow = "card" if fill == "CARD" else None
        self._depth = shadow or None
        if fill == "CARD":
            self.inner = ttk.Frame(self, style="Card.TFrame")
        else:
            self.inner = theme.bind_colors(tk.Frame(self, bd=0, highlightthickness=0), bg=fill)
        self._margin = theme.px(theme.SHADOW_MARGIN) if self._depth else 0
        base_pad = pad if pad is not None else max(theme.px(radius) // 2, theme.px(4))
        self._pad = base_pad + self._margin
        self._win = self.create_window(self._pad, self._pad, window=self.inner, anchor="nw")
        self._painted = None
        self._slices = {}
        self.inner.bind("<Configure>", self._fit, add="+")
        self.bind("<Configure>", lambda _e: self.repaint(), add="+")
        # The content only maps (and reports its size) once it lies inside the
        # canvas, so size the canvas from the content's request up front.
        self.after_idle(self._fit)

    def _fit(self, _event=None):
        # Grow the canvas to its content; act only on a real change, otherwise
        # canvas resize -> inner resize -> canvas resize can loop forever.
        if not self.winfo_exists():
            return
        if not self.fill_height:
            want = self.inner.winfo_reqheight() + 2 * self._pad
            if int(self.cget("height")) != want:
                self.configure(height=want)
        if not self.fit_width:
            return
        want_w = self.inner.winfo_reqwidth() + 2 * self._pad
        if int(self.cget("width")) != want_w:
            self.configure(width=want_w)

    def fit(self):
        """Size the card to its content now (before measuring a new window)."""
        self._fit()

    def set_border(self, role):
        """Change the border's palette role; repaints only on a change."""
        if role != self.border:
            self.border = role
            self.theme_changed()

    def _corner_size(self):
        return self._margin + theme.px(self.radius) + 2

    def _template(self):
        """Small (2k+1)^2 card image; corners and 1 px edge strips come from it."""
        k = self._corner_size()
        size = 2 * k + 1
        border = None if self._depth else theme.color(self.border)
        spec = (size, theme.px(self.radius), theme.color(self.fill), border, self._depth, self._margin,
                theme.color(self.outer), theme.SCALE)
        return theme.rounded_image(size, size, *spec[1:-1]), k, spec

    def repaint(self):
        w, h = max(self.winfo_width(), 1), max(self.winfo_height(), 1)
        key = (w, h, theme.current_appearance(), theme.color(self.fill), theme.color(self.outer))
        if key == self._painted:
            return
        self._painted = key
        self.configure(bg=theme.color(self.outer))
        tmpl, k, spec = self._template()
        k = min(k, w // 2, h // 2)
        self.delete("bg")
        photos = []

        def put(x, y, box, size=None):
            def build():
                part = tmpl.crop(box)
                return part.resize(size, Image.Resampling.NEAREST) if size else part
            photo = _photo(self, ("card", spec, box, size), build)
            photos.append(photo)
            self.create_image(x, y, image=photo, anchor="nw", tags="bg")

        t = tmpl.width
        mid = t // 2
        put(0, 0, (0, 0, k, k))
        put(w - k, 0, (t - k, 0, t, k))
        put(0, h - k, (0, t - k, k, t))
        put(w - k, h - k, (t - k, t - k, t, t))
        if w - 2 * k > 0:
            put(k, 0, (mid, 0, mid + 1, k), (w - 2 * k, k))
            put(k, h - k, (mid, t - k, mid + 1, t), (w - 2 * k, k))
        if h - 2 * k > 0:
            put(0, k, (0, mid, k, mid + 1), (k, h - 2 * k))
            put(w - k, k, (t - k, mid, t, mid + 1), (k, h - 2 * k))
        if w - 2 * k > 0 and h - 2 * k > 0:
            fill = theme.color(self.fill)
            self.create_rectangle(k, k, w - k, h - k, fill=fill, outline=fill, width=0, tags="bg")
        self._photos = photos
        self.tag_lower("bg")
        self.itemconfigure(self._win, width=max(1, w - 2 * self._pad))
        if self.fill_height:
            self.itemconfigure(self._win, height=max(1, h - 2 * self._pad))

    def theme_changed(self):
        self._painted = None
        self.repaint()


# --- SegmentedControl ------------------------------------------------------------
class SegmentedControl(tk.Canvas):
    """Apple-style segmented control.

    A rounded grey track; the selected (or pressed) segment is a white pill
    with a soft shadow, a hovered one a darker grey. With ``variable`` it acts
    like radio buttons, otherwise every segment is a push button. ``items``
    are str or (value, label); ``command(value)`` runs on a click. ``columns``
    lays segments out in a grid filling the width (always gapless);
    ``gapless`` makes the selected pill fill its whole cell. ``icons`` maps a
    value to "play" or "stop". ``min_seg`` is a minimum segment width (design px).
    """

    def __init__(self, parent, items, *, variable=None, command=None, columns=0, gapless=False,
                 icons=None, min_seg=0, bg="WIN"):
        super().__init__(parent, highlightthickness=0, bd=0, cursor="hand2")
        pairs = [(i, i) if isinstance(i, str) else tuple(i) for i in items]
        self._values = [v for v, _ in pairs]
        self._labels = [lbl for _, lbl in pairs]
        self.variable, self.command, self.columns, self.bg = variable, command, columns, bg
        self.gapless = gapless or bool(columns)
        self.icons = dict(icons or {})
        self._disabled = set()
        self.hover = self.pressed = None
        px = theme.px
        self.font = tkfont.Font(root=self._root(), font=theme.ui_font(10))
        self.font_raised = tkfont.Font(root=self._root(), font=theme.ui_font(10, medium=True))
        # Inset by the same margin buttons keep for their shadow, so a track
        # and a button side by side share top and bottom edges.
        self.margin = px(theme.SHADOW_MARGIN)
        self.pad = self.gap = 0 if self.gapless else px(theme.SEG_PAD)
        self.icon_px, self.icon_gap = px(SEG_ICON_PX), px(SEG_ICON_GAP)
        self.seg_h = px(theme.CONTROL_H) - 2 * self.pad
        self.seg_w = [max(px(min_seg) if min_seg else 0,
                          self.font_raised.measure(lbl) + 2 * px(SEG_TEXT_PAD)
                          + (self.icon_px + self.icon_gap if v in self.icons else 0))
                      for v, lbl in pairs]
        if self.gapless and not columns:
            self.seg_w = [max(self.seg_w)] * len(self.seg_w)
        rows = -(-len(pairs) // columns) if columns else 1
        height = rows * self.seg_h + (rows - 1) * self.gap + 2 * (self.pad + self.margin)
        width = sum(self.seg_w) + self.gap * (len(pairs) - 1) + 2 * (self.pad + self.margin)
        if columns:
            # The grid takes its parent's width and elides labels that do not
            # fit, so it asks for almost nothing.
            width = px(SEG_GRID_MIN_W)
        self.configure(height=height, width=width)
        self._trace = None
        if variable is not None:
            self._trace = variable.trace_add("write", lambda *_: self.repaint())
        self.bind("<Configure>", lambda _e: self.repaint(), add="+")
        self.bind("<Motion>", lambda e: self._set(hover=self._hit(e.x, e.y)), add="+")
        self.bind("<Leave>", lambda _e: self._set(hover=None, pressed=None), add="+")
        self.bind("<ButtonPress-1>", lambda e: self._set(pressed=self._hit(e.x, e.y)), add="+")
        self.bind("<ButtonRelease-1>", self._release, add="+")
        self.bind("<Destroy>", self._on_destroy, add="+")

    @property
    def values(self):
        return list(self._values)

    def _on_destroy(self, event):
        if event.widget is self and self._trace is not None:
            try:
                self.variable.trace_remove("write", self._trace)
            except tk.TclError:
                pass
            self._trace = None

    def _boxes(self):
        w = max(self.winfo_width(), int(self.cget("width")))
        inset = self.pad + self.margin
        boxes = []
        if self.columns:
            cw = (w - 2 * inset - (self.columns - 1) * self.gap) / self.columns
            for i in range(len(self._values)):
                r, c = divmod(i, self.columns)
                x, y = inset + c * (cw + self.gap), inset + r * (self.seg_h + self.gap)
                boxes.append((x, y, x + cw, y + self.seg_h))
        else:
            x = inset
            for sw in self.seg_w:
                boxes.append((x, inset, x + sw, inset + self.seg_h))
                x += sw + self.gap
        return boxes

    def _hit(self, x, y):
        for i, (x0, y0, x1, y1) in enumerate(self._boxes()):
            if x0 <= x <= x1 and y0 <= y <= y1:
                return None if self._values[i] in self._disabled else i
        return None

    def _set(self, **changes):
        changed = any(getattr(self, k) != v for k, v in changes.items())
        for k, v in changes.items():
            setattr(self, k, v)
        if changed:
            self.repaint()

    def _release(self, event):
        hit, was = self._hit(event.x, event.y), self.pressed
        self._set(pressed=None)
        if hit is not None and hit == was:
            self.invoke(self._values[hit])

    def invoke(self, value):
        if value not in self._values or value in self._disabled:
            return
        if self.variable is not None:
            self.variable.set(value)
        if self.command:
            self.command(value)

    def set_enabled(self, value, enabled):
        if (value not in self._disabled) == bool(enabled):
            return
        (self._disabled.discard if enabled else self._disabled.add)(value)
        self.repaint()

    def theme_changed(self):
        self.repaint()

    def repaint(self):
        if not self.winfo_exists():
            return
        px, c = theme.px, theme.color
        w = max(self.winfo_width(), int(self.cget("width")))
        h = int(self.cget("height"))
        self.configure(bg=c(self.bg))
        self.delete("all")
        photos = [_rounded_photo(self, w, h, px(theme.RADIUS), c("SEG"), margin=self.margin, under=c(self.bg))]
        self.create_image(0, 0, image=photos[0], anchor="nw")
        selected = self.variable.get() if self.variable is not None else None
        margin = self.margin
        inner_r = px(theme.RADIUS) - self.pad  # concentric with the track
        for i, (x0, y0, x1, y1) in enumerate(self._boxes()):
            value, label = self._values[i], self._labels[i]
            disabled = value in self._disabled
            raised = (value == selected and not disabled) or i == self.pressed
            if raised or (i == self.hover and not disabled):
                # In a gapless grid the pill bleeds 1 px past its cell so the
                # track's antialiased grey edge never shows around it.
                bleed = px(1) if self.gapless else 0
                bx0, by0 = x0 - bleed, y0 - bleed
                bw = round(x1 - x0 + 2 * bleed) + 2 * margin
                bh = round(y1 - y0 + 2 * bleed) + 2 * margin
                photo = _rounded_photo(self, bw, bh, inner_r + bleed, c("BTN") if raised else c("SEG_HOVER"),
                                       None, "raised" if raised else None, margin)
                photos.append(photo)
                self.create_image(round(bx0) - margin, round(by0) - margin, image=photo, anchor="nw")
            font = self.font_raised if raised else self.font
            if self.columns:
                label = _elide(font, label, (x1 - x0) - 2 * theme.px(SEG_CELL_TEXT_PAD))
            if disabled:
                ink = c("MUTED")
            else:
                ink = c("TEXT") if raised or self.variable is None else c("SEG_TEXT")
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            icon = self.icons.get(value)
            if icon:
                # Centre icon + label as one group; the icon is drawn, not a glyph.
                left = cx - (self.icon_px + self.icon_gap + font.measure(label)) / 2
                photo = self._icon(icon, ink)
                photos.append(photo)
                self.create_image(round(left), round(cy), image=photo, anchor="w")
                self.create_text(left + self.icon_px + self.icon_gap, cy, text=label, anchor="w",
                                 font=font, fill=ink)
            else:
                self.create_text(cx, cy, text=label, font=font, fill=ink)
        self._photos = photos

    def _icon(self, kind, ink):
        n, s = self.icon_px, theme.SUPERSAMPLE

        def build():
            img = Image.new("RGBA", (n * s, n * s), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            if kind == "play":
                d.polygon([(1 * s, 0), (1 * s, n * s - 1), (n * s - 1, n * s / 2)], fill=ink)
            else:
                inset = round(n * 0.08) * s
                d.rounded_rectangle([inset, inset, n * s - 1 - inset, n * s - 1 - inset],
                                    radius=s * 1.5, fill=ink)
            return img.resize((n, n), Image.Resampling.LANCZOS)
        return _photo(self, ("icon", kind, ink, n), build)


# --- ParamPill ----------------------------------------------------------------------
class ParamPill(tk.Canvas):
    """Parameter toggle: name on the left, ON / OFF on the right.

    Same height, radius and shadow as image buttons. A click calls
    ``command``; the owner sets the shown state with ``set_state`` (or
    ``theme.set_button_state``).
    """

    def __init__(self, parent, text="", command=None, *, bg="CARD"):
        self.margin = theme.px(theme.SHADOW_MARGIN)
        super().__init__(parent, height=theme.px(theme.CONTROL_H) + 2 * self.margin,
                         width=theme.px(PILL_MIN_W), highlightthickness=0, bd=0, cursor="hand2")
        self._text, self._command, self.bg = str(text), command, bg
        self.state = None
        self._enabled = True
        self.hover = self.pressed = False
        self._elided = {}
        self.name_font = tkfont.Font(root=self._root(), font=theme.ui_font(10, medium=True))
        self.state_font = tkfont.Font(root=self._root(), font=theme.ui_font(8, medium=True))
        self.bind("<Configure>", lambda _e: self.repaint(), add="+")
        self.bind("<Enter>", lambda _e: self._set(hover=True), add="+")
        self.bind("<Leave>", lambda _e: self._set(hover=False, pressed=False), add="+")
        self.bind("<ButtonPress-1>", lambda _e: self._set(pressed=self._enabled), add="+")
        self.bind("<ButtonRelease-1>", self._release, add="+")

    def _set(self, **changes):
        if any(getattr(self, k) != v for k, v in changes.items()):
            for k, v in changes.items():
                setattr(self, k, v)
            self.repaint()

    def _release(self, event):
        was = self.pressed
        self._set(pressed=False)
        inside = 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        if was and inside:
            self.invoke()

    def invoke(self):
        if self._enabled and self._command:
            return self._command()
        return None

    def set_state(self, state):
        state = None if state in (None, "None", "") else state
        if state != self.state:
            self.state = state
            self.repaint()

    def configure(self, cnf=None, **kw):
        kw = {**(cnf or {}), **kw}
        changed = False
        if "text" in kw:
            text = str(kw.pop("text"))
            changed |= text != self._text
            self._text = text
        if "command" in kw:
            self._command = kw.pop("command")
        if "state" in kw:
            enabled = str(kw.pop("state")) != "disabled"
            changed |= enabled != self._enabled
            self._enabled = enabled
            super().configure(cursor="hand2" if enabled else "")
        result = super().configure(**kw) if kw else None
        if changed:
            self.repaint()
        return result

    config = configure

    def cget(self, key):
        if key == "text":
            return self._text
        if key == "command":
            return self._command
        if key == "state":
            return "normal" if self._enabled else "disabled"
        return super().cget(key)

    def __getitem__(self, key):
        return self.cget(key)

    def __setitem__(self, key, value):
        self.configure(**{key: value})

    def _fit_text(self, avail):
        key = (self._text, avail)
        if key not in self._elided:
            text = self._text
            if self.name_font.measure(text) > avail:
                while text and self.name_font.measure(text + ELLIPSIS) > avail:
                    text = text[:-1]
                text = text.rstrip() + ELLIPSIS
            if len(self._elided) > 32:
                self._elided.clear()
            self._elided[key] = text
        return self._elided[key]

    def theme_changed(self):
        self.repaint()

    def repaint(self):
        if not self.winfo_exists():
            return
        c, px, m = theme.color, theme.px, self.margin
        w, h = max(self.winfo_width(), int(self.cget("width"))), int(self.cget("height"))
        self.configure(bg=c(self.bg))
        self.delete("all")
        hover = self.hover and self._enabled
        if not self._enabled:
            fill, border, ink = c("BTN_DISABLED"), c("BTN_LINE"), c("MUTED")
        elif self.state == "ON":
            fill, border, ink = c("ON_HOVER") if hover else c("ON"), None, c("ON_TEXT")
        elif self.state == "OFF":
            fill, border, ink = c("OFF_HOVER") if hover else c("OFF"), None, c("OFF_TEXT")
        else:
            fill, border, ink = c("BTN_HOVER") if hover else c("BTN"), c("BTN_LINE"), c("TEXT")
        if self.pressed and self.state is None:
            fill = c("BTN_PRESSED")
        self._photo_ref = _rounded_photo(self, w, h, px(theme.RADIUS), fill, border,
                                         "raised" if self._enabled else None, m, under=c(self.bg))
        self.create_image(0, 0, image=self._photo_ref, anchor="nw")
        cy, inset = h / 2, m + px(PILL_TEXT_PAD)
        avail = w - 2 * inset
        if self.state:
            state_w = self.state_font.measure(self.state) + px(8)
            # The fill colour already shows ON / OFF: in a narrow pill the
            # name keeps its room and the state word is left out.
            if self.name_font.measure(self._text) <= avail - state_w:
                self.create_text(w - inset, cy, text=self.state, anchor="e", font=self.state_font, fill=ink)
                avail -= state_w
        self.create_text(inset, cy, text=self._fit_text(max(0, avail)), anchor="w",
                         font=self.name_font, fill=ink)


# --- Switch -------------------------------------------------------------------------
class Switch(tk.Canvas):
    """iOS-like switch (36x22 design px) bound to an optional BooleanVar."""

    def __init__(self, parent, *, variable=None, command=None, state="normal", bg="CARD"):
        super().__init__(parent, width=theme.px(SWITCH_W), height=theme.px(SWITCH_H),
                         highlightthickness=0, bd=0)
        self.variable = variable if variable is not None else tk.BooleanVar(master=self, value=False)
        self.command, self.bg = command, bg
        self._enabled = str(state) != "disabled"
        self._trace = self.variable.trace_add("write", lambda *_: self.repaint())
        self.bind("<Button-1>", lambda _e: self.toggle(), add="+")
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._apply_cursor()
        self.repaint()

    def _on_destroy(self, event):
        if event.widget is self and self._trace is not None:
            try:
                self.variable.trace_remove("write", self._trace)
            except tk.TclError:
                pass
            self._trace = None

    def _apply_cursor(self):
        super().configure(cursor="hand2" if self._enabled else "")

    def toggle(self):
        if not self._enabled:
            return
        self.variable.set(not bool(self.variable.get()))
        if self.command:
            self.command()

    def configure(self, cnf=None, **kw):
        kw = {**(cnf or {}), **kw}
        if "state" in kw:
            self._enabled = str(kw.pop("state")) != "disabled"
            self._apply_cursor()
            self.repaint()
        return super().configure(**kw) if kw else None

    config = configure

    def cget(self, key):
        if key == "state":
            return "normal" if self._enabled else "disabled"
        return super().cget(key)

    def theme_changed(self):
        self.repaint()

    def repaint(self):
        c, px = theme.color, theme.px
        w, h = px(SWITCH_W), px(SWITCH_H)
        on = bool(self.variable.get())
        track = c("SWITCH_ON") if on else c("SWITCH_OFF")
        knob = "#ffffff"

        def build():
            s = theme.SUPERSAMPLE
            img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle([0, 0, w * s - 1, h * s - 1], radius=h * s // 2, fill=track)
            inset = px(SWITCH_KNOB_INSET) * s
            k = h * s - 2 * inset
            x = (w * s - k - inset) if on else inset
            d.ellipse([x, inset, x + k, inset + k], fill=knob)
            img = img.resize((w, h), Image.Resampling.LANCZOS)
            if not self._enabled:
                img.putalpha(img.getchannel("A").point(lambda a: a * 45 // 100))
            return img
        self._photo_ref = _photo(self, ("switch", w, h, on, track, knob, self._enabled), build)
        self.configure(bg=c(self.bg))
        self.delete("all")
        self.create_image(0, 0, image=self._photo_ref, anchor="nw")


# --- VideoTag -------------------------------------------------------------------------
class VideoTag(tk.Canvas):
    """Small dark name tag over the video corner (Tk has no real transparency)."""

    def __init__(self, parent, text="", *, bg="VIDEO"):
        super().__init__(parent, width=1, height=1, highlightthickness=0, bd=0)
        self._text, self.bg = str(text), bg
        self.font = tkfont.Font(root=self._root(), font=theme.ui_font(9))
        self.repaint()

    def configure(self, cnf=None, **kw):
        kw = {**(cnf or {}), **kw}
        changed = "text" in kw and str(kw["text"]) != self._text
        if "text" in kw:
            self._text = str(kw.pop("text"))
        result = super().configure(**kw) if kw else None
        if changed:
            self.repaint()
        return result

    config = configure

    def cget(self, key):
        return self._text if key == "text" else super().cget(key)

    def theme_changed(self):
        self.repaint()

    def repaint(self):
        px, c = theme.px, theme.color
        w = self.font.measure(self._text) + 2 * px(TAG_PAD_X)
        h = self.font.metrics("linespace") + 2 * px(TAG_PAD_Y)
        if (int(super().cget("width")), int(super().cget("height"))) != (w, h):
            super().configure(width=w, height=h)
        super().configure(bg=c(self.bg))
        self.delete("all")
        self._photo_ref = _rounded_photo(self, w, h, px(TAG_RADIUS), c("TAG_BG"), under=c(self.bg))
        self.create_image(0, 0, image=self._photo_ref, anchor="nw")
        self.create_text(w / 2, h / 2, text=self._text, font=self.font, fill=c("TAG_TEXT"))


# --- StatusChip (moved from theme) -------------------------------------------------
class StatusChip(ttk.Frame):
    """A muted label, a coloured status dot and a medium-weight value."""

    def __init__(self, parent, label, color, text, *, bg="WIN", **kwargs):
        card = bg == "CARD"
        super().__init__(parent, style="Card.TFrame" if card else "TFrame", **kwargs)
        self._bg = bg
        ttk.Label(self, text=label, style="CardMuted.TLabel" if card else "Status.TLabel").pack(side="left")
        self._dot_label = ttk.Label(self, text="●", font=theme.ui_font(7),
                                    style="Card.TLabel" if card else "TLabel")
        self._dot_label.pack(side="left", padx=(theme.px(4), theme.px(2)))
        self._text_label = ttk.Label(self, text=text, style="Card.TLabel" if card else "StatusValue.TLabel")
        if card:
            self._text_label.configure(font=theme.FONT_SMALL_MEDIUM)
        self._text_label.pack(side="left")
        self.set(color, text)

    def set(self, color, text):
        """Update the semantic dot colour and displayed status text."""
        role = next((name for name in ("STATUS_OK", "STATUS_BAD", "STATUS_WARN")
                     if theme.color(name) == color), None)
        if role:
            theme.bind_colors(self._dot_label, foreground=role)
        else:
            getattr(self._dot_label, "_theme_color_roles", {}).pop("foreground", None)
            self._dot_label.configure(foreground=color)
        if str(self._text_label.cget("text")) != str(text):
            self._text_label.configure(text=text)


# --- CounterLabel --------------------------------------------------------------------
class CounterLabel(ttk.Frame):
    """``prefix`` + current (medium) + `` / total`` (muted).

    The current value is drawn on a canvas with one fixed-width cell per
    digit (the widest digit's advance), right-aligned in a slot as wide as
    the total's shape: changing digits never move, whatever the font's own
    digit widths are, and the counter never changes its requested size.
    """

    def __init__(self, parent, *, prefix=""):
        super().__init__(parent, style="TFrame")
        self._prefix = ttk.Label(self, text=prefix, style="Status.TLabel", padding=0)
        if prefix:
            self._prefix.pack(side="left")
        self._canvas = tk.Canvas(self, width=1, height=1, highlightthickness=0, bd=0, takefocus=0)
        theme.bind_colors(self._canvas, bg="WIN")
        self._canvas.pack(side="left")
        self._total = ttk.Label(self, text="", style="Status.TLabel", padding=0)
        self._total.pack(side="left")
        self._shown = (None, None)
        font = ttk.Style(self).lookup("StatusValue.TLabel", "font") or "TkDefaultFont"
        self._font = tkfont.Font(root=self._root(), font=font)
        self._digit_w = max(self._font.measure(str(d)) for d in range(10))

    def _advance(self, ch):
        return self._digit_w if ch.isdigit() else self._font.measure(ch)

    def cget(self, key):
        """``cget("text")`` gives "current / total", like a plain label would."""
        if key == "text":
            current, total = self._shown
            return f"{current} / {total}" if current is not None else ""
        return super().cget(key)

    def set(self, current, total):
        current, total = str(current), str(total)
        old_current, old_total = self._shown
        if total == old_total and current == old_current:
            return
        if total != old_total:
            self._total.configure(text=f" / {total}")
            width = sum(self._advance(ch) for ch in total) + theme.px(2)
            height = self._font.metrics("linespace")
            if (int(self._canvas.cget("width")), int(self._canvas.cget("height"))) != (width, height):
                self._canvas.configure(width=width, height=height)
        self._shown = (current, total)
        self._draw()

    def _draw(self):
        canvas, text = self._canvas, self._shown[0] or ""
        canvas.delete("all")
        x = int(canvas.cget("width")) - theme.px(2)
        y = int(canvas.cget("height")) / 2
        ink = theme.color("TEXT")
        for ch in reversed(text):
            cell = self._advance(ch)
            x -= cell
            canvas.create_text(x + cell / 2, y, text=ch, font=self._font, fill=ink, anchor="center")

    def theme_changed(self):
        self._draw()


# --- GroupedList ---------------------------------------------------------------------
class GroupedList(RoundedCard):
    """Settings-style grouped list: rows on one card with hairline separators."""

    def __init__(self, parent, *, radius=10, **kwargs):
        super().__init__(parent, radius=radius, **kwargs)
        self._rows = 0
        # Small spacer below the last row (rows are packed before it).
        self._spacer = ttk.Frame(self.inner, height=theme.px(GROUP_BOTTOM_SPACER), style="Card.TFrame")
        self._spacer.pack(side="bottom")

    def row(self, label, hint=None):
        """Add a row; returns the right-hand holder frame for its control.

        The holder carries ``.label`` (the row's ttk.Label) and ``.hint`` (the
        hint ttk.Label or None) so callers can restyle them, e.g. muted when
        the control is disabled.
        """
        px = theme.px
        if self._rows:
            line = tk.Frame(self.inner, height=1, bd=0, highlightthickness=0)
            theme.bind_colors(line, bg="LINE_SOFT")
            line.pack(fill="x", padx=(px(14), 0), before=self._spacer)
        self._rows += 1
        frame = ttk.Frame(self.inner, style="Card.TFrame")
        frame.pack(fill="x", padx=px(14), pady=px(7), before=self._spacer)
        left = ttk.Frame(frame, style="Card.TFrame")
        left.pack(side="left")
        label_widget = ttk.Label(left, text=label, style="Card.TLabel")
        label_widget.pack(side="left")
        hint_widget = None
        if hint:
            hint_widget = ttk.Label(left, text="  " + hint, style="CardMuted.TLabel")
            hint_widget.pack(side="left")
        holder = ttk.Frame(frame, style="Card.TFrame")
        holder.pack(side="right")
        holder.label, holder.hint = label_widget, hint_widget
        return holder


# --- Dropdown list for read-only comboboxes ---------------------------------------------
DROPDOWN_ROW_H = 28               # design px per item
DROPDOWN_PAD = 5                  # inset of the rows from the list's edge
DROPDOWN_GAP = 4                  # between the field and the list
DROPDOWN_RADIUS = 8
DROPDOWN_ROW_RADIUS = 5
DROPDOWN_TEXT_X = 26              # text start; the checkmark sits left of it
DROPDOWN_KEY_COLOR = "#ff00fe"    # Windows: painted transparent, giving round corners


class DropdownList:
    """The app's own list for a read-only ``ttk.Combobox`` (replaces the native popdown).

    A rounded card under the field: a rounded accent highlight follows the
    pointer and a checkmark marks the current value. Picking a value sets the
    combobox and fires ``<<ComboboxSelected>>``, so callers see no difference.
    """

    def __init__(self, combobox):
        self.cb = combobox
        self.values = [str(v) for v in combobox.tk.splitlist(combobox.cget("values"))]
        self.current = combobox.get()
        self.hover = self.values.index(self.current) if self.current in self.values else 0
        px = theme.px
        self.font = tkfont.Font(root=combobox._root(), font=theme.ui_font(10))
        self.row_h, self.pad = px(DROPDOWN_ROW_H), px(DROPDOWN_PAD)
        text_w = max([self.font.measure(v) for v in self.values] or [0])
        self.w = max(combobox.winfo_width(), text_w + px(DROPDOWN_TEXT_X) + 2 * px(12))
        self.h = len(self.values) * self.row_h + 2 * self.pad

        top = self.top = tk.Toplevel(combobox)
        top.withdraw()
        top.overrideredirect(True)
        top.transient(combobox.winfo_toplevel())
        self.round_corners = combobox._windowingsystem == "win32"
        outer = DROPDOWN_KEY_COLOR if self.round_corners else theme.color("LINE")
        if self.round_corners:
            top.attributes("-transparentcolor", DROPDOWN_KEY_COLOR)
        self.canvas = tk.Canvas(top, width=self.w, height=self.h, highlightthickness=0, bd=0, bg=outer,
                                cursor="hand2")
        self.canvas.pack()
        self._background()
        self._paint()

        x, y = combobox.winfo_rootx(), combobox.winfo_rooty() + combobox.winfo_height() + px(DROPDOWN_GAP)
        if y + self.h > combobox.winfo_screenheight():   # no room below: open above
            y = combobox.winfo_rooty() - self.h - px(DROPDOWN_GAP)
        top.geometry(f"{self.w}x{self.h}+{x}+{max(0, y)}")
        top.deiconify()
        top.lift()
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        top.bind("<ButtonPress-1>", self._on_press_anywhere)
        top.bind("<Escape>", lambda _e: self.close())
        top.bind("<Up>", lambda _e: self._move(-1))
        top.bind("<Down>", lambda _e: self._move(1))
        top.bind("<Return>", lambda _e: self.choose(self.hover))
        try:
            top.grab_set()   # a click anywhere else in the app closes the list
        except tk.TclError:
            pass
        top.focus_force()

    def _background(self):
        """Rounded card; on Windows the outside is the key colour (made transparent)."""
        px, c = theme.px, theme.color
        card = theme.rounded_image(self.w, self.h, px(DROPDOWN_RADIUS), c("CARD"), c("LINE"))
        if self.round_corners:
            # Anti-aliased edge pixels blend toward the window colour, fully
            # outside pixels take the key colour (no pink fringe).
            image = Image.alpha_composite(Image.new("RGBA", card.size, c("WIN")), card)
            outside = card.getchannel("A").point(lambda a: 255 if a == 0 else 0)
            image.paste(DROPDOWN_KEY_COLOR, mask=outside)
        else:
            image = Image.alpha_composite(Image.new("RGBA", card.size, c("CARD")), card)
        self._bg = ImageTk.PhotoImage(image, master=self.canvas)
        self.canvas.create_image(0, 0, image=self._bg, anchor="nw", tags="bg")

    def _paint(self):
        px, c = theme.px, theme.color
        self.canvas.delete("row")
        for i, value in enumerate(self.values):
            y0 = self.pad + i * self.row_h
            ink = c("TEXT")
            if i == self.hover:
                self._row_img = _rounded_photo(self.canvas, self.w - 2 * self.pad, self.row_h,
                                               px(DROPDOWN_ROW_RADIUS), c("ACCENT"), under=c("CARD"))
                self.canvas.create_image(self.pad, y0, image=self._row_img, anchor="nw", tags="row")
                ink = "#ffffff"
            cy = y0 + self.row_h / 2
            if value == self.current:
                x0 = self.pad + px(8)
                self.canvas.create_line(x0, cy, x0 + px(3.5), cy + px(3.5), x0 + px(10), cy - px(4),
                                        fill=ink, width=max(1, px(1.6)), capstyle="round",
                                        joinstyle="round", tags="row")
            self.canvas.create_text(self.pad + px(DROPDOWN_TEXT_X), cy, text=value, anchor="w",
                                    font=self.font, fill=ink, tags="row")

    def _row_at(self, y):
        i = int((y - self.pad) // self.row_h)
        return i if 0 <= i < len(self.values) else None

    def _on_motion(self, event):
        i = self._row_at(event.y)
        if i is not None and i != self.hover:
            self.hover = i
            self._paint()

    def _move(self, step):
        self.hover = max(0, min(len(self.values) - 1, self.hover + step))
        self._paint()

    def _on_release(self, event):
        i = self._row_at(event.y)
        if i is not None:
            self.choose(i)

    def _on_press_anywhere(self, event):
        # With the grab, presses outside the list arrive here too: close.
        if event.widget is not self.canvas or not (0 <= event.x < self.w and 0 <= event.y < self.h):
            self.close()

    def choose(self, index):
        value = self.values[index]
        self.close()
        if value != self.current:
            self.cb.set(value)
            self.cb.event_generate("<<ComboboxSelected>>")

    def close(self):
        top, self.top = self.top, None
        if top is None:
            return
        try:
            top.grab_release()
            top.destroy()
            self.cb.focus_set()
        except tk.TclError:
            pass


def attach_dropdown(combobox):
    """Open the app's DropdownList instead of the native list for read-only comboboxes."""
    if getattr(combobox, "_tt_dropdown", False):
        return
    combobox._tt_dropdown = True

    def open_list(_event=None):
        state = combobox.state()
        if "readonly" not in state or "disabled" in state:
            return None   # editable / disabled: ttk's own behaviour
        if combobox.tk.splitlist(combobox.cget("values")):
            DropdownList(combobox)
        return "break"

    combobox.bind("<Button-1>", open_list)
    combobox.bind("<Down>", open_list)
    combobox.bind("<space>", open_list)
