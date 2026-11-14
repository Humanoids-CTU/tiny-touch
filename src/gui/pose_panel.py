"""Pose interaction adapter: widgets, painting and deferred navigation arrival.

Domain objects own all annotation rules. This adapter never writes on refresh,
and consumes a navigation intent once, only after its destination is painted.
"""
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

from adapters.pose_diagram import render_pose_diagram, hit_zone, zone_positions
from domain.pose import ZoneEvent, Navigation, ScaleKind
from gui import theme
from gui.diagram_highlight import DiagramHighlighter

SCALE_STEP = .01
QUALITY_STEP = .01


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

    def build(self):
        app = self.app
        app.channel_selector = None
        app.limb_parameter_heading.config(text="Frame quality")
        pad = theme.px(12)
        ttk.Label(app.mode_controls_frame, text="Pose size", style="CardHead.TLabel").pack(anchor="w", padx=pad)
        for kind in (ScaleKind.HEAD, ScaleKind.BODY):
            self._slider(app.mode_controls_frame, kind, kind.value.title(), .5, 1.5,
                         lambda value, k=kind: self.edit_scale(k, value))
        self._slider(app.limb_parameter_frame, "quality", "Quality · unset", 0, 1, self.edit_quality)
        clear = ttk.Button(app.limb_parameter_frame, text="Clear quality", command=lambda: self.edit_quality(None))
        clear.pack(fill="x", padx=pad, pady=(0, pad))
        self._bind_playback(clear)
        self.widgets.append(clear)
        ttk.Label(app.mode_controls_frame, text="Left: ON · Right: OFF\nMiddle / d: delete event", style="Card.TLabel").pack(padx=pad, pady=pad)
        self.refresh()

    def _slider(self, parent, key, label, low, high, command):
        pad = theme.px(12)
        text = ttk.Label(parent, text=label, style="Card.TLabel")
        text.pack(anchor="w", padx=pad, pady=(pad, 0))
        self.readouts[key] = text
        value = tk.DoubleVar(master=parent, value=1 if isinstance(key, ScaleKind) else 0)
        self.values[key] = value
        slider = ttk.Scale(parent, from_=low, to=high, variable=value, command=command)
        slider.pack(fill="x", padx=pad, pady=(0, pad))
        self._bind_playback(slider)
        self.widgets.append(slider)
        if isinstance(key, ScaleKind):
            button = ttk.Button(parent, text=f"Reset {key.value}", command=lambda: self.edit_scale(key, 1.0))
            button.pack(fill="x", padx=pad)
            self._bind_playback(button)
            self.widgets.append(button)

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

    def annotation_changed(self, frame):
        """Single mutation hook; timeline adapters may update only this frame."""
        self.app._annotation_version = getattr(self.app, "_annotation_version", 0) + 1
        callback = getattr(self.app, "_pose_annotation_changed", None)
        if callback is not None:
            callback(frame)
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
        if navigation not in (Navigation.FORWARD_STEP, Navigation.FORWARD_HOLD) or frame <= previous:
            return
        # Carry is a mutation, but must not stop arrow-hold playback. The painted
        # guard was just checked; lock storage directly without pausing playback.
        if not app._lock_before_annotation(pause_navigation=False):
            return
        before = tuple(session.labels.scale(frame, kind) for kind in ScaleKind)
        session.scales.arrive(previous, frame, navigation, displayed_frame=frame)
        after = tuple(session.labels.scale(frame, kind) for kind in ScaleKind)
        if before != after:
            self.annotation_changed(frame)

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
                    self.values[kind].set(label.value if label else 1.0)
                    suffix = f"{(label.value - 1) * 100:+.0f}% · {label.source.value}" if label else "unset (neutral preview)"
                    self.readouts[kind].config(text=f"{kind.value.title()} · {suffix}")
            quality = self.session.labels.quality(frame)
            if "quality" in self.values:
                self.values["quality"].set(quality if quality is not None else 0)
                self.readouts["quality"].config(text="Quality · unset" if quality is None else f"Quality · {quality:.2f}")
        finally:
            self.syncing = False

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
