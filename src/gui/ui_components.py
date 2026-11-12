"""
ui_components.py
All Tkinter widget construction, layout, and event bindings live here.
It takes a controller object (your LabelingApp instance) that already
implements the callback methods (e.g., load_video, on_timeline_click, etc.).
"""

import tkinter as tk
from tkinter import ttk
import sys

from domain.templates import get_template
from gui import theme
from gui import widgets
from gui.video_overlay import VideoBadge
from gui.diagram_resize import DiagramCanvas, DiagramResizeGrip, clamp_scale

# Width of the frame drawn around the diagram canvas (0: the card is the edge).
DIAGRAM_BORDER_PX = 0
# Screen height kept free of the diagram so its corner grip stays reachable:
# window caption, taskbar and the panel padding above the canvas. Used until
# the other right-column cards exist; then their real heights are reserved.
DIAGRAM_SCREEN_MARGIN_PX = 160
# Window caption plus taskbar, kept free when the diagram's maximum is
# computed from the right column's real contents (design px).
SCREEN_CHROME = 90
RESIZE_FIT_MS = 150               # window resize settles before the diagram re-fits

# Layout (design px, scaled with theme.px at build time).
WINDOW_SIZE = (1200, 1000)        # initial size before main.py maximizes
WINDOW_MIN_SIZE = (1100, 800)
WINDOW_SCREEN_MARGIN = 80         # keep scaled sizes inside the screen
WINDOW_PAD = 14                   # grey margin around everything
COLUMN_GAP = 14                   # between the main column and the right column
CARD_GAP = 4                      # between stacked cards (plus their shadow margins)
CARD_CONTENT_PAD = 14             # content inset inside a card
CARD_HEAD_PAD = (12, 6)           # above / below a card heading
STATUS_ROW_PAD = (8, 10)          # status line above / below
STATUS_ITEM_GAP = 16              # between status items
SIDE_MIN_WIDTH = 120              # right column floor; the diagram sets its width
# Smallest diagram the grip allows, as a fraction of its native size.
DIAGRAM_MIN_DRAG_SCALE = 0.5
NAV_MIN_SEG = 34                  # minimum width of a frame-navigation segment
TIMELINE2_HEIGHT = 30             # global scrub bar
TIMELINE_HEIGHT = 50              # 100-frame detail view
TIMELINE_GAP = 8
TIMELINE_ALIGN_MAX = 80           # follow the video's side letterbox up to this (design px)
NOTES_MIN_HEIGHT = 170            # notes card never shorter; it takes the column's spare height
NOTE_FIELD_PAD = 9
NOTE_WIDTH_CHARS = 1    # no width request: the column width comes from the diagram
NOTE_HEIGHT_LINES = 2
DIAGRAM_CARD_PAD = 0              # the diagram fills its card: every pixel is clickable
# Rim between the card edge and the diagram (design px): the smallest inset at
# which the card's rounded corners (CARD_RADIUS 12) never clip the diagram.
DIAGRAM_CARD_INSET = 4

# Frame navigation segments: value -> label (ASCII labels are part of the design).
NAV_ITEMS = (("jump_back", "<<"), ("back", "<"), ("select", "Select Frame"),
             ("forward", ">"), ("jump_forward", ">>"))
PLAY_ITEMS = (("play", "Play"), ("stop", "Stop"))


def _card_min_height(card):
    """A card's height at its content's requested size (the notes field at two lines)."""
    return card.inner.winfo_reqheight() + 2 * card._pad


def max_diagram_scale(app):
    """Largest diagram scale that leaves the rest of the right column its minimum height.

    The channel and parameter cards keep their size and the notes card keeps
    at least its two-line note field, all on one screen.
    """
    _, base_h = get_template(app.template).native_size
    try:
        screen_h = int(app.winfo_screenheight())
    except tk.TclError:
        return clamp_scale(float("inf"))
    others = [getattr(app, name, None) for name in ("channel_card", "parameter_card", "notes_card")]
    diagram_card = getattr(app, "diagram_card", None)
    if diagram_card is None or any(card is None for card in others):
        return clamp_scale((screen_h - DIAGRAM_SCREEN_MARGIN_PX) / float(base_h))
    px = theme.px
    # The window's real client height once it is up (maximized in practice);
    # before that, the screen minus caption and taskbar.
    available = screen_h - px(SCREEN_CHROME)
    try:
        if app.winfo_ismapped() and app.winfo_height() > px(WINDOW_MIN_SIZE[1]) // 2:
            available = app.winfo_height()
    except tk.TclError:
        pass
    reserve = (2 * px(WINDOW_PAD) + len(others) * px(CARD_GAP)
               + sum(_card_min_height(card) for card in others)
               + 2 * diagram_card._pad + 2 * px(DIAGRAM_CARD_PAD))
    return clamp_scale((available - reserve) / float(base_h))


def min_diagram_scale(app):
    """Smallest scale the grip allows (half the native size).

    The right column always takes the diagram's width (the other cards elide
    their text), so a small diagram never leaves unclickable strips.
    """
    return DIAGRAM_MIN_DRAG_SCALE


def fit_diagram_to_column(app):
    """Show the startup diagram within the column's limits (not saved).

    Smaller when it would squeeze the notes, larger when it would not span
    the column's width.
    """
    app.update_idletasks()   # the cards' requested sizes
    upper = max_diagram_scale(app)
    preferred = clamp_scale(app.config.diagram_scale)
    # The saved size, smaller when the window is too short for it (the
    # two-line notes win); it grows back when the window does.
    limit = min(preferred, upper)
    if abs(limit - app.diagram_scale) < 1e-6:
        return
    if hasattr(app, "apply_diagram_scale"):
        app.apply_diagram_scale(limit)
        return
    app.diagram_scale = limit
    w, h = (int(v * limit) for v in get_template(app.template).native_size)
    app.diagram_canvas.configure(width=w, height=h)
    app.diagram_canvas.delete("all")
    draw_startup_diagram(app, limit)


def _watch_window_height(app):
    """Re-fit the diagram (not saved) when the window's height changes."""
    state = {"height": None, "after": None}

    def settle():
        state["after"] = None
        fit_diagram_to_column(app)

    def on_configure(event):
        if event.widget is not app or event.height == state["height"]:
            return
        state["height"] = event.height
        if state["after"] is not None:
            app.after_cancel(state["after"])
        state["after"] = app.after(RESIZE_FIT_MS, settle)

    app.bind("<Configure>", on_configure, add="+")


def draw_startup_diagram(app, scale):
    """No video loaded: an empty white diagram of the template's size at `scale`.

    The canvas is already sized and DIAGRAM-coloured (white), so nothing is
    drawn; the diagram appears once a video has loaded.
    """
    app.photo = None


def _screen_fit(app, size):
    """Scale a design (w, h) and keep it inside the screen."""
    px = theme.px
    try:
        max_w = app.winfo_screenwidth() - px(WINDOW_SCREEN_MARGIN)
        max_h = app.winfo_screenheight() - px(WINDOW_SCREEN_MARGIN)
    except tk.TclError:
        return px(size[0]), px(size[1])
    return max(1, min(px(size[0]), max_w)), max(1, min(px(size[1]), max_h))


def build_ui(app):
    """
    Build all containers (frames), widgets, and bindings on the given app.
    The app is expected to be a tk.Tk (or Toplevel) and to provide all
    callback methods that are referenced here.
    """
    px = theme.px
    # === Root window basics ===
    app.title('TinyTouch')
    app.geometry('%dx%d' % _screen_fit(app, WINDOW_SIZE))
    app.minsize(*_screen_fit(app, WINDOW_MIN_SIZE))
    app.protocol("WM_DELETE_WINDOW", app.on_close)

    # === Top-level state used by the GUI ===
    app.photo = None
    app.pil_frame = None
    app.current_dot_item_id = [None]
    app.touch = False
    app.is_touch_timeline = False
    app.color_start = theme.TOUCH_START
    app.color_during = theme.TL_DURING
    app.color_end = theme.TOUCH_END
    app.frame_cache = {}
    app.image = None
    # The frame cache itself lives in adapters.frame_buffer.FrameBuffer
    # (constructed in LabelingApp.__init__), not on the widget tree.
    app.play = False
    app.progress = {}
    app.frame_rate = None
    app.last_mouse_x = 0
    app.last_mouse_y = 0

    # Diagram scale / dot size come from the AppConfig snapshot the app holds
    # (loaded once in LabelingApp.__init__) — the GUI never re-reads config.json.
    # A configured scale too large for this screen is shown smaller (not saved)
    # so the diagram's resize grip is on screen; dragging it stores the new value.
    scale = clamp_scale(app.config.diagram_scale, max_diagram_scale(app))
    app.diagram_scale = scale
    dot_size = app.config.dot_size
    app.dot_size = dot_size

    # === Containers ===
    # Toolbar + status line, the video card, the timeline card, and the right
    # column of cards. The video card's inner frame is the video panel itself.
    app.control_frame = ttk.Frame(app)
    # The video sits straight on the window: the frame itself is drawn with
    # rounded corners (LabelingApp / GpuVideoSurface), letterboxed on WIN.
    app.video_card = ttk.Frame(app)
    app.video_frame = theme.bind_colors(
        tk.Frame(app.video_card, bd=0, highlightthickness=0, width=1, height=1), bg="WIN")
    # The panel's size comes from the window, never from the frame on it:
    # without this the label/GPU child would drive the requested size.
    app.video_frame.pack_propagate(False)
    app.video_frame.pack(side="top", fill="both", expand=True)
    # The video name is a translucent badge blended onto the frame's top-right
    # corner by the renderer (LabelingApp._refresh_video_badge).
    app.name_label = VideoBadge("Video Name: -----", on_change=lambda: app._refresh_video_badge())
    app.timeline_card = widgets.RoundedCard(app)
    app.timeline_frame = app.timeline_card.inner
    app.diagram_frame = ttk.Frame(app)

    pad, gap = px(WINDOW_PAD), px(COLUMN_GAP)
    app.control_frame.grid(row=0, column=0, sticky="ew", padx=(pad, 0), pady=(pad, 0))
    app.video_card.grid(row=1, column=0, sticky="nsew", padx=(pad + px(theme.SHADOW_MARGIN), px(theme.SHADOW_MARGIN)))
    app.timeline_card.grid(row=2, column=0, sticky="ew", padx=(pad, 0), pady=(px(CARD_GAP), pad))
    app.diagram_frame.grid(row=0, column=1, rowspan=3, sticky="nsew", padx=(gap, pad), pady=pad)

    app.columnconfigure(0, weight=1)
    app.columnconfigure(1, minsize=px(SIDE_MIN_WIDTH) + gap + pad)
    app.rowconfigure(1, weight=1)
    app.rowconfigure(2, weight=0)

    # === Timeline canvases (one card) ===
    inset = px(CARD_CONTENT_PAD)
    app.timeline2_canvas = tk.Canvas(
        app.timeline_frame,
        height=px(TIMELINE2_HEIGHT),
        bd=0,
        highlightthickness=0,
    )
    app.timeline2_canvas.pack(fill=tk.X, expand=True, padx=inset, pady=(inset, px(TIMELINE_GAP) // 2))
    theme.bind_colors(app.timeline2_canvas, bg="CARD")
    app.timeline2_canvas.bind("<Button-1>", app.on_timeline2_click)

    app.timeline_canvas = tk.Canvas(
        app.timeline_frame,
        height=px(TIMELINE_HEIGHT),
        bd=0,
        highlightthickness=0,
    )
    app.timeline_canvas.pack(fill=tk.X, expand=True, padx=inset, pady=(px(TIMELINE_GAP) // 2, inset))
    theme.bind_colors(app.timeline_canvas, bg="CARD")
    app.timeline_canvas.bind("<Button-1>", app.on_timeline_click)
    # The timelines stretch with the window; redraw them at their new width.
    # (Their full redraw is skipped when the size and data are unchanged.)
    app.timeline2_canvas.bind("<Configure>", lambda _event: app.draw_timeline2())
    app.timeline_canvas.bind("<Configure>", lambda _event: app.draw_timeline())
    if sys.platform.startswith("linux"):
        app.bind("<Button-1>", app.global_click, add="+")   # safer on Linux
    else:
        app.bind_all("<Button-1>", app.global_click, add="+")  # keep Windows behavio

    # === Controls (top bar) ===
    _build_controls(app)

    # === Diagram panel (right column) ===
    _build_diagram_panel(app, scale)

    # === Bindings ===
    _bind_navigation(app)

    # === Resize behavior for video panel ===
    # add="+": RoundedCard keeps its own <Configure> handler on the inner frame.
    app.video_frame.bind('<Configure>', app.on_resize, add="+")


def _nav_command(app):
    actions = {
        "jump_back": lambda: app.next_frame(-app.jump_frame_count),
        "back": lambda: app.next_frame(-1),
        "select": app.select_frame,
        "forward": lambda: app.next_frame(1),
        "jump_forward": lambda: app.next_frame(app.jump_frame_count),
    }
    return lambda value: actions[value]()


def _play_command(app):
    def run(value):
        if value == "play":
            app.play_video()
        else:
            app.stop_video()
        sync_play_control(app)   # Play without a video falls back to Stop
    return run


def sync_play_control(app):
    """Select Play while the video plays (arrow-hold real-time included), Stop otherwise."""
    var = getattr(app, "play_state", None)
    if var is None:
        return
    want = "play" if getattr(app, "play", False) else "stop"
    if var.get() != want:
        var.set(want)


def align_timeline_to_video(app, indent):
    """Inset the timeline card and the toolbar by the video's side letterbox.

    The video frame, the timeline card and the toolbar / status rows then
    share one left and one right edge.

    Larger letterboxes (a narrow video in a wide window) keep the full width:
    the timeline stays long enough to scrub precisely.
    """
    px = theme.px
    if indent > px(TIMELINE_ALIGN_MAX):
        indent = 0
    if indent == getattr(app, "_timeline_indent", 0):
        return
    app._timeline_indent = indent
    pad = px(WINDOW_PAD)
    app.timeline_card.grid_configure(padx=(pad + indent, indent))
    app.control_frame.grid_configure(padx=(pad + indent, indent))


def _build_controls(app):
    px = theme.px
    gap = theme.toolbar_padx()

    # Row 1: actions on the left, frame navigation and playback on the right.
    top_row = ttk.Frame(app.control_frame)
    top_row.pack(fill="x")
    left_top = ttk.Frame(top_row)
    left_top.pack(side="left")

    app.load_video_btn = ttk.Button(
        left_top, text="Load Video", command=app.load_video, style="Tool.TButton", takefocus=0,
    )
    app.load_video_btn.pack(side="left", padx=(0, gap))
    settings_btn = ttk.Button(
        left_top, text="Settings", command=app.open_settings, style="Tool.TButton", takefocus=0,
    )
    settings_btn.pack(side="left", padx=(0, gap))
    app.special_zones_btn = ttk.Button(
        left_top, text="Special Zones", command=app.open_special_zones_app,
        style="Tool.TButton", takefocus=0,
    )
    app.special_zones_btn.pack(side="left", padx=(0, gap))
    app.analysis_btn = ttk.Button(
        left_top, text="Analysis", command=app.analysis, style="Tool.TButton", takefocus=0,
    )
    app.analysis_btn.pack(side="left", padx=(0, gap))
    app.save_btn = ttk.Button(
        left_top, text="Save", command=app.save_data, style="Tool.TButton", takefocus=0,
        state="disabled",   # enabled once a video has finished loading
    )
    app.save_btn.pack(side="left")

    app.play_state = tk.StringVar(app, value="stop")
    app.play_control = widgets.SegmentedControl(
        top_row, PLAY_ITEMS, variable=app.play_state, command=_play_command(app), gapless=True,
        icons={"play": "play", "stop": "stop"},
    )
    app.play_control.pack(side="right")
    app.frame_nav = widgets.SegmentedControl(
        top_row, NAV_ITEMS, command=_nav_command(app), min_seg=NAV_MIN_SEG,
    )
    app.frame_nav.pack(side="right", padx=(0, gap))
    app.frame_nav.set_enabled("select", False)   # enabled once a video is loaded
    app._selecting_frame = False

    # Row 2: status on the left, frame and time counters on the right.
    status_row = ttk.Frame(app.control_frame)
    margin = px(theme.SHADOW_MARGIN)
    status_row.pack(fill="x", padx=margin, pady=tuple(px(v) for v in STATUS_ROW_PAD))
    item_gap = (0, px(STATUS_ITEM_GAP))

    app.mode_label = widgets.StatusChip(status_row, label="Mode:", color=theme.STATUS_OK, text="-----")
    app.mode_label.pack(side="left", padx=item_gap)
    app.loading_label = widgets.StatusChip(status_row, label="Buffer:", color=theme.STATUS_OK, text="Loaded")
    app.loading_label.pack(side="left", padx=item_gap)

    # Keep the label for updates, but do not show it in the UI.
    app.framerate_label = ttk.Label(status_row, text="Frame Rate: -----", style="Status.TLabel")

    app.min_touch_length_label = ttk.Label(
        status_row, text="Minimal Touch Length: -----", style="Status.TLabel",
    )
    app.min_touch_length_label.pack(side="left", padx=item_gap)
    app.jump_label = ttk.Label(status_row, text="Jump: -----", style="Status.TLabel")
    app.jump_label.pack(side="left", padx=item_gap)

    # Packed right to left: frame counter, then time counter.
    app.time_counter_label = widgets.CounterLabel(status_row)
    app.time_counter_label.set("0", "0")
    app.time_counter_label.pack(side="right")
    app.frame_counter_label = widgets.CounterLabel(status_row)
    app.frame_counter_label.set(0, 0)
    app.frame_counter_label.pack(side="right", padx=item_gap)


def _card(parent, first=False):
    # The diagram card alone sets the column's width; the others follow it.
    card = widgets.RoundedCard(parent, fit_width=False)
    card.pack(side="top", fill="x", pady=(0 if first else theme.px(CARD_GAP), 0))
    return card


def _build_diagram_panel(app, scale):
    px = theme.px
    inset = px(CARD_CONTENT_PAD)
    head_pad = tuple(px(v) for v in CARD_HEAD_PAD)
    app.option_var_1 = tk.StringVar()
    app.option_var_1.set("RH")
    definition = get_template(app.template)
    base_w, base_h = definition.native_size
    w, h = int(base_w * scale), int(base_h * scale)

    # --- Diagram card ---
    # A DIAGRAM-coloured card: the diagram art is black on white, so its rim
    # stays white in dark mode too (in light mode DIAGRAM equals CARD).
    app.diagram_card = widgets.RoundedCard(app.diagram_frame, fill="DIAGRAM", shadow="card",
                                           pad=px(DIAGRAM_CARD_INSET))
    app.diagram_card.pack(side="top", fill="x")
    diagram_host = app.diagram_card.inner
    # The diagram keeps a holder frame: the resize grip is placed against it.
    app.diagram_border = tk.Frame(diagram_host, bd=0, highlightthickness=0)
    app.diagram_border.pack(padx=px(DIAGRAM_CARD_PAD), pady=px(DIAGRAM_CARD_PAD), side="top", anchor="n")
    theme.bind_colors(app.diagram_border, bg="DIAGRAM")

    app.diagram_canvas = DiagramCanvas(
        app.diagram_border,
        width=w,
        height=h,
        bd=0,
        highlightthickness=0,
    )
    app.diagram_canvas.pack(padx=DIAGRAM_BORDER_PX, pady=DIAGRAM_BORDER_PX)
    theme.bind_colors(app.diagram_canvas, bg="DIAGRAM")

    draw_startup_diagram(app, scale)

    # Drag the corner bracket in the card's bottom-left corner to resize the
    # diagram (aspect ratio kept); the controller redraws and persists the
    # scale (LabelingApp.commit_diagram_scale).
    app.diagram_grip = DiagramResizeGrip(
        app.diagram_canvas,
        native_size=lambda: get_template(app.template).native_size,
        get_scale=lambda: app.diagram_scale,
        max_scale=lambda: max_diagram_scale(app),
        min_scale=lambda: min_diagram_scale(app),
        on_preview=app.preview_diagram_scale,
        on_commit=app.commit_diagram_scale,
    )

    # Bind clicks on the diagram (these call back into the controller)
    # add="+": the grip has its own hover / drag bindings on the canvas.
    # Presses on the grip resize instead of placing a dot.
    grip = app.diagram_grip
    app.diagram_canvas.bind("<Motion>", app.update_last_mouse_position, add="+")
    app.diagram_canvas.bind("<Leave>", app.on_diagram_leave, add="+")
    app.diagram_canvas.bind(
        "<Button-3>", lambda event: None if grip.hit(event) else app.on_diagram_click(event, is_onset=False))
    app.diagram_canvas.bind(
        "<Button-1>",
        lambda event: None if grip.handle_press(event) else app.on_diagram_click(event, is_onset=True))
    app.diagram_canvas.bind("<Button-2>", app.on_middle_click)

    # --- Channel card (filled by LabelingApp.rebuild_annotation_controls) ---
    app.channel_card = _card(app.diagram_frame)
    app.mode_controls_frame = app.channel_card.inner

    # --- Parameters card ---
    app.parameter_card = _card(app.diagram_frame)
    parameter_box = app.parameter_card.inner
    parameter_box.columnconfigure(0, weight=1, uniform="parameters")
    parameter_box.columnconfigure(1, weight=1, uniform="parameters")
    left_pad, right_pad = (inset, px(4)), (px(4), inset)

    ttk.Label(parameter_box, text="Parameters", style="CardHead.TLabel").grid(
        row=0, column=0, columnspan=2, sticky="w", padx=inset, pady=head_pad)

    app.limb_parameter_heading = widgets.ElidingLabel(
        parameter_box, text=f"{definition.channel_noun}-specific", style="CardMuted.TLabel",
    )
    app.limb_parameter_heading.grid(row=1, column=0, sticky="ew", padx=left_pad)
    widgets.ElidingLabel(parameter_box, text="Global", style="CardMuted.TLabel").grid(
        row=1, column=1, sticky="ew", padx=right_pad)

    app.limb_parameter_frame = ttk.Frame(parameter_box, style="Card.TFrame")
    app.limb_parameter_frame.grid(row=2, column=0, sticky="new", padx=left_pad, pady=(0, px(10)))
    app.limb_par1_btn = None
    app.limb_par2_btn = None
    app.limb_par3_btn = None

    global_parameter_frame = ttk.Frame(parameter_box, style="Card.TFrame")
    global_parameter_frame.grid(row=2, column=1, sticky="new", padx=right_pad, pady=(0, px(10)))

    def pill(index, text):
        button = widgets.ParamPill(global_parameter_frame, text=text,
                                   command=lambda: app.parameter_dic_insert(index))
        button.pack(fill="x")
        return button

    app.par1_btn = pill(1, app.config.parameter1)
    app.par2_btn = pill(2, app.config.parameter2)
    app.par3_btn = pill(3, app.config.parameter3)

    # --- Notes card ---
    # The notes card takes the column's spare height, so its bottom lines up
    # with the timeline card; the note field grows with it.
    app.notes_card = widgets.RoundedCard(app.diagram_frame, fill_height=True, fit_width=False)
    app.notes_card.configure(height=px(NOTES_MIN_HEIGHT))
    app.notes_card.pack(side="top", fill="both", expand=True, pady=(px(CARD_GAP), 0))
    note_controls = app.notes_card.inner
    ttk.Label(note_controls, text="Notes", style="CardHead.TLabel").pack(
        anchor="w", padx=inset, pady=head_pad)

    note_field = widgets.RoundedCard(
        note_controls, fill="BTN", border="BTN_LINE", radius=theme.RADIUS, outer="CARD",
        pad=px(NOTE_FIELD_PAD), fill_height=True,
    )
    app.note_entry = tk.Text(
        note_field.inner,
        width=NOTE_WIDTH_CHARS,
        height=NOTE_HEIGHT_LINES,
        wrap="word",
        font=theme.FONT_SMALL,
        bd=0,
        padx=px(1),
        pady=0,
        spacing2=px(3),
        highlightthickness=0,
    )
    app.note_entry.pack(fill="both", expand=True)
    note_field.configure(height=app.note_entry.winfo_reqheight() + 2 * note_field._pad)
    theme.bind_colors(
        app.note_entry, bg="BTN", fg="NOTE_TEXT", insertbackground="TEXT",
        selectbackground="ACCENT", selectforeground="BTN",
    )

    note_button_row = ttk.Frame(note_controls, style="Card.TFrame")
    note_button_row.pack(side="bottom", fill="x", padx=inset, pady=(px(8), inset))
    note_field.pack(side="top", fill="both", expand=True, padx=inset)
    app.save_note_button = ttk.Button(
        note_button_row,
        text="Save Note",
        command=app.save_note,
        style="Card.Tool.TButton",
        takefocus=0,
    )
    app.save_note_button.pack(side="right")

    if hasattr(app, "rebuild_annotation_controls"):
        app.rebuild_annotation_controls()
    fit_diagram_to_column(app)
    # Card heights settle once the window is laid out, and the window can be
    # resized later: fit again whenever its height changes.
    _watch_window_height(app)


def _guard_key(app, cb):
    """Skip a global nav key action while a text editor holds focus.

    The keystroke still reaches the Entry (its class binding ran first in
    bindtag order); we only suppress the nav side effect. Returns None so no
    other binding is broken. The guard sits at the binding site — not inside
    the handler — because on_middle_click is also bound to <Button-2> on the
    canvas, which must keep working regardless of Note-entry focus.
    """
    def wrapped(event):
        if app._entry_has_focus():
            return
        return cb(event)
    return wrapped


def _bind_navigation(app):
    app.bind("<KeyPress-d>", _guard_key(app, app.on_middle_click))
    app.bind("<Left>", _guard_key(app, app.navigate_left))
    app.bind("<Right>", _guard_key(app, app.navigate_right))
    # Releases must still stop a hold when focus has moved into the note box.
    app.bind("<KeyRelease-Left>", lambda event: app._on_arrow_release(-1))
    app.bind("<KeyRelease-Right>", lambda event: app._on_arrow_release(1))
    app.bind("<FocusOut>", lambda event: app._cancel_arrow_hold_state(), add="+")
    app.bind("<Shift-Left>", _guard_key(app, lambda event: app.next_frame(-app.jump_frame_count)))
    app.bind("<Shift-Right>", _guard_key(app, lambda event: app.next_frame(app.jump_frame_count)))
    app.bind("<space>", _guard_key(app, app.toggle_play))

    # Wheel bindings: Windows/Mac vs Linux
    if sys.platform.startswith("linux"):
        # Wheel events on X11/Wayland commonly report as Button-4/5
        app.bind_all("<Button-4>", app.on_mouse_wheel)
        app.bind_all("<Button-5>", app.on_mouse_wheel)
    else:
        app.bind_all("<MouseWheel>", app.on_mouse_wheel)
