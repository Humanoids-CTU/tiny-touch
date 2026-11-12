"""App-level dialogs: close confirmation, labeling-mode picker, Settings.

The dialog functions take the ``LabelingApp`` as ``app``. Styled with the
shared theme roles and ``gui.widgets`` (grouped list, segmented control,
switch); behaviour and texts are those of the original labeling_app dialogs.
"""

import logging
import tkinter as tk
from tkinter import messagebox, ttk

from adapters import config
from adapters.config import MIN_VIDEO_DOWNSCALE
from domain.templates import TEMPLATE_LABELS
from domain.zone_display import ZoneDisplaySettings
from gui import theme
from gui.widgets import GroupedList, SegmentedControl, Switch

annotation_logger = logging.getLogger("annot")

# Settings dialog: which optional sections and rows are shown. The settings
# themselves keep working (config values, project data, and apply logic are
# untouched); these flags only hide the widgets from the Settings window.
SETTINGS_SHOW_ARROW_HOLD = False
SETTINGS_SHOW_HOVER_HIGHLIGHT = False
SETTINGS_SHOW_PARAMETER_LABELS = False
SETTINGS_SHOW_PROJECT_TEMPLATE = False
SETTINGS_SHOW_ZONE_NAME_EDITOR = False

# Layout (design px, scaled with theme.px).
DIALOG_PAD_X = 18
DIALOG_PAD_Y = 16
SECTION_GAP = 14          # space above a section heading (not the first)
SECTION_LABEL_GAP = 6     # heading -> card
SECTION_INDENT = 4        # headings and footer line up with the card's inner edge
FOOTER_GAP = 14           # last card -> footer
BUTTON_GAP = 0            # Tool/Primary buttons carry their own shadow margin
SETTINGS_ENTRY_WIDTH = 7          # chars, numeric fields
SETTINGS_LABEL_ENTRY_WIDTH = 18   # chars, parameter-label fields
SETTINGS_COMBO_WIDTH = 22         # chars, renderer combobox
SMALL_DIALOG_MIN_W = 380          # mode picker / close confirm minimum width
SETTINGS_MIN_W = 420              # Settings minimum width
ROW_CONTROL_GAP = 16              # minimum space between a row's text and its control
CONFIRM_WRAP = 340
TOGGLE_MIN_SEG = 84              # two-option toggles: roomy segments, like the channel grid


def center_over_parent(window, parent) -> None:
    """Place a realized dialog in the center of its parent window."""
    window.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - window.winfo_width()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - window.winfo_height()) // 2
    window.geometry(f"+{max(0, x)}+{max(0, y)}")


def _dialog_frame(win):
    px = theme.px
    content = ttk.Frame(win, padding=(px(DIALOG_PAD_X), px(DIALOG_PAD_Y)))
    content.pack(fill="both", expand=True)
    return content


def _footer(content, top_gap=FOOTER_GAP):
    px = theme.px
    foot = ttk.Frame(content)
    foot.pack(fill="x", side="bottom", pady=(px(top_gap), 0), padx=px(SECTION_INDENT))
    return foot


def custom_confirm_close(root) -> bool:
    px = theme.px
    win = tk.Toplevel(root)
    win.withdraw()
    win.title("Close Application")
    win.resizable(False, False)
    win.transient(root)
    theme.bind_colors(win, bg="WIN")
    win.minsize(px(SMALL_DIALOG_MIN_W), 1)

    confirmed = False

    content = _dialog_frame(win)
    ttk.Label(content, text="Do you want to close the application?", style="Title.TLabel",
              wraplength=px(CONFIRM_WRAP)).pack(anchor="w", padx=px(SECTION_INDENT))
    ttk.Label(content, text="Your progress will be saved.", style="Muted.TLabel",
              wraplength=px(CONFIRM_WRAP)).pack(anchor="w", padx=px(SECTION_INDENT), pady=(px(6), 0))

    def on_yes():
        nonlocal confirmed
        confirmed = True
        win.destroy()

    foot = _footer(content, top_gap=18)
    # Packed right-to-left: [Cancel] [OK]
    ttk.Button(foot, text="OK", command=on_yes, style="Primary.TButton", takefocus=0).pack(side="right")
    ttk.Button(foot, text="Cancel", command=win.destroy, style="Tool.TButton", takefocus=0).pack(
        side="right", padx=(0, px(BUTTON_GAP)))
    win.protocol("WM_DELETE_WINDOW", win.destroy)
    center_over_parent(win, root)
    win.deiconify()
    win.grab_set()  # modal; after deiconify so the grab never hits an unmapped window (Linux)
    win.wait_window()
    return confirmed


def ask_labeling_mode(app):
    """Modal mode picker. Returns "Normal" / "Reliability", or None when
    the window is closed without confirming.

    Deliberately side-effect free on the app: the caller commits the mode
    (app.labeling_mode + the mode chip) only once the load is actually
    going ahead, so cancelling a load can never leave the OPEN video
    tagged with a half-switched mode (its export metadata records
    app.labeling_mode on every save).
    """
    px = theme.px
    mode_window = tk.Toplevel(app)
    mode_window.withdraw()
    mode_window.title("Select Mode")
    mode_window.resizable(False, False)
    mode_window.transient(app)
    theme.bind_colors(mode_window, bg="WIN")
    mode_window.minsize(px(SMALL_DIALOG_MIN_W), 1)

    content = _dialog_frame(mode_window)
    ttk.Label(content, text="Choose labeling mode:", style="Title.TLabel").pack(
        anchor="w", padx=px(SECTION_INDENT), pady=(0, px(10)))
    cfg = config.load_config()
    labeling_var = tk.StringVar(master=mode_window,
                                value=getattr(app, "labeling_mode", cfg.get("last_labeling_mode", "Normal")))
    SegmentedControl(content, ("Normal", "Reliability"), variable=labeling_var,
                     gapless=True, min_seg=TOGGLE_MIN_SEG, bg="WIN").pack(anchor="w")

    chosen = {"mode": None}

    def set_mode():
        chosen["mode"] = labeling_var.get()
        # The preference default is fine to persist right away; it does
        # not touch the open video's state.
        cfg["last_labeling_mode"] = chosen["mode"]
        config.save_config(cfg)
        mode_window.destroy()

    foot = _footer(content, top_gap=18)
    ttk.Button(foot, text="Continue", command=set_mode, style="Primary.TButton", takefocus=0).pack(side="right")
    center_over_parent(mode_window, app)
    mode_window.deiconify()
    mode_window.grab_set()
    mode_window.wait_window()
    return chosen["mode"]


def _section(content, title, first=False):
    """Section heading + a fresh grouped-list card; returns the card."""
    px = theme.px
    ttk.Label(content, text=title, style="Section.TLabel").pack(
        anchor="w", padx=px(SECTION_INDENT), pady=(0 if first else px(SECTION_GAP), px(SECTION_LABEL_GAP)))
    group = GroupedList(content)
    group.pack(fill="x")
    return group


def _row(group, label, hint=None):
    """GroupedList row whose control keeps a gap from the row text."""
    holder = group.row(label, hint)
    holder.pack_configure(padx=(theme.px(ROW_CONTROL_GAP), 0))
    return holder


def open_settings(app):
    if getattr(app, "_settings_win", None) and app._settings_win.winfo_exists():
        app._settings_win.lift()
        return

    px = theme.px
    cfg = config.load_config()
    win = tk.Toplevel(app)
    win.withdraw()   # shown centred once built
    win.title("Settings")
    win.resizable(False, False)
    win.transient(app)
    theme.bind_colors(win, bg="WIN")
    win.minsize(px(SETTINGS_MIN_W), 1)
    app._settings_win = win

    content = _dialog_frame(win)

    def _v(key, default):
        return cfg.get(key, default)

    vars_map = {
        "appearance": tk.StringVar(value=app.config.appearance.title()),
        "video_renderer": tk.StringVar(value=(
            "CPU" if app.config.video_renderer == "cpu" else "Automatic (GPU preferred)")),
        "video_downscale": tk.StringVar(value=str(_v("video_downscale", 1.0))),
        # "diagram_scale": the diagram is resized by dragging its corner grip.
        "dot_size": tk.StringVar(value=str(_v("dot_size", 10))),
        "jump_seconds": tk.StringVar(value=str(_v("jump_seconds", 1.0))),
        "parameter1": tk.StringVar(value=str(_v("parameter1", "Parameter 1"))),
        "parameter2": tk.StringVar(value=str(_v("parameter2", "Parameter 2"))),
        "parameter3": tk.StringVar(value=str(_v("parameter3", "Parameter 3"))),
        "limb_parameter1": tk.StringVar(value=str(_v("limb_parameter1", "CP1"))),
        "limb_parameter2": tk.StringVar(value=str(_v("limb_parameter2", "CP2"))),
        "limb_parameter3": tk.StringVar(value=str(_v("limb_parameter3", "CP3"))),
        "realtime_arrow_hold": tk.BooleanVar(value=bool(_v("realtime_arrow_hold", True))),
        "diagram_hover_effects": tk.BooleanVar(value=bool(_v("diagram_hover_effects", True))),
    }

    show_zone_names = tk.BooleanVar(value=app.zone_display.show_names)

    def entry(holder, key, width=SETTINGS_ENTRY_WIDTH, state="normal"):
        field = ttk.Entry(holder, textvariable=vars_map[key], width=width, justify="right",
                          style="Card.TEntry", state=state)
        field.pack(side="right")
        return field

    # --- Display -----------------------------------------------------------
    display = _section(content, "DISPLAY", first=True)
    # Appearance is only applied on Save (apply_settings), not on click.
    SegmentedControl(_row(display, "Appearance"), ("Light", "Dark"), variable=vars_map["appearance"],
                     gapless=True, min_seg=TOGGLE_MIN_SEG, bg="CARD").pack(side="right")
    ttk.Combobox(
        _row(display, "Video renderer"), textvariable=vars_map["video_renderer"],
        values=("Automatic (GPU preferred)", "CPU"), state="readonly", width=SETTINGS_COMBO_WIDTH,
        style="Card.TCombobox",
    ).pack(side="right")
    ttk.Label(_row(display, "Active renderer"), textvariable=app._renderer_status,
              style="CardMuted.TLabel").pack(side="right")
    downscale_field = entry(_row(display, "Video downscale", "1 = full, 2 = half"), "video_downscale")

    def _clamp_downscale(_event=None):
        # 1 is full resolution; anything smaller (or not a number) becomes 1.0.
        try:
            ok = float(vars_map["video_downscale"].get()) >= MIN_VIDEO_DOWNSCALE
        except ValueError:
            ok = False
        if not ok:
            vars_map["video_downscale"].set(str(MIN_VIDEO_DOWNSCALE))

    downscale_field.bind("<FocusOut>", _clamp_downscale, add="+")
    # Diagram scale: set by dragging the grip in the diagram's bottom-left
    # corner (LabelingApp.commit_diagram_scale) instead of a field here.
    entry(_row(display, "Dot size"), "dot_size")
    entry(_row(display, "Fast-jump seconds", ">> / Shift+Arrow"), "jump_seconds")
    if SETTINGS_SHOW_ARROW_HOLD:
        from labeling_app import ARROW_HOLD_DELAY_MS  # lazy: labeling_app imports this module
        Switch(_row(display, "Hold arrows to play", f"{ARROW_HOLD_DELAY_MS} ms tap delay; target: video FPS"),
               variable=vars_map["realtime_arrow_hold"]).pack(side="right")
    if SETTINGS_SHOW_HOVER_HIGHLIGHT:
        Switch(_row(display, "Highlight the zone under the pointer"),
               variable=vars_map["diagram_hover_effects"]).pack(side="right")
    # Project-level toggle (saved with the project, not config.json), shown
    # under Display; it only takes effect while a video is loaded.
    zone_row = _row(display, "Show zone names on diagrams")
    Switch(zone_row, variable=show_zone_names,
           state="normal" if app.video is not None else "disabled").pack(side="right")
    if app.video is None:
        zone_row.label.configure(style="CardMuted.TLabel", font=theme.FONT_BASE)

    def parse_float(value, key):
        if value is None:
            return 0.0
        s = str(value).strip()
        if s == "":
            return 0.0
        try:
            return float(s)
        except Exception:
            raise ValueError(f"{key} must be a number")

    if app.video is not None and getattr(app, "coding_setup", None):
        for i in range(1, 4):
            vars_map[f"parameter{i}"].set(app.coding_setup.parameter_labels[f"Par{i}"])
            vars_map[f"limb_parameter{i}"].set(app.coding_setup.limb_parameter_labels[f"Par{i}"])

    # --- Parameter labels --------------------------------------------------
    if SETTINGS_SHOW_PARAMETER_LABELS:
        labels = _section(content, "PARAMETER LABELS")
        channel_noun = "Channel"
        coding_readonly = app.video is not None and app.state_repo.load_preparation_state() == "ready"
        state = "readonly" if coding_readonly else "normal"
        for i in range(1, 4):
            entry(_row(labels, f"{channel_noun} Parameter {i}"), f"limb_parameter{i}",
                  SETTINGS_LABEL_ENTRY_WIDTH, state)
        for i in range(1, 4):
            entry(_row(labels, f"Parameter {i}"), f"parameter{i}", SETTINGS_LABEL_ENTRY_WIDTH, state)

    # --- Project (project DB, not config.json) -----------------------------
    if app.video is not None and (SETTINGS_SHOW_PROJECT_TEMPLATE or SETTINGS_SHOW_ZONE_NAME_EDITOR):
        project = _section(content, "PROJECT")
        if SETTINGS_SHOW_PROJECT_TEMPLATE:
            template_state = app.state_repo.load_template()
            status = "locked after preparation" if template_state.locked else "changeable before preparation"
            ttk.Button(
                _row(project, f"Template: {TEMPLATE_LABELS[template_state.template]}", status),
                text="Change project template", command=app.change_project_template,
                style="Card.Tool.TButton", takefocus=0,
                state=tk.DISABLED if template_state.locked else tk.NORMAL,
            ).pack(side="right")
        if SETTINGS_SHOW_ZONE_NAME_EDITOR:
            ttk.Button(
                _row(project, "Zone names"), text="Edit zone names", command=app.edit_project_zone_names,
                state=tk.DISABLED if app.state_repo.load_preparation_state() == "ready" else tk.NORMAL,
                style="Card.Tool.TButton", takefocus=0,
            ).pack(side="right")

    def apply_settings(close=False):
        try:
            new_cfg = dict(cfg)
            new_cfg["appearance"] = vars_map["appearance"].get().lower()
            new_cfg["video_renderer"] = (
                "cpu" if vars_map["video_renderer"].get() == "CPU" else "auto")
            downscale = parse_float(vars_map["video_downscale"].get(), "video_downscale")
            if downscale < MIN_VIDEO_DOWNSCALE:
                downscale = MIN_VIDEO_DOWNSCALE
                vars_map["video_downscale"].set(str(downscale))
            new_cfg["video_downscale"] = downscale
            # The corner grip owns the diagram scale; write the live value so a
            # dialog opened before a drag does not restore the old size.
            new_cfg["diagram_scale"] = round(float(app.diagram_scale), 3)
            new_cfg["dot_size"] = parse_float(vars_map["dot_size"].get(), "dot_size")
            jump_seconds = parse_float(vars_map["jump_seconds"].get(), "jump_seconds")
            if jump_seconds <= 0:
                jump_seconds = 1.0
            new_cfg["jump_seconds"] = jump_seconds

            def _label_from(key, default):
                raw = vars_map[key].get()
                val = str(raw).strip() if raw is not None else ""
                return val if val else default

            new_cfg["parameter1"] = _label_from("parameter1", new_cfg.get("parameter1", "Parameter 1"))
            new_cfg["parameter2"] = _label_from("parameter2", new_cfg.get("parameter2", "Parameter 2"))
            new_cfg["parameter3"] = _label_from("parameter3", new_cfg.get("parameter3", "Parameter 3"))
            new_cfg["limb_parameter1"] = _label_from("limb_parameter1", new_cfg.get("limb_parameter1", "CP1"))
            new_cfg["limb_parameter2"] = _label_from("limb_parameter2", new_cfg.get("limb_parameter2", "CP2"))
            new_cfg["limb_parameter3"] = _label_from("limb_parameter3", new_cfg.get("limb_parameter3", "CP3"))
            new_cfg["realtime_arrow_hold"] = bool(vars_map["realtime_arrow_hold"].get())
            new_cfg["diagram_hover_effects"] = bool(vars_map["diagram_hover_effects"].get())
        except ValueError as e:
            messagebox.showerror("Invalid settings", str(e), parent=win)
            return

        config.save_config(new_cfg)
        app.apply_runtime_settings(new_cfg)
        for key, new_value in new_cfg.items():
            old_value = cfg.get(key)
            if old_value != new_value:
                annotation_logger.info(
                    "setting %s %r -> %r", key, old_value, new_value
                )
        cfg.clear()
        cfg.update(new_cfg)
        if app.video is not None and show_zone_names.get() != app.zone_display.show_names:
            if not app._save_zone_display(
                    ZoneDisplaySettings(app.zone_display.labels, show_zone_names.get())):
                return
        if close:
            win.destroy()

    # Save applies and closes; closing the window (title-bar X) discards.
    # The logs link is a quiet secondary action, kept apart from Save.
    foot = ttk.Frame(content)
    foot.pack(fill="x", pady=(px(FOOTER_GAP), 0), padx=px(SECTION_INDENT))
    logs_link = ttk.Label(foot, text="Open logs folder", style="Link.TLabel", cursor="hand2")
    logs_link.pack(side="left")
    logs_link.bind("<Button-1>", lambda _event: app._open_logs_folder())
    ttk.Button(foot, text="Save", command=lambda: apply_settings(close=True),
               style="Primary.TButton", takefocus=0).pack(side="right")
    center_over_parent(win, app)
    win.deiconify()
    # Shown after being built hidden: take the keyboard focus explicitly, or
    # typing keeps going to the main window.
    win.lift()
    win.focus_force()
