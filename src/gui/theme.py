"""Central UI palette, fonts, and ttk styling on plain ttk ``clam``.

The look follows ``demos/design_lab.py``: a grey window, white cards with a
soft shadow, and rounded image buttons. Rounded shapes are ttk *image
elements* generated with Pillow; every appearance switch registers a new,
uniquely named set of elements (one "generation") and keeps that
generation's PhotoImages alive until the next switch.

Colours and fonts are module globals that change on a theme switch, so read
them as ``theme.X`` at call time, never with ``from gui.theme import X``.
Canvas widgets that paint themselves define ``theme_changed()``; it is called
after every switch (see ``_refresh_colors``).
"""

import logging
import sys
import tkinter.font as tkfont
from collections import OrderedDict
from tkinter import TclError, ttk

from PIL import Image, ImageDraw, ImageFilter, ImageTk

from gui.native_title_bar import apply_title_bar, round_popup

logger = logging.getLogger(__name__)

# --- Geometry (px before DPI scaling; convert with px()) -----------------------
# Buttons and segmented tracks share one height and radius; a pill inside a
# track uses RADIUS - SEG_PAD so the two curves stay concentric.
CONTROL_H = 28        # visible height of buttons and segmented tracks
RADIUS = 8            # corner radius of buttons, fields and tracks
SEG_PAD = 2           # gap between a track and the pill inside it
CARD_RADIUS = 12      # panel corner radius
SHADOW_MARGIN = 4     # transparent room around raised shapes for the shadow
TOOLBAR_GAP = 8       # visible gap between toolbar controls
SUPERSAMPLE = 4       # antialiasing factor for generated images
# ttk tiles (does not stretch) the middle of an image element. A large source
# image keeps the tile count low; tiny images made 60 buttons take ~1.9 s.
ELEMENT_IMAGE_PX = 160
# Shadows as (y offset px, blur sigma px, alpha 0-255) layers.
DEPTH = {"raised": ((0, .5, 14), (1, 1.0, 20)), "card": ((0, .5, 10), (1, 1.5, 14))}
# Scrollbar thumb: visible radius and the transparent inset around it.
SCROLL_THUMB_RADIUS = 3
SCROLL_THUMB_INSET = 3
PROGRESS_THICKNESS = 6
INDICATOR_SIZE = 16   # check / radio indicator box
INDICATOR_GAP = 7     # space between the indicator and its text
PROGRESS_BLOCK_W = 80  # moving block of an indeterminate progress bar
# Pillow image cache size (entries); generated images are small.
IMAGE_CACHE_SIZE = 512

FONT_FAMILY_CANDIDATES = ("Segoe UI Variable Text", "Segoe UI")                   # else TkDefaultFont's family
FONT_MEDIUM_CANDIDATES = ("Segoe UI Variable Text Semibold", "Segoe UI Semibold")  # else family + "bold"

# Kept for timelines: parameter ticks are 1 px and dashed so a parameter OFF
# can never be mistaken for a touch OFF.
TL_PARAM_MARK_WIDTH = 1
TL_PARAM_MARK_DASH = (3, 2)

# --- Palettes ---------------------------------------------------------------
# Lab roles are copied verbatim from demos/design_lab.py; the app roles below
# them are retuned to sit on the new surfaces.
LIGHT_PALETTE = dict(
    WIN="#f5f5f7", CARD="#ffffff", LINE="#d2d2d7", LINE_SOFT="#e5e5ea",
    TEXT="#1d1d1f", MUTED="#6e6e73", ACCENT="#0071e3", ACCENT_HOVER="#0077ed",
    BTN="#ffffff", BTN_HOVER="#f7f7f9", BTN_LINE="#dadadf", BTN_PRESSED="#e6e6ea", BTN_DISABLED="#f0f0f2",
    SEG="#e8e8ed", SEG_HOVER="#dedee4", SEG_TEXT="#3a3a3c", TRACK="#ececf0", VIDEO="#151517", DIAGRAM="#ffffff", DIAGRAM_LINE="#d2d2d7",
    ON="#cdeed6", ON_HOVER="#bfe7cb", ON_TEXT="#1b6b37", ON_MARK="#2f9e5a",
    OFF="#fbd9d5", OFF_HOVER="#f7cbc6", OFF_TEXT="#a52a1f", OFF_MARK="#d9493d",
    NOTE="#8e5cc2", NOTE_TEXT="#3a3a3c", SWITCH_OFF="#d1d1d6", SWITCH_ON="#0071e3",
    TAG_BG="#2b2b2e", TAG_TEXT="#d6d6db",
    # App roles.
    TL_DURING="#e4f5e9", TL_UNAVAILABLE="#dcdce1", TL_UNAVAILABLE_MARK="#aeaeb2",
    TL_PARAM_ON_MARK="#6fbf8a", TL_PARAM_OFF_MARK="#e88a80",
    STATUS_WARN="#d08a00", DOT_ONSET="#21a453", DOT_OFFSET="#e2483d", SPECIAL_ZONE_DOT="#21a453",
    TOUCH_START="#0071e3", TOUCH_END="#d9493d",
)
DARK_PALETTE = dict(
    WIN="#1c1c1e", CARD="#2c2c2e", LINE="#48484a", LINE_SOFT="#38383a",
    TEXT="#f5f5f7", MUTED="#98989d", ACCENT="#0a84ff", ACCENT_HOVER="#2b95ff",
    BTN="#3a3a3c", BTN_HOVER="#444446", BTN_LINE="#4a4a4c", BTN_PRESSED="#505052", BTN_DISABLED="#2f2f31",
    SEG="#232325", SEG_HOVER="#2e2e30", SEG_TEXT="#d1d1d6", TRACK="#3a3a3c", VIDEO="#0d0d0e", DIAGRAM="#ffffff", DIAGRAM_LINE="#d2d2d7",
    ON="#21452f", ON_HOVER="#285338", ON_TEXT="#8fe0a8", ON_MARK="#4cc77a",
    OFF="#4a2723", OFF_HOVER="#58302b", OFF_TEXT="#ff9d92", OFF_MARK="#ff6b5e",
    NOTE="#c79bf2", NOTE_TEXT="#d1d1d6", SWITCH_OFF="#48484a", SWITCH_ON="#0a84ff",
    TAG_BG="#2b2b2e", TAG_TEXT="#d6d6db",
    # App roles. Diagram dots stay as in light: the diagram stays white.
    TL_DURING="#1b3324", TL_UNAVAILABLE="#262628", TL_UNAVAILABLE_MARK="#5a5a5e",
    TL_PARAM_ON_MARK="#3f9e63", TL_PARAM_OFF_MARK="#c9655b",
    STATUS_WARN="#e0b43c", DOT_ONSET="#21a453", DOT_OFFSET="#e2483d", SPECIAL_ZONE_DOT="#21a453",
    TOUCH_START="#0a84ff", TOUCH_END="#ff6b5e",
)
PALETTES = {"light": LIGHT_PALETTE, "dark": DARK_PALETTE}

# Legacy role -> new role (or a literal colour). Derived whenever a palette is
# applied so unmigrated code keeps working; new code uses the new names.
LEGACY_ALIASES = {
    "SURFACE": "WIN", "SURFACE_ALT": "TRACK", "TOOLBAR_BG": "WIN", "VIDEO_BG": "VIDEO",
    "BORDER": "LINE", "TEXT_MUTED": "MUTED", "NEUTRAL": "BTN", "ON_GREEN": "ON", "OFF_RED": "OFF",
    "DIAGRAM_BG": "DIAGRAM", "DISABLED_BG": "BTN_DISABLED", "DISABLED_FG": "MUTED",
    "TL_EMPTY": "TRACK", "TL_ON": "ON", "TL_OFF": "OFF", "TL_OUTLINE": "LINE_SOFT",
    "TL_ONSET_MARK": "ON_MARK", "TL_OFFSET_MARK": "OFF_MARK", "TL_NOTE_MARK": "NOTE",
    "PLAYHEAD": "ACCENT", "STATUS_OK": "ON_MARK", "STATUS_BAD": "OFF_MARK",
    "SELECTION_BG": "ACCENT", "SELECTION_FG": "#ffffff",
}


def _resolved(palette):
    """Palette plus its legacy aliases."""
    full = dict(palette)
    for legacy, target in LEGACY_ALIASES.items():
        full[legacy] = target if target.startswith("#") else palette[target]
    return full


# --- Runtime state (resolved by init_style; read as theme.X) -------------------
_appearance = "light"
globals().update(_resolved(LIGHT_PALETTE))
SCALE = 1.0
FONT_FAMILY = FONT_FAMILY_CANDIDATES[-1] if sys.platform == "win32" else "TkDefaultFont"
FONT_MEDIUM_FAMILY = None
FONT_BASE = (FONT_FAMILY, 10)
FONT_SMALL = (FONT_FAMILY, 9)
FONT_MEDIUM = (FONT_FAMILY, 10, "bold")
FONT_SMALL_MEDIUM = (FONT_FAMILY, 9, "bold")
FONT_SECTION = (FONT_FAMILY, 8, "bold")
FONT_TITLE = (FONT_FAMILY, 12, "bold")
FONT_BOLD = FONT_MEDIUM
FONT_LINK = FONT_BASE
FONT_SUBTITLE = FONT_SMALL
FONT_DIALOG_TITLE = FONT_TITLE

_root = None
_generation = 0
_images = {}        # this generation's PhotoImages, keyed by image spec
_prev_images = {}   # previous generation, alive until the next switch
_image_cache = OrderedDict()
_shadow_cache = OrderedDict()
_dot_cache = {}


# --- Small helpers --------------------------------------------------------------
def current_appearance():
    return _appearance


def px(value):
    """Scale a design pixel value to device pixels (at least 1 for positive input)."""
    scaled = round(value * SCALE)
    return max(1, scaled) if value > 0 else scaled


def ui_font(size, medium=False):
    """Font tuple: regular, or the semibold cut used for medium text."""
    if medium:
        if FONT_MEDIUM_FAMILY:
            return (FONT_MEDIUM_FAMILY, size)
        return (FONT_FAMILY, size, "bold")
    return (FONT_FAMILY, size)


def color(role):
    return globals()[role]


def toolbar_padx():
    """Gap between image buttons so the *visible* gap is TOOLBAR_GAP."""
    return max(0, px(TOOLBAR_GAP) - 2 * px(SHADOW_MARGIN))


def _resolve_fonts(root):
    global FONT_FAMILY, FONT_MEDIUM_FAMILY, FONT_BASE, FONT_SMALL, FONT_MEDIUM
    global FONT_SMALL_MEDIUM, FONT_SECTION, FONT_TITLE, FONT_BOLD, FONT_LINK
    global FONT_SUBTITLE, FONT_DIALOG_TITLE
    families = set(tkfont.families(root))
    default_family = tkfont.nametofont("TkDefaultFont", root=root).actual("family")
    FONT_FAMILY = next((f for f in FONT_FAMILY_CANDIDATES if f in families), default_family)
    FONT_MEDIUM_FAMILY = next((f for f in FONT_MEDIUM_CANDIDATES if f in families), None)
    FONT_BASE, FONT_SMALL = ui_font(10), ui_font(9)
    FONT_MEDIUM, FONT_SMALL_MEDIUM = ui_font(10, True), ui_font(9, True)
    FONT_SECTION, FONT_TITLE = ui_font(8, True), ui_font(12, True)
    FONT_BOLD, FONT_LINK = FONT_MEDIUM, FONT_BASE
    FONT_SUBTITLE, FONT_DIALOG_TITLE = FONT_SMALL, FONT_TITLE
    # Plain Tk widgets that set no font follow the UI family too.
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            tkfont.nametofont(name, root=root).configure(family=FONT_FAMILY)
        except TclError:
            pass


def _cache_put(cache, key, value):
    cache[key] = value
    if len(cache) > IMAGE_CACHE_SIZE:
        cache.popitem(last=False)
    return value


# --- Image generation -----------------------------------------------------------
def _shadow(w, h, radius, depth, margin):
    """Downsampled shadow-only layer; shared by every fill colour."""
    key = (w, h, radius, depth, margin, SCALE)
    if key in _shadow_cache:
        _shadow_cache.move_to_end(key)
        return _shadow_cache[key]
    s = SUPERSAMPLE
    img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    x0, y0, x1, y1 = margin * s, margin * s, (w - margin) * s - 1, (h - margin) * s - 1
    for dy, sigma, alpha in DEPTH[depth]:
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        off = round(dy * SCALE * s)
        ImageDraw.Draw(layer).rounded_rectangle([x0, y0 + off, x1, y1 + off], radius=radius * s,
                                                fill=(0, 0, 0, alpha))
        img = Image.alpha_composite(img, layer.filter(ImageFilter.GaussianBlur(sigma * SCALE * s)))
    return _cache_put(_shadow_cache, key, img.resize((w, h), Image.Resampling.LANCZOS))


def rounded_image(w, h, radius, fill, border=None, depth=None, margin=0, under=None):
    """Antialiased rounded rectangle, optionally with a 1 px border and a shadow.

    All sizes are device pixels (already passed through px()); SCALE only
    scales the shadow offsets and blur. ``margin`` px of transparent room
    surround the shape so the shadow can fade out. ``under`` (a colour)
    composites the result onto that background, giving a fully opaque image:
    Tk draws partially transparent photos through a slow software blend, so
    opaque images make image buttons about twice as fast to paint. Results
    are cached.
    """
    w, h, radius, margin = int(w), int(h), int(radius), int(margin)
    if under:
        key = (w, h, radius, fill, border, depth, margin, SCALE, under)
        if key not in _image_cache:
            base = Image.new("RGBA", (w, h), under)
            _cache_put(_image_cache, key, Image.alpha_composite(
                base, rounded_image(w, h, radius, fill, border, depth, margin)))
        _image_cache.move_to_end(key)
        return _image_cache[key]
    key = (w, h, radius, fill, border, depth, margin, SCALE)
    if key in _image_cache:
        _image_cache.move_to_end(key)
        return _image_cache[key]
    s = SUPERSAMPLE
    shape = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    x0, y0, x1, y1 = margin * s, margin * s, (w - margin) * s - 1, (h - margin) * s - 1
    r = radius * s
    d = ImageDraw.Draw(shape)
    if border:
        d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=border)
        d.rounded_rectangle([x0 + s, y0 + s, x1 - s, y1 - s], radius=max(0, r - s), fill=fill)
    else:
        d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill)
    shape = shape.resize((w, h), Image.Resampling.LANCZOS)
    if depth:
        shape = Image.alpha_composite(_shadow(w, h, radius, depth, margin), shape)
    return _cache_put(_image_cache, key, shape)


def _photo(key, factory):
    """This generation's PhotoImage for ``key`` (built once per generation)."""
    if key not in _images:
        _images[key] = ImageTk.PhotoImage(factory(), master=_root)
    return _images[key]


def _rounded_photo(fill, border, radius, depth=None, margin=0, size=ELEMENT_IMAGE_PX, under=None):
    """(PhotoImage, slice px) for an image element; ``radius`` in design px."""
    r = px(radius)
    photo = _photo(("rounded", size, r, fill, border, depth, margin, under),
                   lambda: rounded_image(size, size, r, fill, border, depth, margin, under))
    return photo, r + 2 + margin


def _chevron_photo(ink):
    def build():
        s, w, h = SUPERSAMPLE, px(18), px(14)
        img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
        cx, cy, a = w * s / 2 - s * 3, h * s / 2, px(4) * s
        ImageDraw.Draw(img).line([(cx - a, cy - a / 2), (cx, cy + a / 2), (cx + a, cy - a / 2)],
                                 fill=ink, width=max(1, int(1.6 * s * SCALE)), joint="curve")
        return img.resize((w, h), Image.Resampling.LANCZOS)
    return _photo(("chevron", ink), build)


def _element(style, name, normal, states=(), slice_px=None, **extra):
    """Uniquely named image element: large source image, small minimum size."""
    if slice_px is None:
        slice_px = px(RADIUS) + 2
    elem = f"tt{_generation}.{name}"
    options = dict(border=slice_px, padding=0, sticky="nsew",
                   width=2 * slice_px, height=2 * slice_px)
    options.update(extra)
    # padding=0: an image element otherwise uses its border as inner padding.
    style.element_create(elem, "image", normal, *states, **options)
    return elem


# --- Styles -----------------------------------------------------------------------
def _image_button(style, name, normal, hover, pressed, disabled, fg, *, border=None, bg=None):
    """Register ``name`` (e.g. 'Tool.TButton') as a rounded image button."""
    border = BTN_LINE if border is None else border
    margin = px(SHADOW_MARGIN)
    background = bg or WIN
    # Composited onto the style's background: opaque images paint fast, which
    # is why buttons on cards need the Card.* styles.
    made = {k: _rounded_photo(c, border or None, RADIUS, None if k == "d" else "raised", margin,
                              under=background)
            for k, c in dict(n=normal, h=hover, p=pressed, d=disabled).items()}
    elem = _element(style, name + ".bg", made["n"][0],
                    (("disabled", made["d"][0]), ("pressed", made["p"][0]), ("active", made["h"][0])),
                    slice_px=made["n"][1])
    style.layout(name, [(elem, {"sticky": "nsew", "children": [
        ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})])
    font = ui_font(10, medium=True)
    # Pad so the visible pill (widget minus shadow margin) is exactly CONTROL_H.
    line = tkfont.Font(root=_root, font=font).metrics("linespace")
    pad_y = max(0, (px(CONTROL_H) + 2 * margin - line) // 2)
    style.configure(name, foreground=fg, background=background, width=0, anchor="center",
                    font=font, padding=(px(12) + margin, pad_y), focuscolor=background)
    style.map(name, foreground=[("disabled", MUTED)], background=[("active", background)])


def _button_styles(style):
    for prefix, bg in (("", WIN), ("Card.", CARD)):
        _image_button(style, prefix + "Tool.TButton", BTN, BTN_HOVER, BTN_PRESSED, BTN_DISABLED, TEXT, bg=bg)
        _image_button(style, prefix + "Primary.TButton", ACCENT, ACCENT_HOVER, ACCENT, BTN_DISABLED,
                      "#ffffff", border=ACCENT, bg=bg)
        _image_button(style, prefix + "StateNeutral.TButton", BTN, BTN_HOVER, BTN_PRESSED, BTN_DISABLED,
                      TEXT, bg=bg)
        _image_button(style, prefix + "StateOn.TButton", ON, ON_HOVER, ON_HOVER, BTN_DISABLED, ON_TEXT,
                      border=ON, bg=bg)
        _image_button(style, prefix + "StateOff.TButton", OFF, OFF_HOVER, OFF_HOVER, BTN_DISABLED, OFF_TEXT,
                      border=OFF, bg=bg)
    _image_button(style, "TButton", BTN, BTN_HOVER, BTN_PRESSED, BTN_DISABLED, TEXT)


def _field_styles(style):
    """Rounded Entry / Combobox with an accent ring on focus and a chevron arrow."""
    arrow = f"tt{_generation}.Combobox.chevron"
    style.element_create(arrow, "image", _chevron_photo(MUTED), ("disabled", _chevron_photo(LINE)),
                         ("active", _chevron_photo(TEXT)), sticky="")
    for prefix, bg in (("", WIN), ("Card.", CARD)):
        normal = _rounded_photo(BTN, LINE, RADIUS - 1, under=bg)[0]
        focus = _rounded_photo(BTN, ACCENT, RADIUS - 1, under=bg)[0]
        disabled = _rounded_photo(BTN_DISABLED, LINE_SOFT, RADIUS - 1, under=bg)[0]
        for widget in ("Entry", "Combobox"):
            name = f"{prefix}T{widget}"
            elem = _element(style, f"{name}.field", normal, (("disabled", disabled), ("focus", focus)))
            inner = [(arrow, {"side": "right", "sticky": "ns"})] if widget == "Combobox" else []
            inner.append((f"{widget}.padding", {"sticky": "nsew", "children": [
                (f"{widget}.textarea", {"sticky": "nsew"})]}))
            style.layout(name, [(elem, {"sticky": "nsew", "children": inner})])
            style.configure(name, fieldbackground=BTN, foreground=TEXT, background=bg,
                            insertcolor=TEXT, selectbackground=ACCENT, selectforeground="#ffffff",
                            padding=(px(8), px(4)))
            style.map(name, fieldbackground=[("disabled", BTN_DISABLED), ("readonly", BTN)],
                      foreground=[("disabled", MUTED), ("readonly", TEXT)],
                      background=[("active", bg)],
                      # A focused readonly combobox would otherwise paint its text selected.
                      selectbackground=[("readonly", BTN)],
                      selectforeground=[("readonly", TEXT)])
    style.configure("ComboboxPopdownFrame", background=CARD, relief="flat", borderwidth=0)
    # The dropdown list is a plain Tk Listbox in its own popup window.
    for option, value in _listbox_options().items():
        _root.option_add(f"*TCombobox*Listbox.{option}", value)


def _listbox_options():
    return {"background": CARD, "foreground": TEXT, "selectBackground": ACCENT,
            # TkTextFont matches the text in the combobox field itself.
            "selectForeground": "#ffffff", "font": "TkTextFont", "borderWidth": 0,
            # The hairline comes from the highlight ring: the popdown frame's own
            # "solid" border is always black.
            # Windows 11 draws the hairline and rounded corners itself (round_popup).
            "relief": "flat", "highlightThickness": 0 if sys.platform == "win32" else 1,
            "highlightBackground": LINE,
            "highlightColor": LINE, "activeStyle": "none"}


def _scrollbar_styles(style):
    r, inset = px(SCROLL_THUMB_RADIUS), px(SCROLL_THUMB_INSET)
    slice_px = r + inset + 1

    def thumb(fill):
        return _photo(("thumb", fill, r, inset, WIN),
                      lambda: rounded_image(ELEMENT_IMAGE_PX, ELEMENT_IMAGE_PX, r, fill, margin=inset, under=WIN))

    for orient in ("Vertical", "Horizontal"):
        name = f"{orient}.TScrollbar"
        elem = _element(style, f"{orient}.Scrollbar.thumb", thumb(LINE),
                        (("pressed", thumb(MUTED)), ("active", thumb(MUTED))), slice_px=slice_px)
        style.layout(name, [(f"{orient}.Scrollbar.trough", {"sticky": "nsew", "children": [
            (elem, {"expand": "1", "sticky": "nsew"})]})])
        style.configure(name, troughcolor=WIN, background=WIN, bordercolor=WIN,
                        lightcolor=WIN, darkcolor=WIN, gripcount=0, arrowsize=2 * slice_px)


def _progress_styles(style):
    h = px(PROGRESS_THICKNESS)
    r = h // 2

    def bar(fill, under):
        # Opaque: partially transparent element edges left stray pixels here.
        return _photo(("bar", fill, h, under), lambda: rounded_image(ELEMENT_IMAGE_PX, h, r, fill, under=under))

    trough = _element(style, "Horizontal.Progressbar.trough", bar(TRACK, WIN), slice_px=(r + 1, r),
                      width=2 * r + 2, height=h, sticky="ew")
    # The pbar's requested width is the moving block in indeterminate mode.
    pbar = _element(style, "Horizontal.Progressbar.pbar", bar(ACCENT, TRACK), slice_px=(r + 1, r),
                    width=px(PROGRESS_BLOCK_W), height=h, sticky="ew")
    style.layout("Horizontal.TProgressbar", [(trough, {"sticky": "nsew", "children": [
        (pbar, {"side": "left", "sticky": "ns"})]})])
    style.configure("Horizontal.TProgressbar", troughcolor=TRACK, background=ACCENT,
                    bordercolor=TRACK, lightcolor=ACCENT, darkcolor=ACCENT, thickness=h)


def _text_styles(style):
    style.configure(".", background=WIN, foreground=TEXT, font=FONT_BASE, bordercolor=LINE,
                    lightcolor=CARD, darkcolor=CARD, troughcolor=TRACK, selectbackground=ACCENT,
                    selectforeground="#ffffff", fieldbackground=BTN, insertcolor=TEXT,
                    focuscolor=ACCENT)
    style.configure("TFrame", background=WIN)
    style.configure("Card.TFrame", background=CARD)
    style.configure("TLabel", background=WIN, foreground=TEXT)
    style.configure("Card.TLabel", background=CARD, foreground=TEXT)
    style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED, font=FONT_SMALL)
    style.configure("CardHead.TLabel", background=CARD, foreground=TEXT, font=FONT_SMALL_MEDIUM)
    style.configure("Card.Link.TLabel", background=CARD, foreground=ACCENT, font=FONT_BASE)
    style.configure("Muted.TLabel", background=WIN, foreground=MUTED)
    style.configure("Status.TLabel", background=WIN, foreground=MUTED, font=FONT_SMALL)
    style.configure("StatusValue.TLabel", background=WIN, foreground=TEXT, font=FONT_SMALL_MEDIUM)
    style.configure("Section.TLabel", background=WIN, foreground=MUTED, font=FONT_SECTION)
    style.configure("Title.TLabel", background=WIN, foreground=TEXT, font=FONT_TITLE)
    style.configure("Link.TLabel", background=WIN, foreground=ACCENT, font=FONT_LINK)
    _separator_style(style)
    style.configure("TLabelframe", background=WIN, bordercolor=LINE_SOFT, lightcolor=WIN, darkcolor=WIN)
    style.configure("TLabelframe.Label", background=WIN, foreground=TEXT, font=FONT_MEDIUM)
    _indicator_styles(style)


def _indicator_photo(kind, fill, border, mark, bg):
    """Check box or radio circle (with its trailing gap) on ``bg``, opaque."""
    def build():
        s, n, gap = SUPERSAMPLE, px(INDICATOR_SIZE), px(INDICATOR_GAP)
        img = Image.new("RGBA", ((n + gap) * s, n * s), bg)
        d = ImageDraw.Draw(img)
        box = [0, 0, n * s - 1, n * s - 1]
        inner = [s, s, n * s - 1 - s, n * s - 1 - s]
        radius = n * s // 2 if kind == "radio" else px(4) * s
        d.rounded_rectangle(box, radius=radius, fill=border or fill)
        if border:
            d.rounded_rectangle(inner, radius=max(0, radius - s), fill=fill)
        if mark and kind == "radio":
            c, k = n * s / 2, n * s * 0.19
            d.ellipse([c - k, c - k, c + k, c + k], fill=mark)
        elif mark:
            pts = [(n * s * .26, n * s * .52), (n * s * .43, n * s * .68), (n * s * .74, n * s * .34)]
            d.line(pts, fill=mark, width=max(s, round(1.8 * SCALE * s)), joint="curve")
        return img.resize((n + gap, n), Image.Resampling.LANCZOS)
    return _photo(("indicator", kind, fill, border, mark, bg), build)


def _indicator_styles(style):
    """Image check boxes and radio circles (clam's own draw an X / tiny dot)."""
    for kind, widget in (("check", "Checkbutton"), ("radio", "Radiobutton")):
        for prefix, bg in (("", WIN), ("Card.", CARD)):
            name = f"{prefix}T{widget}"
            off = _indicator_photo(kind, BTN, LINE, None, bg)
            off_hover = _indicator_photo(kind, BTN_HOVER, MUTED, None, bg)
            on = _indicator_photo(kind, ACCENT, None, "#ffffff", bg)
            on_hover = _indicator_photo(kind, ACCENT_HOVER, None, "#ffffff", bg)
            off_dis = _indicator_photo(kind, BTN_DISABLED, LINE_SOFT, None, bg)
            on_dis = _indicator_photo(kind, BTN_DISABLED, LINE_SOFT, MUTED, bg)
            elem = f"tt{_generation}.{name}.indicator"
            style.element_create(elem, "image", off, ("disabled selected", on_dis), ("disabled", off_dis),
                                 ("active selected", on_hover), ("selected", on),
                                 ("active", off_hover), sticky="")
            style.layout(name, [(f"{widget}.padding", {"sticky": "nsew", "children": [
                (elem, {"side": "left", "sticky": ""}),
                (f"{widget}.label", {"side": "left", "sticky": "nsew"})]})])
            style.configure(name, background=bg, foreground=TEXT, focuscolor=bg, padding=(0, px(2)))
            style.map(name, background=[("active", bg)], foreground=[("disabled", MUTED)])


def _separator_style(style):
    """A flat LINE_SOFT hairline (the default separator is a 3D groove)."""
    line = _photo(("flat", LINE_SOFT), lambda: Image.new("RGBA", (4, 4), LINE_SOFT))
    elem = _element(style, "TSeparator.line", line, slice_px=0, width=1, height=1)
    style.layout("TSeparator", [(elem, {"sticky": "nsew"})])
    style.configure("TSeparator", background=LINE_SOFT)


def init_style(root, appearance="light"):
    """Attach the selected appearance to an existing ``tk.Tk`` root."""
    global _root, SCALE
    _root = root
    _dot_cache.clear()   # its photos belong to the previous root's interpreter
    style = ttk.Style(root)
    style.theme_use("clam")  # clam honours colours and image elements
    SCALE = root.winfo_fpixels("1i") / 96.0
    _resolve_fonts(root)
    bind_colors(root, bg="WIN")
    try:
        from gui.app_icon import apply_app_icon
        apply_app_icon(root)   # the TT icon on every window (and the taskbar)
    except Exception:
        logger.debug("app icon unavailable", exc_info=True)
    root.bind_all("<Map>", _on_window_map, add="+")
    apply_appearance(root, style, appearance)
    return style


def apply_appearance(root, style, appearance):
    """Switch every ttk style and explicitly coloured widget together."""
    global _appearance, _generation, _images, _prev_images, _root
    if _root is None:
        _root = root
    _appearance = appearance if appearance in PALETTES else "light"
    globals().update(_resolved(PALETTES[_appearance]))
    _generation += 1
    _prev_images, _images = _images, {}
    _text_styles(style)
    _button_styles(style)
    _field_styles(style)
    _scrollbar_styles(style)
    _progress_styles(style)
    _refresh_colors(root)


# --- Colour binding and the theme-change walk ----------------------------------
def bind_colors(widget, **roles):
    """Remember explicit colour roles for a Tk widget, including future dialogs."""
    widget._theme_color_roles = {**getattr(widget, "_theme_color_roles", {}), **roles}
    widget.configure(**{option: globals()[role] for option, role in roles.items()})
    return widget


def _refresh_colors(root):
    """Recolour bound widgets, sync title bars, then call ``theme_changed()``."""
    stack = [root]
    while stack:
        widget = stack.pop()
        try:
            roles = getattr(widget, "_theme_color_roles", None)
            if roles:
                widget.configure(**{option: globals()[role] for option, role in roles.items()})
            _sync_title_bar(widget)
            if getattr(widget, "winfo_class", lambda: "")() == "TCombobox":
                _recolor_popdown(widget)
            hook = getattr(widget, "theme_changed", None)
            if callable(hook):
                hook()
            stack.extend(widget.winfo_children())
        except TclError:
            # A widget destroyed mid-walk; nothing left to recolour.
            continue
        except Exception:
            logger.exception("theme refresh failed for %s", widget)


def _recolor_popdown(combobox):
    """Existing combobox popdown lists do not see option_add changes."""
    listbox = f"{combobox}.popdown.f.l"
    if int(combobox.tk.call("winfo", "exists", listbox)):
        options = _listbox_options()
        combobox.tk.call(listbox, "configure",
                         "-background", options["background"], "-foreground", options["foreground"],
                         "-selectbackground", options["selectBackground"],
                         "-selectforeground", options["selectForeground"],
                         "-highlightbackground", options["highlightBackground"],
                         "-highlightcolor", options["highlightColor"])


def _sync_title_bar(widget):
    if widget.winfo_toplevel() is widget:
        apply_title_bar(widget, dark=_appearance == "dark", background=WIN, foreground=TEXT)


def _on_window_map(event):
    # Map fires for child controls too; only root/Toplevel windows have captions.
    # Tcl-owned popups (for example a combobox list) have no Python widget object.
    if isinstance(event.widget, str):
        if event.widget.endswith(".popdown"):
            # A combobox list: rounded corners and a hairline border, drawn by
            # the window manager (Windows 11), like a native menu.
            try:
                round_popup(int(_root.tk.call("winfo", "id", event.widget)), LINE)
            except (TclError, AttributeError, ValueError):   # gone, or no root yet
                pass
        return
    if getattr(event.widget, "winfo_class", lambda: "")() == "TCombobox":
        from gui.widgets import attach_dropdown   # widgets imports theme
        attach_dropdown(event.widget)
        return
    _sync_title_bar(event.widget)


def set_button_state(widget, state):
    """Show an ON, OFF, or unset (None/"None"/"") state on a button.

    Widgets with ``set_state`` (ParamPill) handle it themselves; ttk buttons
    swap their ``State*.TButton`` style, keeping a ``Card.`` prefix.
    """
    normalized = None if state in (None, "None", "") else state
    if hasattr(widget, "set_state"):
        widget.set_state(normalized)
        return
    style_name = {"ON": "StateOn.TButton", "OFF": "StateOff.TButton"}.get(normalized, "StateNeutral.TButton")
    current = str(widget.cget("style"))
    if current.startswith("Card."):
        style_name = "Card." + style_name
    # Reapplying an unchanged style still queues native repaint work.
    if current != style_name:
        widget.configure(style=style_name)


def dot_sprite(color, radius, ring="#ffffff", ring_px=2, hollow=False):
    """Return a cached, antialiased ``PhotoImage`` for a canvas dot."""
    radius = max(1, int(round(float(radius))))
    ring_px = max(0, int(round(float(ring_px))))
    key = (color, radius, ring, ring_px, bool(hollow))
    if key not in _dot_cache:
        supersample = 4
        diameter = (radius + ring_px) * 2
        source_size = diameter * supersample
        image = Image.new("RGBA", (source_size, source_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        inset = ring_px * supersample
        circle_box = [inset, inset, source_size - 1 - inset, source_size - 1 - inset]
        if hollow:
            draw.ellipse(circle_box, outline=color, width=max(2, radius // 2) * supersample)
        else:
            draw.ellipse([0, 0, source_size - 1, source_size - 1], fill=ring)
            draw.ellipse(circle_box, fill=color)
        image = image.resize((diameter, diameter), Image.Resampling.LANCZOS)
        _dot_cache[key] = ImageTk.PhotoImage(image, master=_root)
    return _dot_cache[key]
