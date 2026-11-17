"""Pose interaction adapter: widgets, painting and deferred navigation arrival.

Domain objects own all annotation rules. This adapter never writes on refresh,
and consumes a navigation intent once, only after its destination is painted.
"""
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

from adapters.pose_diagram import render_pose_diagram, hit_zone, zone_positions
from domain.pose import ZoneEvent, ScaleKind, CARRY_NAVIGATION
from gui import theme
from gui.diagram_highlight import DiagramHighlighter
from gui.ui_components import CARD_CONTENT_PAD, CARD_HEAD_PAD
from gui.widgets import ElidingLabel

SCALE_STEP = .01
QUALITY_STEP = .01
ROW_GAP = 6           # design px above each readout row
CARD_BOTTOM_GAP = 10  # design px below the last Pose size slider
PILL_GAP = 6          # design px between the global parameter pills in Pose
UNSET_QUALITY_POSITION = 1.0  # where the quality slider rests while a frame has no quality


class PosePanel:
    def __init__(self, app):
        self.app = app
        self.session = app.pose_session
        self.pending = None
        self.syncing = False
        self.values = {}
        self.readouts = {}
        self.photo = None
        self.base_image = None
        self.image_key = None
        self.widgets = []
        app.frame_paint_listeners.append(self.painted)

    def detach(self):
        if self.painted in self.app.frame_paint_listeners:
            self.app.frame_paint_listeners.remove(self.painted)
        self.pending = None
        self._restore_parameter_layout()

    def build(self):
        app = self.app
        app.channel_selector = None
        px = theme.px
        inset = px(CARD_CONTENT_PAD)
        controls = app.mode_controls_frame
        ttk.Label(controls, text="Pose size", style="CardHead.TLabel").pack(
            anchor="w", padx=inset, pady=tuple(px(v) for v in CARD_HEAD_PAD))
        for kind in (ScaleKind.HEAD, ScaleKind.BODY):
            self._slider(controls, kind, kind.value.title(), .5, 1.5,
                         lambda value, k=kind: self.edit_scale(k, value), "Reset",
                         lambda k=kind: self.edit_scale(k, 1.0))
        ttk.Frame(controls, height=px(CARD_BOTTOM_GAP), style="Card.TFrame").pack()
        self._pose_parameter_layout()
        self._slider(app.limb_parameter_frame, "quality", "Quality · unset", 0, 1, self.edit_quality,
                     "Clear", lambda: self.edit_quality(None))
        self.refresh()

    def _pose_parameter_layout(self):
        """Quality spans the Parameters card; the global pills sit in one row below it.

        The card is built for Touch (channel column | global column); the
        original grid and pack options are kept and put back on detach.
        """
        app = self.app
        px = theme.px
        inset = px(CARD_CONTENT_PAD)
        frame = app.limb_parameter_frame
        grid = frame.master
        global_frame = app.par1_btn.master
        global_label = next(iter(grid.grid_slaves(row=1, column=1)), None)
        pills = (app.par1_btn, app.par2_btn, app.par3_btn)
        self._saved_layout = {
            "grid": [(w, w.grid_info()) for w in (app.limb_parameter_heading, frame, global_label, global_frame)
                     if w is not None],
            "pack": [(p, p.pack_info()) for p in pills],
        }
        app.limb_parameter_heading.grid_remove()
        frame.grid_configure(row=1, column=0, columnspan=2, padx=0, pady=(0, px(ROW_GAP)))
        if global_label is not None:
            global_label.grid_configure(row=2, column=0, columnspan=2, padx=inset)
        global_frame.grid_configure(row=3, column=0, columnspan=2, padx=inset)
        for index, pill in enumerate(pills):
            pill.pack_configure(side="left", fill="x", expand=True,
                                padx=(0 if index == 0 else px(PILL_GAP), 0))

    def _restore_parameter_layout(self):
        saved = self.__dict__.pop("_saved_layout", None)
        if not saved:
            return
        try:
            for widget, info in saved["grid"]:
                widget.grid(**{("in_" if key == "in" else key): value for key, value in info.items()})
            for widget, info in saved["pack"]:
                widget.pack_configure(**{key: value for key, value in info.items() if key != "in"})
        except tk.TclError:
            pass   # the window is being torn down

    def _slider(self, parent, key, label, low, high, command, action_text, action):
        px = theme.px
        inset = px(CARD_CONTENT_PAD)
        # Readout with a quiet text action on the right; the slider gets the full width below.
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill="x", padx=inset, pady=(px(ROW_GAP), 0))
        button = ttk.Button(row, text=action_text, style="CardLink.TButton", command=action, cursor="hand2")
        button.pack(side="right")
        self._bind_playback(button)
        self.widgets.append(button)
        text = ElidingLabel(row, text=label, style="CardSmall.TLabel")
        text.pack(side="left", fill="x", expand=True)
        self.readouts[key] = text
        value = tk.DoubleVar(master=parent, value=1)
        self.values[key] = value
        slider = ttk.Scale(parent, from_=low, to=high, variable=value, command=command,
                           style="Card.Horizontal.TScale")
        # The knob image has a transparent shadow margin; pull it out so the
        # track lines up with the text above.
        slider.pack(fill="x", padx=inset - px(theme.SHADOW_MARGIN))
        self._bind_playback(slider)
        self.widgets.append(slider)

    def _bind_playback(self, widget):
        # Run before ttk's class binding can activate a focused Reset button.
        def toggle(event):
            self.app.toggle_play(event)
            return "break"
        widget.bind("<space>", toggle)

    def active(self):
        return (getattr(self.app, "annotation_type", "Touch") == "Pose"
                and getattr(self.app, "pose_session", None) is self.session
                and self.app.video is not None)

    def _ready(self):
        return self.active() and self.app._lock_before_annotation()

    def annotation_changed(self, frame, *, repaint=True):
        """Single mutation hook; timeline adapters may update only this frame.

        `repaint=False` leaves the controls and diagram to the frame refresh
        that follows a paint anyway (throttled during playback).
        """
        self.app._annotation_version = getattr(self.app, "_annotation_version", 0) + 1
        callback = getattr(self.app, "_pose_annotation_changed", None)
        if callback is not None:
            callback(frame)
        if repaint:
            self.refresh()
            self.draw()

    def edit_scale(self, kind, value):
        if self.syncing or not self._ready():
            return
        frame = self.app.video.current_frame
        value = round(round(float(value) / SCALE_STEP) * SCALE_STEP, 10)
        self.session.scales.edit(frame, kind, value, displayed_frame=self.app.displayed_frame)
        self.annotation_changed(frame)

    def edit_quality(self, value):
        if self.syncing or not self._ready():
            return
        frame = self.app.video.current_frame
        value = None if value is None else round(round(float(value) / QUALITY_STEP) * QUALITY_STEP, 10)
        self.session.labels.set_quality(frame, value, displayed_frame=self.app.displayed_frame)
        self.annotation_changed(frame)

    def click(self, x, y, event):
        if not self.active():
            return
        zoom = self.app.diagram_scale
        body, head = self.display_scales()
        zone = hit_zone(x / zoom, y / zoom, body, head)
        if zone is None or not self._ready():
            return
        frame = self.app.video.current_frame
        self.session.labels.set_event(frame, zone, event, displayed_frame=self.app.displayed_frame)
        self.annotation_changed(frame)
        highlighter = getattr(self.app, "_highlighter", None)
        if highlighter is not None and event is not None:
            highlighter.flash(zone, theme.DOT_ONSET if event is ZoneEvent.ON else theme.DOT_OFFSET)

    def request_navigation(self, previous, destination, navigation):
        # Every navigation request replaces stale intent, including view-only requests.
        self.pending = (self.session, self.app.video, previous, destination, navigation)

    def painted(self, frame, _size):
        pending, self.pending = self.pending, None
        if pending is None or not self.active():
            return
        session, video, previous, destination, navigation = pending
        app = self.app
        if (session is not self.session or video is not app.video or destination != frame
                or app.video.current_frame != frame or app.displayed_frame != frame):
            return
        if navigation not in CARRY_NAVIGATION or frame <= previous:
            return
        # Carry is a mutation, but must not stop arrow-hold playback. The painted
        # guard was just checked; lock storage directly without pausing playback.
        if not app._lock_before_annotation(pause_navigation=False):
            return
        before = tuple(session.labels.scale(frame, kind) for kind in ScaleKind)
        session.scales.arrive(previous, frame, navigation, displayed_frame=frame)
        after = tuple(session.labels.scale(frame, kind) for kind in ScaleKind)
        if before != after:
            # Runs inside display_first_frame, before its frame-control refresh
            # (every step; at most 25/s while playing). A full redraw here would
            # run on every played frame, once per frame the scale is carried to.
            self.annotation_changed(frame, repaint=False)

    def display_scales(self):
        frame = self.app.video.current_frame
        return tuple((self.session.labels.scale(frame, kind).value
                      if self.session.labels.scale(frame, kind) is not None else 1.0)
                     for kind in ScaleKind)

    def refresh(self):
        if not self.active():
            return
        frame = self.app.video.current_frame
        self.syncing = True
        try:
            for kind in ScaleKind:
                label = self.session.labels.scale(frame, kind)
                if kind in self.values:
                    self._show(kind, label.value if label else 1.0)
                    suffix = f"{(label.value - 1) * 100:+.0f}% · {label.source.value}" if label else "unset (neutral preview)"
                    self._show_readout(kind, f"{kind.value.title()} · {suffix}")
            quality = self.session.labels.quality(frame)
            if "quality" in self.values:
                self._show("quality", quality if quality is not None else UNSET_QUALITY_POSITION)
                self._show_readout("quality", "Quality · unset" if quality is None else f"Quality · {quality:.2f}")
        finally:
            self.syncing = False

    # refresh() runs up to 25 times a second during playback; touching a slider
    # or label that did not change still costs Tk a redraw and a re-layout.
    def _show(self, key, value):
        variable = self.values[key]
        if variable.get() != value:
            variable.set(value)

    def _show_readout(self, key, text):
        shown = self.__dict__.setdefault("_readout_text", {})
        if shown.get(key) != text:
            self.readouts[key].config(text=text)
            shown[key] = text

    def draw_frame(self):
        """Per-frame repaint (playback, stepping): only the dots, like Touch.

        Falls back to the full draw when the figure itself must change (the
        frame's body/head scale differs) or someone cleared the canvas. A full
        draw on every frame wipes the canvas, re-creates the diagram image and
        zone labels, and makes the resize grip blink while it is restored.
        """
        if not self.active():
            return
        app = self.app
        body, head = self.display_scales()
        if ((body, head, app.diagram_scale) != self.image_key
                or not app.diagram_canvas.find_withtag("diagram")):
            self.draw()
            return
        self._draw_dots(body, head)

    def draw(self):
        if not self.active():
            return
        app = self.app
        body, head = self.display_scales()
        key = (body, head, app.diagram_scale)
        canvas = app.diagram_canvas
        if key != self.image_key:
            image = render_pose_diagram(body, head)
            size = app._diagram_display_size(app.diagram_scale)
            canvas.config(width=size[0], height=size[1])
            image = image.resize(size, Image.Resampling.LANCZOS)
            self.base_image = image.convert("RGB")
            self.photo = ImageTk.PhotoImage(image, master=canvas)
            self.image_key = key
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=self.photo, tags=("diagram",))
        highlight_key = ("pose", app.diagram_scale)
        if app._highlighter is None or app._highlighter_key != highlight_key:
            if app._highlighter is not None:
                app._highlighter.destroy()
            app._highlighter = DiagramHighlighter(canvas, app._zone_masks, app.diagram_scale,
                                                  self.base_image.size, app._hover_tooltip)
            app._highlighter.set_enabled(app.diagram_hover_effects)
            app._highlighter_key = highlight_key
        app._highlighter.set_base(self.base_image)
        app._highlighter.canvas_cleared()
        from gui.zone_labels import draw_zone_labels
        settings = getattr(app, "zone_display", None)
        if settings is not None:
            draw_zone_labels(canvas, settings, zone_positions(body, head), app.diagram_scale)
        self._draw_dots(body, head)

    def _draw_dots(self, body, head):
        app = self.app
        canvas = app.diagram_canvas
        canvas.delete("dot")
        frame = app.video.current_frame
        index = app._get_pose_timeline_index()
        active = index.active_zones(frame)
        for zone, (x, y) in zone_positions(body, head).items():
            event = self.session.labels.event(frame, zone)
            if event is None and zone not in active:
                continue
            color = theme.DOT_OFFSET if event is ZoneEvent.OFF else theme.DOT_ONSET
            canvas.create_image(x * app.diagram_scale, y * app.diagram_scale,
                                image=theme.dot_sprite(color, getattr(app, "dot_size", 10), hollow=event is None), tags=("dot",))
