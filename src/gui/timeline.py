"""Shared canvas decorations and Touch timeline rendering.

Receives explicit projections and geometry; never accesses the app controller.
"""
from PIL import Image, ImageDraw, ImageTk
from gui import theme
from gui.video_surface import rounded_corner_mask
from gui.timeline_geometry import TimelineGeometry
from domain.touch_timeline import detail_timeline, overview_timeline


# Timeline playhead dimensions in design pixels.
PLAYHEAD_CAP_W, PLAYHEAD_CAP_H = 10, 7
PLAYHEAD_CAP_ROUND = 1.5
PLAYHEAD_STEM_W = 2
PLAYHEAD_SUPERSAMPLE = 8
TIMELINE_CORNER_RADIUS = 6


class TouchTimelineView:
    """One canvas's content cache and playhead, with explicit Touch inputs.

    Invalidation keeps the displayed content until the next draw. Reset drops
    session keys and item IDs; it does not touch annotations or other widgets.
    """

    def __init__(self, canvas):
        self.canvas = canvas
        self.reset()

    def reset(self):
        self._key = None
        self._dirty = True
        self._playhead = None

    def invalidate(self):
        self._dirty = True

    def geometry(self):
        return TimelineGeometry(self.canvas.winfo_width(), self.canvas.winfo_height())

    def _needs_draw(self, key):
        return self._dirty or key != self._key

    def _content_drawn(self, key):
        self._key = key
        self._dirty = False
        self._playhead = None

    def draw_detail(self, frames, limb, total_frames, zone, frame_count, initial_touch, during_color, current_frame):
        g = self.geometry()
        key = (limb, zone, g.width, g.height)
        projection = None
        offset = zone * frame_count
        if self._needs_draw(key):
            projection = detail_timeline(frames, limb, total_frames, offset, frame_count, initial_touch)
            draw_touch_detail(self.canvas, g, projection, during_color)
            self._content_drawn(key)
        frame = current_frame - offset
        if 0 <= frame < frame_count:
            self._playhead = update_playhead(self.canvas, self._playhead,
                g.marker_position(frame, frame_count, centered=True), g.top, g.bottom)
        return projection

    def draw_overview(self, frames, limb, total_frames, current_frame):
        g = self.geometry()
        key = (limb, g.width, g.height)
        if self._needs_draw(key):
            draw_touch_overview(self.canvas, g, overview_timeline(frames, limb), total_frames)
            self._content_drawn(key)
        self._playhead = update_playhead(self.canvas, self._playhead,
            g.marker_position(current_frame, total_frames), g.top, g.bottom)


def parameter_color(state):
    if state == "ON":
        return theme.TL_PARAM_ON_MARK
    if state == "OFF":
        return theme.TL_PARAM_OFF_MARK
    return None


def draw_param_tick(canvas, x, top, bottom, color):
    return canvas.create_line(x, top, x, bottom, fill=color,
                              width=theme.TL_PARAM_MARK_WIDTH, dash=theme.TL_PARAM_MARK_DASH)


def _parameter_ticks(canvas, marks, x, geometry, *, global_marks=True):
    if global_marks:
        color = parameter_color(marks.parameter)
        if color:
            draw_param_tick(canvas, x, geometry.top, geometry.bottom, color)
    for dx, state in zip((-2, 0, 2), marks.limb_parameters):
        color = parameter_color(state)
        if color:
            draw_param_tick(canvas, x + dx, geometry.top, geometry.bottom, color)


def draw_touch_detail(canvas, geometry, projection, during_color):
    canvas.delete("all")
    g = geometry
    count = len(projection.cells)
    colors = {"on": theme.TL_ON, "off": theme.TL_OFF, "during": during_color,
              "empty": theme.TL_EMPTY, "unavailable": theme.TL_UNAVAILABLE}
    for i, (cell, marks) in enumerate(zip(projection.cells, projection.marks)):
        left, right = g.position(i, count), g.position(i + 1, count)
        canvas.create_rectangle(left, g.top, right, g.bottom, fill=colors[cell], outline="")
        if cell == "unavailable":
            canvas.create_line(left + 2, g.bottom - 2, right - 2, g.top + 2,
                               fill=theme.TL_UNAVAILABLE_MARK, width=1)
        _parameter_ticks(canvas, marks, (left + right) / 2, g)
    # Preserve the existing final-cell duplicate limb ticks and draw order.
    if projection.marks:
        _parameter_ticks(canvas, projection.marks[-1], (left + right) / 2, g, global_marks=False)
    canvas.create_rectangle(g.left, g.top, g.right, g.bottom, fill="", outline=theme.TL_OUTLINE)
    for i in range(1, count):
        x = g.position(i, count)
        canvas.create_line(x, g.top, x, g.bottom, fill=theme.TL_OUTLINE, width=1)
    for i, marks in enumerate(projection.marks):
        if marks.note:
            draw_note_marker(canvas, marks.frame, g.marker_position(i, count, centered=True), g.bottom)
    _round_track_corners(canvas, 0, 0, g.width, g.height)


def draw_touch_overview(canvas, geometry, projection, total_frames):
    canvas.delete("all")
    g = geometry
    canvas.create_rectangle(g.left, g.top, g.right, g.bottom, fill=theme.TL_EMPTY, outline=theme.TL_OUTLINE)
    for start, end in projection.intervals:
        x1, x2 = g.position(start, total_frames), g.position(end, total_frames)
        if x2 - x1 > 6:
            canvas.create_rectangle(x1 + 3, g.top + 1, x2 - 3, g.bottom - 1,
                                    fill=theme.TL_DURING, outline="")
    # Global marks precede all limb marks, then semantic edges and notes.
    for marks in projection.marks:
        color = parameter_color(marks.parameter)
        if color:
            draw_param_tick(canvas, g.position(marks.frame, total_frames), g.top, g.bottom, color)
    for marks in projection.marks:
        _parameter_ticks(canvas, marks, g.position(marks.frame, total_frames), g, global_marks=False)
    for frames, color in ((projection.onsets, theme.TL_ONSET_MARK), (projection.offsets, theme.TL_OFFSET_MARK)):
        for frame in frames:
            x = g.position(frame, total_frames)
            canvas.create_line(x, g.top, x, g.bottom, fill=color, width=2)
    for frame in projection.notes:
        draw_note_marker(canvas, frame, g.marker_position(frame, total_frames), g.bottom)
    _round_track_corners(canvas, 0, 0, g.width, g.height)

def _playhead_photo(canvas, height):
    """Antialiased playhead image `height` px tall, cached on the canvas."""
    color = theme.PLAYHEAD
    key = (height, color, theme.SCALE)
    cache = canvas.__dict__.setdefault("_playhead_photos", {})
    if key not in cache:
        s, px = PLAYHEAD_SUPERSAMPLE, theme.px
        # Even width with an even stem: the stem's centre is the image's centre.
        w = px(PLAYHEAD_CAP_W) // 2 * 2
        stem = max(2, px(PLAYHEAD_STEM_W) // 2 * 2)
        cap_h = min(height, px(PLAYHEAD_CAP_H))
        r = PLAYHEAD_CAP_ROUND * theme.SCALE * s
        big = Image.new("RGBA", (w * s, height * s), (0, 0, 0, 0))
        draw = ImageDraw.Draw(big)
        mid = w * s / 2
        draw.rectangle([mid - stem * s / 2, cap_h * s / 2, mid + stem * s / 2 - 1, height * s - 1], fill=color)
        # Downward triangle with rounded corners: an inset triangle stroked
        # with a round-joined line of the rounding radius.
        tri = [(r, r), (w * s - r, r), (mid, cap_h * s - r)]
        draw.polygon(tri, fill=color)
        draw.line(tri + [tri[0]], fill=color, width=round(2 * r), joint="curve")
        for cx, cy in tri:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
        cache[key] = ImageTk.PhotoImage(big.resize((w, height), Image.Resampling.LANCZOS), master=canvas)
    return cache[key]


def _round_track_corners(canvas, left, top, right, bottom):
    """Card-coloured corner masks over a timeline track's four corners.

    Drawn last in a full redraw (the playhead is raised above them), so the
    track reads as a rounded bar without changing how anything else is drawn.
    """
    r = min(theme.px(TIMELINE_CORNER_RADIUS), (right - left) // 2, (bottom - top) // 2)
    if r <= 0:
        return
    key = (r, theme.CARD)
    cache = canvas.__dict__.setdefault("_corner_photos", {})
    if key not in cache:
        corner = Image.new("RGBA", (r, r), theme.CARD)
        corner.putalpha(rounded_corner_mask(r))
        flips = (None, Image.Transpose.FLIP_LEFT_RIGHT, Image.Transpose.FLIP_TOP_BOTTOM,
                 Image.Transpose.ROTATE_180)
        cache[key] = [ImageTk.PhotoImage(corner if f is None else corner.transpose(f), master=canvas)
                      for f in flips]
    for (x, y), photo in zip(((left, top), (right - r, top), (left, bottom - r), (right - r, bottom - r)),
                             cache[key]):
        canvas.create_image(x, y, image=photo, anchor="nw", tags="track_corner")


def draw_note_marker(canvas, frame, x, bottom):
    """Keep frame notes distinct from full-height touch/parameter ticks."""
    canvas.create_polygon(
        x, bottom - 9, x + 4, bottom - 5,
        x, bottom - 1, x - 4, bottom - 5,
        fill=theme.TL_NOTE_MARK, outline="",
        tags=("note_marker", f"note_frame:{frame}"),
    )

def update_playhead(canvas, item_id, x, top, bottom):
    """Create or move the shared playhead: a rounded cap on a 2 px stem.

    It is one antialiased image (cached per height and colour), so cap and
    stem never snap apart, and the stem's centre sits exactly on `x`.
    """
    photo = _playhead_photo(canvas, max(1, int(bottom - top)))
    left = int(round(x)) - photo.width() // 2
    if item_id is None:
        return canvas.create_image(left, top, image=photo, anchor="nw")
    canvas.coords(item_id, left, top)
    if canvas.itemcget(item_id, "image") != str(photo):
        canvas.itemconfigure(item_id, image=photo)
    canvas.tag_raise(item_id)
    return item_id

