"""Central UI palette, fonts, and reusable ttk styling helpers."""

from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

from gui.native_title_bar import apply_title_bar

THEME_NAME = "cosmo"
DIAGRAM_BG = "#ffffff"

# Surfaces / text.
SURFACE = "#f8f9fa"
SURFACE_ALT = "#eef0f2"
VIDEO_BG = "#dee2e6"
BORDER = "#ced4da"
TEXT = "#212529"
TEXT_MUTED = "#68717a"
DISABLED_BG = SURFACE_ALT
DISABLED_FG = TEXT_MUTED

# Semantic widget state.
ACCENT = "#2780e3"
ON_GREEN = "#9fdca4"
OFF_RED = "#E57373"
NEUTRAL = "#ffffff"
ON_HOVER = "#8fd096"
OFF_HOVER = "#dd6666"
SELECTION_BG = "#1f64b0"
SELECTION_FG = "#ffffff"

# Touch timelines.
TL_EMPTY = "#e9ecef"
TL_OUTLINE = "#d5d9dd"
TL_UNAVAILABLE = "#d7dadd"
TL_UNAVAILABLE_MARK = "#aeb4ba"
TL_ON = ON_GREEN
TL_DURING = "#d9f0db"
TL_OFF = OFF_RED
TL_ONSET_MARK = "#2f8f57"
TL_OFFSET_MARK = "#c0392b"
# Parameter ticks are secondary to onset/offset edges: muted hues, 1 px and
# dashed, so a parameter OFF can never be mistaken for a touch OFF.
TL_PARAM_ON_MARK = "#74b58c"
TL_PARAM_OFF_MARK = "#dc9088"
TL_PARAM_MARK_WIDTH = 1
TL_PARAM_MARK_DASH = (3, 2)
PLAYHEAD = ACCENT

# Status chips use small semantic dots rather than filled backgrounds.
STATUS_OK = TL_ONSET_MARK
STATUS_BAD = TL_OFFSET_MARK
STATUS_WARN = "#d39e00"

# Legacy controller fields retained until the timeline polish phase.
TOUCH_START = ACCENT
TOUCH_END = TL_OFFSET_MARK

# Diagram dots.
DOT_ONSET = "#21a453"
DOT_OFFSET = "#e2483d"
SPECIAL_ZONE_DOT = DOT_OFFSET

# Keep the existing role names for canvas painters. TinyTouch owns one Tk
# interpreter; selecting a palette updates the roles before any widget repaints.
LIGHT_PALETTE = {
    name: value for name, value in tuple(globals().items())
    if name.isupper() and isinstance(value, str) and value.startswith("#")
}
DARK_PALETTE = {
    **LIGHT_PALETTE,
    "SURFACE": "#24282f", "SURFACE_ALT": "#2c313a",
    "VIDEO_BG": "#191d23", "BORDER": "#454d5a",
    "TEXT": "#e4e8ef", "TEXT_MUTED": "#a6b0bf",
    "DISABLED_BG": "#2c313a", "DISABLED_FG": "#a6b0bf",
    "ACCENT": "#83b4ed", "NEUTRAL": "#303640",
    "ON_GREEN": "#355746", "OFF_RED": "#65434b",
    "ON_HOVER": "#426b57", "OFF_HOVER": "#7a515b",
    "SELECTION_BG": "#45658a", "SELECTION_FG": "#e4e8ef",
    "TL_EMPTY": "#2c313a", "TL_OUTLINE": "#424a56",
    "TL_UNAVAILABLE": "#20242b", "TL_UNAVAILABLE_MARK": "#616c7b",
    "TL_ON": "#355746", "TL_DURING": "#30483e", "TL_OFF": "#65434b",
    "TL_ONSET_MARK": "#75c69b", "TL_OFFSET_MARK": "#e79599",
    "TL_PARAM_ON_MARK": "#689a80", "TL_PARAM_OFF_MARK": "#ba8088",
    "PLAYHEAD": "#83b4ed", "TOUCH_START": "#83b4ed", "TOUCH_END": "#e79599",
    "STATUS_OK": "#75c69b", "STATUS_BAD": "#e79599", "STATUS_WARN": "#dec17b",
}
PALETTES = {"light": LIGHT_PALETTE, "dark": DARK_PALETTE}
_appearance = "light"


def bind_colors(widget, **roles):
    """Remember explicit color roles for a Tk widget, including future dialogs."""
    widget._theme_color_roles = {**getattr(widget, "_theme_color_roles", {}), **roles}
    widget.configure(**{option: globals()[role] for option, role in roles.items()})
    return widget


def _refresh_colors(widget):
    roles = getattr(widget, "_theme_color_roles", {})
    if roles:
        widget.configure(**{option: globals()[role] for option, role in roles.items()})
    _sync_title_bar(widget)
    for child in widget.winfo_children():
        _refresh_colors(child)


def _sync_title_bar(widget):
    if widget.winfo_toplevel() is widget:
        apply_title_bar(widget, dark=_appearance == "dark",
                        background=SURFACE, foreground=TEXT)


def _on_window_map(event):
    # Map fires for child controls too; only root/Toplevel windows have captions.
    # Tcl-owned popups (for example a combobox list) have no Python widget object.
    if isinstance(event.widget, str):
        return
    _sync_title_bar(event.widget)


_dot_cache = {}

# Fonts.
FONT_BASE = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_TITLE = ("Segoe UI", 11)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_SUBTITLE = FONT_SMALL
FONT_DIALOG_TITLE = FONT_TITLE


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
            draw.ellipse(
                circle_box,
                outline=color,
                width=max(2, radius // 2) * supersample,
            )
        else:
            draw.ellipse([0, 0, source_size - 1, source_size - 1], fill=ring)
            draw.ellipse(circle_box, fill=color)
        image = image.resize(
            (diameter, diameter),
            Image.Resampling.LANCZOS,
        )
        _dot_cache[key] = ImageTk.PhotoImage(image)
    return _dot_cache[key]


def _flat_button(style, name, background, hover):
    """Register a flat button style with readable hover text."""
    style.configure(
        name,
        background=background,
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=background,
        darkcolor=background,
        focusthickness=0,
        font=FONT_BASE,
        padding=(10, 5),
    )
    style.map(
        name,
        background=[("active", hover), ("pressed", hover)],
        foreground=[
            ("active", TEXT),
            ("pressed", TEXT),
            ("disabled", TEXT_MUTED),
        ],
        bordercolor=[("active", BORDER)],
        lightcolor=[("active", hover)],
        darkcolor=[("active", hover)],
    )


def init_style(root, appearance="light"):
    """Attach the selected appearance to an existing ``tk.Tk`` root."""
    # Keep this import local so importing app modules remains safe in headless
    # tests and does not initialize ttkbootstrap's widget API prematurely.
    import ttkbootstrap

    from ttkbootstrap.style import ThemeDefinition
    from ttkbootstrap.themes.standard import STANDARD_THEMES

    style = ttkbootstrap.Style(theme=THEME_NAME)
    colors = dict(STANDARD_THEMES["darkly"]["colors"])
    colors.update(
        bg=DARK_PALETTE["SURFACE"], fg=DARK_PALETTE["TEXT"],
        inputbg=DARK_PALETTE["VIDEO_BG"], inputfg=DARK_PALETTE["TEXT"],
        border=DARK_PALETTE["BORDER"], primary=DARK_PALETTE["ACCENT"],
        secondary=DARK_PALETTE["BORDER"], active=DARK_PALETTE["NEUTRAL"],
        selectbg=DARK_PALETTE["SELECTION_BG"], selectfg=DARK_PALETTE["SELECTION_FG"],
        success=DARK_PALETTE["STATUS_OK"], danger=DARK_PALETTE["STATUS_BAD"],
        warning=DARK_PALETTE["STATUS_WARN"],
    )
    style.register_theme(ThemeDefinition(
        name="tinytouch-dark", themetype="dark", colors=colors,
    ))
    bind_colors(root, bg="SURFACE")
    root.bind_all("<Map>", _on_window_map, add="+")
    apply_appearance(root, style, appearance)
    return style


def apply_appearance(root, style, appearance):
    """Switch themed controls and explicitly colored widgets together."""
    global _appearance
    _appearance = appearance
    globals().update(PALETTES.get(appearance, LIGHT_PALETTE))
    style.theme_use("tinytouch-dark" if appearance == "dark" else THEME_NAME)
    _flat_button(style, "Tool.TButton", NEUTRAL, TL_EMPTY)
    _flat_button(style, "StateOn.TButton", ON_GREEN, ON_HOVER)
    _flat_button(style, "StateOff.TButton", OFF_RED, OFF_HOVER)
    _flat_button(style, "StateNeutral.TButton", NEUTRAL, TL_EMPTY)
    style.configure("Muted.TLabel", foreground=TEXT_MUTED)
    _refresh_colors(root)


def set_button_state(button, state):
    """Apply the semantic ttk style for an ON, OFF, or unset state."""
    normalized = None if state in (None, "None", "") else state
    style_name = {
        "ON": "StateOn.TButton",
        "OFF": "StateOff.TButton",
    }.get(normalized, "StateNeutral.TButton")
    button.configure(style=style_name)


class StatusChip(ttk.Frame):
    """A muted label followed by a colored status dot and plain text."""

    def __init__(self, parent, label, color, text, **kwargs):
        super().__init__(parent, **kwargs)
        ttk.Label(
            self,
            text=label,
            font=FONT_SMALL,
            style="Muted.TLabel",
        ).pack(side="left")
        self._dot_label = ttk.Label(
            self,
            text="●",
            font=FONT_SMALL,
            foreground=color,
        )
        self._dot_label.pack(side="left", padx=(4, 2))
        self._text_label = ttk.Label(self, text=text, font=FONT_SMALL)
        self._text_label.pack(side="left")
        self.set(color, text)

    def set(self, color, text):
        """Update the semantic dot color and displayed status text."""
        role = next((name for name in ("STATUS_OK", "STATUS_BAD", "STATUS_WARN")
                     if globals()[name] == color), None)
        if role:
            bind_colors(self._dot_label, foreground=role)
        else:
            getattr(self._dot_label, "_theme_color_roles", {}).pop("foreground", None)
            self._dot_label.configure(foreground=color)
        self._text_label.configure(text=text)
