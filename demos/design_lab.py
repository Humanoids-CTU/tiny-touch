"""Design lab: can ttk draw the proposed Apple-style TinyTouch look?

Standalone feasibility check for the visual refresh. It mirrors the layout of
the real main window (toolbar, status line, video, timelines, diagram panel)
and opens Settings as its own dialog, as the app does. It does not import or
change the app. Run from the repository root:

    uv run demos/design_lab.py

Hover, click and toggle everything: the parameter pills cycle ON / OFF / unset,
the timeline moves its playhead on click, Settings > Appearance switches
light / dark at runtime.
"""

import sys
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageDraw, ImageFilter, ImageTk

# --- Tunables ---------------------------------------------------------------
# Geometry (px before DPI scaling). Buttons and segmented tracks share one
# height and radius; a pill inside a track uses RADIUS - SEG_PAD so the two
# curves stay concentric (an even gap all the way round the corner).
CONTROL_H = 28      # visible height of buttons and segmented tracks
RADIUS = 8          # corner radius of buttons, fields and tracks
SEG_PAD = 2         # gap between a track and the pill inside it
CARD_RADIUS = 12    # panel corner radius
SHADOW_MARGIN = 4   # transparent room around raised shapes for the shadow to fade out
TOOLBAR_GAP = 8     # visible gap between toolbar controls
SUPERSAMPLE = 4     # antialiasing factor for generated corner images
# ttk tiles (does not stretch) the middle of an image element. A large source
# image keeps the tile count low; 22 px images made 60 buttons take ~1.9 s to draw.
ELEMENT_IMAGE_PX = 160
SIDE_WIDTH = 330    # right column width in px (before DPI scaling)
DIAGRAM_WIDTH = 195
FONT_FAMILY = "Segoe UI Variable Text" if sys.platform == "win32" else "TkDefaultFont"
# Windows exposes the semibold cut as its own family. It is the closest match to
# the mockup's medium (500) weight and renders cleaner than Tk's synthetic bold.
FONT_MEDIUM = "Segoe UI Variable Text Semibold" if sys.platform == "win32" else None


def ui_font(size, medium=False):
    """Font tuple: regular, or the medium/semibold cut for labels on controls."""
    if medium and FONT_MEDIUM:
        return (FONT_MEDIUM, size)
    return (FONT_FAMILY, size, "bold" if medium else "normal")
# Shadows as (y offset px, blur sigma px, alpha 0-255) layers. "raised" matches
# the mockup's CSS: 0 1px 2px rgba(0,0,0,.06) plus a faint 0.5px ring.
DEPTH = {
    "raised": ((0, 0.5, 14), (1, 1.0, 20)),
    "card": ((0, 0.5, 10), (1, 1.5, 14)),
}
DIAGRAM_PATH = Path(__file__).resolve().parent.parent / "src" / "resources" / "icons" / "RH.png"

PALETTES = {
    "light": dict(
        WIN="#f5f5f7", CARD="#ffffff", LINE="#d2d2d7", LINE_SOFT="#e5e5ea",
        TEXT="#1d1d1f", MUTED="#6e6e73", ACCENT="#0071e3", ACCENT_HOVER="#0077ed",
        BTN="#ffffff", BTN_HOVER="#f7f7f9", BTN_LINE="#dadadf", BTN_PRESSED="#e6e6ea", BTN_DISABLED="#f0f0f2",
        SEG="#e8e8ed", SEG_HOVER="#dedee4", SEG_TEXT="#3a3a3c", TRACK="#ececf0", VIDEO="#151517", DIAGRAM="#ffffff",
        ON="#cdeed6", ON_HOVER="#bfe7cb", ON_TEXT="#1b6b37", ON_MARK="#2f9e5a",
        OFF="#fbd9d5", OFF_HOVER="#f7cbc6", OFF_TEXT="#a52a1f", OFF_MARK="#d9493d",
        NOTE="#8e5cc2", NOTE_TEXT="#3a3a3c", SWITCH_OFF="#d1d1d6", SWITCH_ON="#34c759",
    ),
    "dark": dict(
        WIN="#1c1c1e", CARD="#2c2c2e", LINE="#48484a", LINE_SOFT="#38383a",
        TEXT="#f5f5f7", MUTED="#98989d", ACCENT="#0a84ff", ACCENT_HOVER="#2b95ff",
        BTN="#3a3a3c", BTN_HOVER="#444446", BTN_LINE="#4a4a4c", BTN_PRESSED="#505052", BTN_DISABLED="#2f2f31",
        SEG="#232325", SEG_HOVER="#2e2e30", SEG_TEXT="#d1d1d6", TRACK="#3a3a3c", VIDEO="#0d0d0e", DIAGRAM="#f2f2f4",
        ON="#21452f", ON_HOVER="#285338", ON_TEXT="#8fe0a8", ON_MARK="#4cc77a",
        OFF="#4a2723", OFF_HOVER="#58302b", OFF_TEXT="#ff9d92", OFF_MARK="#ff6b5e",
        NOTE="#c79bf2", NOTE_TEXT="#d1d1d6", SWITCH_OFF="#48484a", SWITCH_ON="#30d158",
    ),
}


def enable_dpi_awareness():
    """Crisp rendering on scaled Windows displays (the app should do the same)."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


def pill_image(w, h, radius, fill, border=None, depth=None, margin=0, scale=1.0):
    """Antialiased rounded rectangle, optionally with a soft layered shadow.

    `margin` px of transparent space surround the shape so the shadow can fade
    out instead of being cut off at the image edge.
    """
    s = SUPERSAMPLE
    img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    x0, y0, x1, y1 = margin * s, margin * s, (w - margin) * s - 1, (h - margin) * s - 1
    r = radius * s
    for dy, sigma, alpha in DEPTH.get(depth, ()):
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        off = round(dy * scale * s)
        ImageDraw.Draw(layer).rounded_rectangle([x0, y0 + off, x1, y1 + off], radius=r, fill=(0, 0, 0, alpha))
        img = Image.alpha_composite(img, layer.filter(ImageFilter.GaussianBlur(sigma * scale * s)))
    d = ImageDraw.Draw(img)
    if border:
        d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=border)
        d.rounded_rectangle([x0 + s, y0 + s, x1 - s, y1 - s], radius=max(0, r - s), fill=fill)
    else:
        d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill)
    return img.resize((w, h), Image.Resampling.LANCZOS)


class Lab:
    def __init__(self, root):
        self.root = root
        self.mode = "light"
        self.scale = root.winfo_fpixels("1i") / 96.0  # 1.0 at 100 %, 1.5 at 150 %
        self.images = {}       # keeps PhotoImages alive
        self.generation = 0    # unique element names per restyle
        self.style = ttk.Style(root)
        self.style.theme_use("clam")  # clam honours colors and image elements
        self.painters = []     # canvases repainted on theme change
        self.bound = []        # (tk widget, {option: palette key})
        self.settings_win = None
        self.combo = None
        self.restyle()
        self.build()

    # --- image helpers ------------------------------------------------------
    def px(self, value):
        return max(1, round(value * self.scale))

    def keep(self, photo):
        self.images[id(photo)] = photo
        return photo

    def rounded(self, fill, border, radius, size=None, depth=None, margin=0):
        """Rounded image for a ttk element; returns (photo, slice px)."""
        r = self.px(radius)
        w = h = size or ELEMENT_IMAGE_PX
        img = pill_image(w, h, r, fill, border, depth, margin, self.scale)
        return self.keep(ImageTk.PhotoImage(img, master=self.root)), r + 2 + margin

    def flat(self, fill, size=ELEMENT_IMAGE_PX):
        return self.keep(ImageTk.PhotoImage(Image.new("RGBA", (size, size), fill), master=self.root))

    def chevron(self, color):
        """Small antialiased down-chevron for the combobox arrow."""
        s, w, h = SUPERSAMPLE, self.px(18), self.px(14)
        img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        cx, cy, a = w * s / 2 - s * 3, h * s / 2, self.px(4) * s
        d.line([(cx - a, cy - a / 2), (cx, cy + a / 2), (cx + a, cy - a / 2)], fill=color,
               width=int(1.6 * s * self.scale), joint="curve")
        return self.keep(ImageTk.PhotoImage(img.resize((w, h), Image.Resampling.LANCZOS), master=self.root))

    def image_element(self, name, normal, states=(), slice_px=None):
        """Create a uniquely named ttk image element; small minimum size, large source."""
        slice_px = slice_px or self.px(RADIUS) + 2
        elem = f"lab{self.generation}.{name}"
        # padding=0: an image element otherwise uses its border as inner padding,
        # which made every button ~12 px wider and taller on each side.
        self.style.element_create(elem, "image", normal, *states, border=slice_px, padding=0,
                                  sticky="nsew", width=2 * slice_px, height=2 * slice_px)
        return elem

    # --- styles -------------------------------------------------------------
    def image_button(self, name, normal, hover, pressed, disabled, fg, border=None, bold=False, bg=None):
        """Register `name` (e.g. 'Tool.TButton') as a rounded image button."""
        p = self.p
        border = p["BTN_LINE"] if border is None else border
        margin = self.px(SHADOW_MARGIN)
        made = {k: self.rounded(c, border or None, RADIUS, depth=None if k == "d" else "raised", margin=margin)
                for k, c in dict(n=normal, h=hover, p=pressed, d=disabled).items()}
        imgs = {k: v[0] for k, v in made.items()}
        elem = self.image_element(name + ".bg", imgs["n"],
                                  (("disabled", imgs["d"]), ("pressed", imgs["p"]), ("active", imgs["h"])),
                                  slice_px=made["n"][1])
        self.style.layout(name, [(elem, {"sticky": "nsew", "children": [
            ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})])
        font = ui_font(10, medium=True)
        # Pad so the visible pill (widget minus shadow margin) is exactly CONTROL_H.
        line = tkfont.Font(root=self.root, font=font).metrics("linespace")
        pad_y = max(0, (self.px(CONTROL_H) + 2 * margin - line) // 2)
        self.style.configure(name, foreground=fg, background=bg or p["WIN"], width=0, anchor="center",
                             font=font, padding=(self.px(12) + margin, pad_y))
        self.style.map(name, foreground=[("disabled", p["MUTED"])], background=[("active", bg or p["WIN"])])

    def segment_styles(self):
        """Segments on a grey track: radio segments (stay selected) and push segments."""
        p = self.p
        sel = self.rounded(p["BTN"], p["LINE_SOFT"], RADIUS - 1)[0]
        hov = self.rounded(p["BTN_HOVER"] if self.mode == "light" else p["BTN"], None, RADIUS - 1)[0]
        flat = self.flat(p["SEG"])
        for name, kind in (("Seg.Toolbutton", "Toolbutton"), ("Seg.TButton", "Button")):
            states = (("selected", sel), ("pressed", sel), ("active", hov))
            elem = self.image_element(name + ".bg", flat, states)
            self.style.layout(name, [(elem, {"sticky": "nsew", "children": [
                (f"{kind}.padding", {"sticky": "nsew", "children": [(f"{kind}.label", {"sticky": "nsew"})]})]})])
            self.style.configure(name, foreground=p["TEXT"], background=p["SEG"], width=0, anchor="center",
                                 font=(FONT_FAMILY, 10), padding=(self.px(10), self.px(3)))
            self.style.map(name, foreground=[("disabled", p["MUTED"])], background=[("active", p["SEG"])])
        track = self.rounded(p["SEG"], None, RADIUS + 1)[0]
        elem = self.image_element("Seg.TFrame.bg", track)
        self.style.layout("Seg.TFrame", [(elem, {"sticky": "nsew", "children": [
            ("Frame.padding", {"sticky": "nsew"})]})])
        self.style.configure("Seg.TFrame", background=p["SEG"])

    def field_styles(self):
        """Rounded Entry and Combobox with an accent ring on focus and a chevron arrow."""
        p = self.p
        normal = self.rounded(p["BTN"], p["LINE"], RADIUS - 1)[0]
        focus = self.rounded(p["BTN"], p["ACCENT"], RADIUS - 1)[0]
        arrow = f"lab{self.generation}.Combobox.chevron"
        self.style.element_create(arrow, "image", self.chevron(p["MUTED"]),
                                  ("active", self.chevron(p["TEXT"])), sticky="")
        for widget in ("Entry", "Combobox"):
            elem = self.image_element(widget + ".field", normal, (("focus", focus),))
            inner = [(arrow, {"side": "right", "sticky": "ns"})] if widget == "Combobox" else []
            inner.append((f"{widget}.padding", {"sticky": "nsew", "children": [
                (f"{widget}.textarea", {"sticky": "nsew"})]}))
            self.style.layout("T" + widget, [(elem, {"sticky": "nsew", "children": inner})])
            self.style.configure("T" + widget, fieldbackground=p["BTN"], foreground=p["TEXT"],
                                 background=p["CARD"], padding=(self.px(8), self.px(4)))
            self.style.map("T" + widget, fieldbackground=[("readonly", p["BTN"])],
                           foreground=[("readonly", p["TEXT"])], background=[("active", p["CARD"])])
        # The dropdown list is a plain Tk Listbox in its own popup window.
        for option, value in (("background", p["CARD"]), ("foreground", p["TEXT"]),
                              ("selectBackground", p["ACCENT"]), ("selectForeground", "#ffffff"),
                              ("font", (FONT_FAMILY, 10)), ("borderWidth", 0), ("relief", "flat"),
                              ("highlightThickness", 0), ("activeStyle", "none")):
            self.root.option_add(f"*TCombobox*Listbox.{option}", value)

    def restyle(self):
        self.p = p = PALETTES[self.mode]
        self.generation += 1
        self.old_images, self.images = self.images, {}
        s = self.style
        s.configure(".", background=p["WIN"], foreground=p["TEXT"], font=(FONT_FAMILY, 10),
                    bordercolor=p["LINE"], lightcolor=p["CARD"], darkcolor=p["CARD"],
                    troughcolor=p["TRACK"], selectbackground=p["ACCENT"], selectforeground="#ffffff",
                    fieldbackground=p["BTN"], insertcolor=p["TEXT"])
        s.configure("TFrame", background=p["WIN"])
        s.configure("Card.TFrame", background=p["CARD"])
        s.configure("TLabel", background=p["WIN"], foreground=p["TEXT"])
        s.configure("Card.TLabel", background=p["CARD"], foreground=p["TEXT"])
        s.configure("CardMuted.TLabel", background=p["CARD"], foreground=p["MUTED"], font=(FONT_FAMILY, 9))
        s.configure("CardHead.TLabel", background=p["CARD"], foreground=p["TEXT"], font=ui_font(9, True))
        s.configure("Status.TLabel", foreground=p["MUTED"], font=(FONT_FAMILY, 9))
        s.configure("StatusValue.TLabel", foreground=p["TEXT"], font=ui_font(9, True))
        s.configure("Section.TLabel", foreground=p["MUTED"], font=ui_font(8, True))
        s.configure("Link.TLabel", foreground=p["ACCENT"], font=(FONT_FAMILY, 10))
        self.image_button("Tool.TButton", p["BTN"], p["BTN_HOVER"], p["BTN_PRESSED"], p["BTN_DISABLED"], p["TEXT"])
        self.image_button("Card.Tool.TButton", p["BTN"], p["BTN_HOVER"], p["BTN_PRESSED"], p["BTN_DISABLED"],
                          p["TEXT"], bg=p["CARD"])
        self.image_button("Primary.TButton", p["ACCENT"], p["ACCENT_HOVER"], p["ACCENT"], p["BTN_DISABLED"],
                          "#ffffff", border=p["ACCENT"], bold=True)
        self.image_button("StateNeutral.TButton", p["BTN"], p["BTN_HOVER"], p["BTN_PRESSED"], p["BTN_DISABLED"],
                          p["TEXT"], bg=p["CARD"], bold=True)
        self.image_button("StateOn.TButton", p["ON"], p["ON_HOVER"], p["ON_HOVER"], p["BTN_DISABLED"],
                          p["ON_TEXT"], border=p["ON"], bold=True, bg=p["CARD"])
        self.image_button("StateOff.TButton", p["OFF"], p["OFF_HOVER"], p["OFF_HOVER"], p["BTN_DISABLED"],
                          p["OFF_TEXT"], border=p["OFF"], bold=True, bg=p["CARD"])
        self.segment_styles()
        self.field_styles()
        self.root.configure(bg=p["WIN"])
        for widget, roles in self.bound:
            if widget.winfo_exists():
                widget.configure(**{option: p[key] for option, key in roles.items()})
        for painter in self.painters:
            if painter.winfo_exists():
                painter.repaint()

    def bind_colors(self, widget, **roles):
        self.bound.append((widget, roles))
        widget.configure(**{option: self.p[key] for option, key in roles.items()})
        return widget

    def set_mode(self, mode):
        if mode != self.mode:
            self.mode = mode
            self.restyle()

    # --- main window --------------------------------------------------------
    def build(self):
        root, px = self.root, self.px
        root.title("TinyTouch")
        outer = ttk.Frame(root, padding=px(14))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        main = ttk.Frame(outer)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)
        side = ttk.Frame(outer, width=px(SIDE_WIDTH))
        side.grid(row=0, column=1, sticky="ns", padx=(px(14), 0))
        side.grid_propagate(False)
        side.pack_propagate(False)

        # Toolbar: actions on the left, frame navigation and playback on the right.
        bar = ttk.Frame(main)
        bar.grid(row=0, column=0, sticky="ew")
        for text in ("Load Video", "Settings", "Special Zones", "Analysis", "Save"):
            command = self.open_settings if text == "Settings" else None
            button = ttk.Button(bar, text=text, style="Tool.TButton", takefocus=0, command=command)
            button.pack(side="left", padx=(0, max(0, px(TOOLBAR_GAP) - 2 * px(SHADOW_MARGIN))))
            if text == "Settings":
                self.settings_button = button
        play = tk.StringVar(value="Play")
        SegmentedControl(bar, self, ("Play", "Stop"), variable=play, gapless=True,
                         icons={"Play": "play", "Stop": "stop"}).pack(side="right")
        SegmentedControl(bar, self, ("«", "‹", "Select Frame", "›", "»"), min_seg=34).pack(
            side="right", padx=(0, max(0, px(TOOLBAR_GAP) - 2 * px(SHADOW_MARGIN))))

        # Status line under the toolbar.
        status = ttk.Frame(main)
        status.grid(row=1, column=0, sticky="ew", pady=(px(8), px(10)))
        for label, value, dot in (("Mode", "Normal", True), ("Buffer", "Loaded", True),
                                  ("Min touch length", "0.12 s", False), ("Jump", "0.28 s", False)):
            ttk.Label(status, text=label, style="Status.TLabel").pack(side="left")
            if dot:
                dot_label = tk.Label(status, text="●", font=(FONT_FAMILY, 7), bd=0)
                self.bind_colors(dot_label, bg="WIN", fg="ON_MARK")
                dot_label.pack(side="left", padx=(px(4), px(2)))
            else:
                ttk.Frame(status, width=px(4)).pack(side="left")
            ttk.Label(status, text=value, style="StatusValue.TLabel").pack(side="left", padx=(0, px(16)))
        # Packed right-to-left: "Frame 1 248 / 9 000  ·  00:49.9 / 06:00.0"
        for text, style in reversed((("Frame ", "Status.TLabel"), ("1 248", "StatusValue.TLabel"),
                                     (" / 9 000   ·   ", "Status.TLabel"), ("00:49.9", "StatusValue.TLabel"),
                                     (" / 06:00.0", "Status.TLabel"))):
            ttk.Label(status, text=text, style=style, padding=0).pack(side="right")

        # Video and timelines.
        video = RoundedCard(main, self, fill="VIDEO", border="VIDEO")
        video.grid(row=2, column=0, sticky="nsew")
        video.fill_height = True
        label = tk.Label(video.inner, text="video surface (the GPU renderer draws here)", bd=0)
        self.bind_colors(label, bg="VIDEO", fg="MUTED")
        label.pack(expand=True)
        VideoTag(video.inner, self, "session_04_cam2.mp4").place(
            relx=0, rely=1, x=px(12), y=-px(12), anchor="sw")
        tl = RoundedCard(main, self)
        tl.grid(row=3, column=0, sticky="ew", pady=(px(4), 0))
        self.timeline = Timeline(tl.inner, self)
        self.timeline.pack(fill="x", padx=px(14), pady=px(12))

        # Right column: diagram, channel, parameters, notes.
        diagram = RoundedCard(side, self)
        diagram.pack(fill="x")
        Diagram(diagram.inner, self).pack(padx=px(12), pady=px(12))

        channel = RoundedCard(side, self)
        channel.pack(fill="x", pady=(px(4), 0))
        head = ttk.Frame(channel.inner, style="Card.TFrame")
        head.pack(fill="x", padx=px(14), pady=(px(12), px(8)))
        ttk.Label(head, text="Channel", style="CardHead.TLabel").pack(side="left")
        chosen = tk.StringVar(value="Right Hand")
        SegmentedControl(channel.inner, self, ("Right Hand", "Left Hand", "Right Leg", "Left Leg"),
                         variable=chosen, columns=2, bg="CARD").pack(fill="x", padx=px(14), pady=(0, px(14)))

        params = RoundedCard(side, self)
        params.pack(fill="x", pady=(px(4), 0))
        body = params.inner
        ttk.Label(body, text="Parameters", style="CardHead.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=px(14), pady=(px(12), px(6)))
        for col, text in enumerate(("Channel", "Global")):
            ttk.Label(body, text=text, style="CardMuted.TLabel").grid(
                row=1, column=col, sticky="w", padx=(px(14), px(4)) if col == 0 else (px(4), px(14)))
        for row in range(3):
            for col, prefix in enumerate(("LP", "P")):
                start = {(0, 0): "ON", (1, 1): "OFF"}.get((row, col))
                ParamPill(body, self, f"{prefix}{row + 1}", start).grid(
                    row=row + 2, column=col, sticky="ew", pady=0,
                    padx=(px(14), px(4)) if col == 0 else (px(4), px(14)))
        body.columnconfigure((0, 1), weight=1, uniform="p")
        ttk.Frame(body, height=px(10), style="Card.TFrame").grid(row=5, column=0)

        notes = RoundedCard(side, self)
        notes.pack(fill="x", pady=(px(4), 0))
        ttk.Label(notes.inner, text="Notes", style="CardHead.TLabel").pack(
            anchor="w", padx=px(14), pady=(px(12), px(6)))
        field = RoundedCard(notes.inner, self, fill="BTN", border="BTN_LINE", radius=RADIUS, outer="CARD",
                            pad=px(9))
        field.pack(fill="x", padx=px(14))
        text = tk.Text(field.inner, height=2, wrap="word", bd=0, highlightthickness=0,
                       font=(FONT_FAMILY, 9), padx=px(1), pady=0, spacing2=px(3))
        self.bind_colors(text, bg="BTN", fg="NOTE_TEXT", insertbackground="TEXT",
                         selectbackground="ACCENT", selectforeground="BTN")
        text.insert("1.0", "Baby turns toward the camera; hand partly hidden.")
        text.pack(fill="x")
        row = ttk.Frame(notes.inner, style="Card.TFrame")
        row.pack(fill="x", padx=px(14), pady=(px(8), px(14)))
        ttk.Button(row, text="Save Note", style="Card.Tool.TButton", takefocus=0).pack(side="right")

        root.bind("<space>", lambda _e: self.timeline.step(), add="+")

    # --- settings dialog ----------------------------------------------------
    def open_settings(self):
        if self.settings_win is not None and self.settings_win.winfo_exists():
            self.settings_win.lift()
            return self.settings_win
        px = self.px
        win = tk.Toplevel(self.root)
        win.title("Settings")
        win.resizable(False, False)
        self.bind_colors(win, bg="WIN")
        self.settings_win = win
        content = ttk.Frame(win, padding=(px(18), px(16)))
        content.pack(fill="both", expand=True)

        ttk.Label(content, text="DISPLAY", style="Section.TLabel").pack(anchor="w", padx=px(4), pady=(0, px(6)))
        group = RoundedCard(content, self, radius=10)
        group.pack(fill="x")
        rows = group.inner

        def row(label, hint=None):
            if rows.winfo_children():
                line = tk.Frame(rows, height=1, bd=0)
                self.bind_colors(line, bg="LINE_SOFT")
                line.pack(fill="x", padx=(px(14), 0))
            frame = ttk.Frame(rows, style="Card.TFrame")
            frame.pack(fill="x", padx=px(14), pady=px(7))
            left = ttk.Frame(frame, style="Card.TFrame")
            left.pack(side="left")
            ttk.Label(left, text=label, style="Card.TLabel").pack(side="left")
            if hint:
                ttk.Label(left, text="  " + hint, style="CardMuted.TLabel").pack(side="left")
            return frame

        appearance = tk.StringVar(value=self.mode.title())
        SegmentedControl(row("Appearance"), self, ("Light", "Dark"), variable=appearance, bg="CARD",
                         command=lambda value: self.set_mode(value.lower())).pack(side="right")
        self.combo = ttk.Combobox(row("Video renderer"), values=("Automatic (GPU preferred)", "CPU"),
                                  state="readonly", width=22)
        self.combo.set("Automatic (GPU preferred)")
        self.combo.pack(side="right")
        ttk.Label(row("Active renderer"), text="Not initialized", style="CardMuted.TLabel").pack(side="right")
        for label, hint, value in (("Video downscale", "1 = full, 2 = half", "1.0"), ("Dot size", None, "10.0"),
                                   ("Fast-jump seconds", ">> / Shift+Arrow", "0.28")):
            entry = ttk.Entry(row(label, hint), width=7, justify="right")
            entry.insert(0, value)
            entry.pack(side="right")
        Switch(row("Show zone names on diagrams"), self).pack(side="right")
        ttk.Frame(rows, height=px(2), style="Card.TFrame").pack()

        foot = ttk.Frame(content)
        foot.pack(fill="x", pady=(px(14), 0), padx=px(4))
        ttk.Label(foot, text="Open logs folder", style="Link.TLabel", cursor="hand2").pack(side="left")
        ttk.Button(foot, text="Save", style="Primary.TButton", takefocus=0,
                   command=win.destroy).pack(side="right")
        return win


class SegmentedControl(tk.Canvas):
    """Apple-style segmented control drawn on a canvas.

    A rounded grey track; the selected (or pressed) segment is a white pill with
    a soft shadow, a hovered one is a slightly darker grey. With `variable` it
    behaves like radio buttons; without it every segment is a push button.
    `columns` lays the segments out in a grid that fills the available width.
    `gapless` makes the selected pill fill its whole cell (grids are always
    gapless). `icons` maps a label to a drawn icon ("play" / "stop").
    """

    def __init__(self, parent, lab, labels, variable=None, columns=0, bg="WIN", command=None,
                 gapless=False, icons=None, min_seg=0):
        super().__init__(parent, highlightthickness=0, bd=0, cursor="hand2")
        self.lab, self.labels, self.variable, self.columns = lab, list(labels), variable, columns
        self.bg, self.command = bg, command
        self.gapless = gapless or bool(columns)
        self.icons = icons or {}
        self._icon_cache = {}
        self.hover = self.pressed = None
        self.font = tkfont.Font(root=lab.root, font=ui_font(10))
        self.font_raised = tkfont.Font(root=lab.root, font=ui_font(10, medium=True))
        px = lab.px
        # The track is drawn inset by the same margin buttons keep for their
        # shadow, so a track and a button side by side share top and bottom edges.
        self.margin = px(SHADOW_MARGIN)
        # Gapless controls (the channel grid, Play/Stop) have no inner gap: the
        # selected cell fills its share of the track. Others keep the inset pill.
        self.pad = self.gap = 0 if self.gapless else px(SEG_PAD)
        self.icon_px, self.icon_gap = px(9), px(7)
        self.seg_h = px(CONTROL_H) - 2 * self.pad
        self.seg_w = [max(px(min_seg), self.font_raised.measure(text) + 2 * px(11)
                          + (self.icon_px + self.icon_gap if text in self.icons else 0)) for text in self.labels]
        if self.gapless and not columns:
            self.seg_w = [max(self.seg_w)] * len(self.seg_w)  # equal halves
        rows = -(-len(self.labels) // columns) if columns else 1
        height = rows * self.seg_h + (rows - 1) * self.gap + 2 * (self.pad + self.margin)
        width = sum(self.seg_w) + self.gap * (len(self.labels) - 1) + 2 * (self.pad + self.margin)
        self.configure(height=height, width=px(100) if columns else width)
        if variable is not None:
            variable.trace_add("write", lambda *_: self.repaint())
        self.bind("<Configure>", lambda _e: self.repaint())
        self.bind("<Motion>", lambda e: self._set(hover=self._hit(e.x, e.y)))
        self.bind("<Leave>", lambda _e: self._set(hover=None, pressed=None))
        self.bind("<ButtonPress-1>", lambda e: self._set(pressed=self._hit(e.x, e.y)))
        self.bind("<ButtonRelease-1>", self._release)
        lab.painters.append(self)

    def _boxes(self):
        w = max(self.winfo_width(), int(self.cget("width")))
        boxes = []
        inset = self.pad + self.margin
        if self.columns:
            cw = (w - 2 * inset - (self.columns - 1) * self.gap) / self.columns
            for i in range(len(self.labels)):
                r, c = divmod(i, self.columns)
                x = inset + c * (cw + self.gap)
                y = inset + r * (self.seg_h + self.gap)
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
                return i
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
        if hit is None or hit != was:
            return
        value = self.labels[hit]
        if self.variable is not None:
            self.variable.set(value)
        if self.command:
            self.command(value)

    def repaint(self):
        p, px = self.lab.p, self.lab.px
        w = max(self.winfo_width(), int(self.cget("width")))
        h = int(self.cget("height"))
        self.configure(bg=p[self.bg])
        self.delete("all")
        if getattr(self, "_icon_mode", None) != self.lab.mode:
            self._icon_cache, self._icon_mode = {}, self.lab.mode
        track = pill_image(w, h, px(RADIUS), p["SEG"], margin=self.margin)
        self._track = ImageTk.PhotoImage(track, master=self)
        self.create_image(0, 0, image=self._track, anchor="nw")
        selected = self.variable.get() if self.variable is not None else None
        self._pills, margin = [], self.margin
        inner_r = px(RADIUS) - self.pad  # concentric with the track (equal when there is no gap)
        for i, (x0, y0, x1, y1) in enumerate(self._boxes()):
            label = self.labels[i]
            raised = label == selected or i == self.pressed
            if raised or i == self.hover:
                # In a gapless grid the pill bleeds 1 px past its cell so the
                # track's antialiased grey edge never shows around it.
                bleed = px(1) if self.gapless else 0
                bx0, by0, bx1, by1 = x0 - bleed, y0 - bleed, x1 + bleed, y1 + bleed
                bw, bh = round(bx1 - bx0) + 2 * margin, round(by1 - by0) + 2 * margin
                img = pill_image(bw, bh, inner_r + bleed, p["BTN"] if raised else p["SEG_HOVER"],
                                 None, "raised" if raised else None, margin, self.lab.scale)
                photo = ImageTk.PhotoImage(img, master=self)
                self._pills.append(photo)
                self.create_image(round(bx0) - margin, round(by0) - margin, image=photo, anchor="nw")
            font = self.font_raised if raised else self.font
            ink = p["TEXT"] if raised or self.variable is None else p["SEG_TEXT"]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            icon = self.icons.get(label)
            if icon:
                # Centre icon + label as one group; the icon is drawn, not a
                # font glyph, so it sits exactly on the text's optical centre.
                group = self.icon_px + self.icon_gap + font.measure(label)
                left = cx - group / 2
                photo = self._icon(icon, ink)
                self.create_image(round(left), round(cy), image=photo, anchor="w")
                self.create_text(left + self.icon_px + self.icon_gap, cy, text=label, anchor="w", font=font, fill=ink)
            else:
                self.create_text(cx, cy, text=label, font=font, fill=ink)

    def _icon(self, kind, color):
        """Antialiased play triangle or stop square, cached per colour."""
        key = (kind, color)
        if key not in self._icon_cache:
            n, s = self.icon_px, SUPERSAMPLE
            img = Image.new("RGBA", (n * s, n * s), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            if kind == "play":
                # Equilateral-ish triangle, nudged so its visual centre sits mid-box.
                d.polygon([(1 * s, 0), (1 * s, n * s - 1), (n * s - 1, n * s / 2)], fill=color)
            else:
                inset = round(n * 0.08) * s
                d.rounded_rectangle([inset, inset, n * s - 1 - inset, n * s - 1 - inset], radius=s * 1.5, fill=color)
            self._icon_cache[key] = ImageTk.PhotoImage(img.resize((n, n), Image.Resampling.LANCZOS), master=self)
        return self._icon_cache[key]


class VideoTag(tk.Canvas):
    """Small translucent-looking name tag drawn over the video corner.

    Tk has no real transparency, so the tag is a dark rounded pill on the
    video background colour.
    """

    def __init__(self, parent, lab, text):
        self.lab, self.text = lab, text
        self.font = tkfont.Font(root=lab.root, font=ui_font(9))
        px = lab.px
        w = self.font.measure(text) + 2 * px(9)
        h = self.font.metrics("linespace") + 2 * px(4)
        super().__init__(parent, width=w, height=h, highlightthickness=0, bd=0)
        lab.painters.append(self)
        self.repaint()

    def repaint(self):
        p = self.lab.p
        w, h = int(self.cget("width")), int(self.cget("height"))
        self.configure(bg=p["VIDEO"])
        self.delete("all")
        self._photo = ImageTk.PhotoImage(pill_image(w, h, self.lab.px(6), "#2b2b2e"), master=self)
        self.create_image(0, 0, image=self._photo, anchor="nw")
        self.create_text(w / 2, h / 2, text=self.text, font=self.font, fill="#d6d6db")


class RoundedCard(tk.Canvas):
    """A Canvas that paints a rounded rectangle and hosts a frame inside it."""

    def __init__(self, parent, lab, fill="CARD", border="LINE_SOFT", radius=CARD_RADIUS, outer="WIN", pad=None):
        super().__init__(parent, highlightthickness=0, bd=0, height=10, width=10)
        self.lab, self.fill, self.border, self.radius, self.outer = lab, fill, border, radius, outer
        self.fill_height = False
        if fill == "CARD":
            self.inner = ttk.Frame(self, style="Card.TFrame")
        else:
            self.inner = tk.Frame(self, bd=0)
            lab.bind_colors(self.inner, bg=fill)
        # Panels get the soft card shadow; fields (fill != CARD) keep a hairline.
        self._margin = lab.px(SHADOW_MARGIN) if fill == "CARD" else 0
        self._pad = (pad if pad is not None else max(lab.px(radius) // 2, lab.px(4))) + self._margin
        self._win = self.create_window(self._pad, self._pad, window=self.inner, anchor="nw")
        self._painted = None
        self.inner.bind("<Configure>", self._fit_height)
        self.bind("<Configure>", lambda _e: self.repaint())
        # The content is only mapped (and reports its size) once it lies inside
        # the canvas, so size the canvas from the content's request up front.
        self.after_idle(self._fit_height)
        lab.painters.append(self)

    def _fit_height(self, _event=None):
        # Grow the canvas to its content. Only act on a real change, otherwise
        # canvas resize -> inner resize -> canvas resize can loop forever.
        if self.fill_height or not self.winfo_exists():
            return
        want = self.inner.winfo_reqheight() + 2 * self._pad
        if int(self.cget("height")) != want:
            self.configure(height=want)
        # Request the content's natural width so dialogs size to fit it.
        want_w = self.inner.winfo_reqwidth() + 2 * self._pad
        if int(self.cget("width")) != want_w:
            self.configure(width=want_w)

    def repaint(self):
        p = self.lab.p
        w, h = max(self.winfo_width(), 20), max(self.winfo_height(), 20)
        key = (w, h, self.lab.mode)
        if key == self._painted:
            return
        self._painted = key
        self.configure(bg=p[self.outer])
        r = self.lab.px(self.radius)
        if self._margin:
            img = pill_image(w, h, r, p[self.fill], None, "card", self._margin, self.lab.scale)
        else:
            img = pill_image(w, h, r, p[self.fill], p[self.border])
        self._photo = ImageTk.PhotoImage(img, master=self)
        self.delete("bg")
        self.create_image(0, 0, image=self._photo, anchor="nw", tags="bg")
        self.tag_lower("bg")
        self.itemconfigure(self._win, width=w - 2 * self._pad)
        if self.fill_height:
            self.itemconfigure(self._win, height=h - 2 * self._pad)


class ParamPill(tk.Canvas):
    """Parameter toggle as in the mockup: name on the left, ON / OFF on the right.

    Click cycles unset -> ON -> OFF. Drawn on a canvas because a ttk button can
    only centre one text. Uses the same height, radius and shadow as buttons.
    """

    ORDER = (None, "ON", "OFF")

    def __init__(self, parent, lab, text, state=None):
        self.lab, self.text, self.value = lab, text, state
        self.hover = self.pressed = False
        self.margin = lab.px(SHADOW_MARGIN)
        super().__init__(parent, height=lab.px(CONTROL_H) + 2 * self.margin, width=lab.px(80),
                         highlightthickness=0, bd=0, cursor="hand2")
        self.name_font = tkfont.Font(root=lab.root, font=ui_font(10, medium=True))
        self.state_font = tkfont.Font(root=lab.root, font=ui_font(8, medium=True))
        self.bind("<Configure>", lambda _e: self.repaint())
        self.bind("<Enter>", lambda _e: self._set(hover=True))
        self.bind("<Leave>", lambda _e: self._set(hover=False, pressed=False))
        self.bind("<ButtonPress-1>", lambda _e: self._set(pressed=True))
        self.bind("<ButtonRelease-1>", self._release)
        lab.painters.append(self)

    def _set(self, **changes):
        for k, v in changes.items():
            setattr(self, k, v)
        self.repaint()

    def _release(self, _event):
        if self.pressed:
            self.value = self.ORDER[(self.ORDER.index(self.value) + 1) % 3]
        self._set(pressed=False)

    def repaint(self):
        p, px, m = self.lab.p, self.lab.px, self.margin
        w, h = max(self.winfo_width(), int(self.cget("width"))), int(self.cget("height"))
        self.configure(bg=p["CARD"])
        self.delete("all")
        if self.value == "ON":
            fill, border, ink = p["ON_HOVER"] if self.hover else p["ON"], None, p["ON_TEXT"]
        elif self.value == "OFF":
            fill, border, ink = p["OFF_HOVER"] if self.hover else p["OFF"], None, p["OFF_TEXT"]
        else:
            fill, border, ink = p["BTN_HOVER"] if self.hover else p["BTN"], p["BTN_LINE"], p["TEXT"]
        if self.pressed:
            fill = p["BTN_PRESSED"] if self.value is None else fill
        img = pill_image(w, h, px(RADIUS), fill, border, "raised", m, self.lab.scale)
        self._photo = ImageTk.PhotoImage(img, master=self)
        self.create_image(0, 0, image=self._photo, anchor="nw")
        cy = h / 2
        self.create_text(m + px(12), cy, text=self.text, anchor="w", font=self.name_font, fill=ink)
        if self.value:
            self.create_text(w - m - px(12), cy, text=self.value, anchor="e", font=self.state_font, fill=ink)


class StateButton(ttk.Button):
    """Cycles unset -> ON -> OFF like the parameter buttons."""

    ORDER = (None, "ON", "OFF")

    def __init__(self, parent, text, state=None):
        self.base, self.value = text, state
        super().__init__(parent, command=self.cycle, takefocus=0)
        self.apply()

    def cycle(self):
        self.value = self.ORDER[(self.ORDER.index(self.value) + 1) % 3]
        self.apply()

    def apply(self):
        style = {"ON": "StateOn.TButton", "OFF": "StateOff.TButton"}.get(self.value, "StateNeutral.TButton")
        self.configure(style=style, text=f"{self.base}   {self.value}" if self.value else self.base)


class Switch(tk.Canvas):
    """iOS-like switch drawn on a canvas."""

    def __init__(self, parent, lab):
        super().__init__(parent, width=lab.px(36), height=lab.px(22), highlightthickness=0, bd=0, cursor="hand2")
        self.lab, self.on = lab, False
        self.bind("<Button-1>", lambda _e: self.toggle())
        lab.painters.append(self)
        self.repaint()

    def toggle(self):
        self.on = not self.on
        self.repaint()

    def repaint(self):
        p, px = self.lab.p, self.lab.px
        w, h, s = px(36), px(22), SUPERSAMPLE
        img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, w * s - 1, h * s - 1], radius=h * s // 2,
                            fill=p["SWITCH_ON"] if self.on else p["SWITCH_OFF"])
        k = (h - 4) * s
        x = (w * s - k - 2 * s) if self.on else 2 * s
        d.ellipse([x, 2 * s, x + k, 2 * s + k], fill="#ffffff")
        self._photo = ImageTk.PhotoImage(img.resize((w, h), Image.Resampling.LANCZOS), master=self)
        self.configure(bg=p["CARD"])
        self.delete("all")
        self.create_image(0, 0, image=self._photo, anchor="nw")


class Diagram(tk.Canvas):
    """The body diagram with an onset dot, as in the right column of the app."""

    def __init__(self, parent, lab):
        self.lab = lab
        source = Image.open(DIAGRAM_PATH).convert("RGBA")
        w = lab.px(DIAGRAM_WIDTH)
        h = round(source.height * w / source.width)
        super().__init__(parent, width=w, height=h, highlightthickness=0, bd=0)
        self._photo = ImageTk.PhotoImage(source.resize((w, h), Image.Resampling.LANCZOS), master=self)
        self.create_image(0, 0, image=self._photo, anchor="nw")
        r, x, y = lab.px(6), 0.085 * w, 0.62 * h
        self.create_oval(x - r - 2, y - r - 2, x + r + 2, y + r + 2, fill="#ffffff", width=0)
        self.create_oval(x - r, y - r, x + r, y + r, fill="#21a453", width=0)
        lab.bind_colors(self, bg="DIAGRAM")


class Timeline(tk.Canvas):
    """Parameter and touch tracks with rounded ends, edges, a note and a playhead."""

    TOUCHES = ((0.06, 0.13), (0.22, 0.33), (0.47, 0.52), (0.71, 0.80))
    PARAMS = (("ON", 0.18, 0.27), ("OFF", 0.41, 0.47), ("ON", 0.63, 0.75))

    def __init__(self, parent, lab):
        super().__init__(parent, height=lab.px(96), highlightthickness=0, bd=0)
        self.lab, self.head = lab, 0.245
        self.bind("<Configure>", lambda _e: self.repaint())
        self.bind("<Button-1>", self.click)
        lab.painters.append(self)

    def click(self, event):
        self.head = min(1, max(0, event.x / max(1, self.winfo_width())))
        self.repaint()

    def step(self):
        self.head = (self.head + 0.01) % 1
        self.repaint()

    def pill(self, x0, y0, x1, y1, r, fill):
        # Rounded rectangle from rectangles and ovals (the canvas has no native rounding).
        self.create_rectangle(x0 + r, y0, x1 - r, y1, fill=fill, width=0)
        self.create_rectangle(x0, y0 + r, x1, y1 - r, fill=fill, width=0)
        for cx, cy in ((x0, y0), (x1 - 2 * r, y0), (x0, y1 - 2 * r), (x1 - 2 * r, y1 - 2 * r)):
            self.create_oval(cx, cy, cx + 2 * r, cy + 2 * r, fill=fill, width=0)

    def repaint(self):
        p, px = self.lab.p, self.lab.px
        self.configure(bg=p["CARD"])
        self.delete("all")
        w = self.winfo_width()
        if w < 10:
            return
        small = (FONT_FAMILY, 9)
        self.create_text(0, 0, text="Parameters", anchor="nw", fill=p["MUTED"], font=small)
        self.create_text(w, 0, text="LP1 · P2", anchor="ne", fill=p["MUTED"], font=small)
        y0, y1 = px(20), px(30)
        self.pill(0, y0, w - 1, y1, px(5), p["TRACK"])
        for kind, a, b in self.PARAMS:
            self.create_rectangle(a * w, y0, b * w, y1, fill=p[kind], width=0)
        self.create_text(0, px(40), text="Touches · Right Hand", anchor="nw", fill=p["MUTED"], font=small)
        self.create_text(w, px(40), text="4 touches", anchor="ne", fill=p["MUTED"], font=small)
        y0, y1 = px(60), px(94)
        self.pill(0, y0, w - 1, y1, px(8), p["TRACK"])
        for a, b in self.TOUCHES:
            xa, xb = a * w, b * w
            self.create_rectangle(xa, y0, xb, y1, fill=p["ON"], width=0)
            self.create_line(xa, y0, xa, y1, fill=p["ON_MARK"], width=px(2))
            self.create_line(xb, y0, xb, y1, fill=p["OFF_MARK"], width=px(2))
        self.create_line(0.58 * w, y0, 0.58 * w, y1, fill=p["NOTE"], width=px(2))
        x, r = self.head * w, px(5)
        self.create_line(x, y0 - px(4), x, y1 + px(1), fill=p["ACCENT"], width=px(2))
        self.create_oval(x - r, y0 - px(4) - r, x + r, y0 - px(4) + r, fill=p["ACCENT"], width=0)


def main():
    enable_dpi_awareness()
    root = tk.Tk()
    root.geometry("1860x1240")
    Lab(root)
    root.mainloop()


if __name__ == "__main__":
    main()
