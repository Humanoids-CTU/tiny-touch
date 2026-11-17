"""Shared canvas decorations and Touch timeline rendering.

Receives explicit projections and geometry; never accesses the app controller.

A track's static content (cells, ticks, separators, rounded corners) is painted
into one pixel array (`gui.timeline_raster`) and shown as a single opaque
canvas image. Only the playhead and the clickable note markers are canvas
items, so a playhead move repaints one image strip whatever the track holds.
"""
from PIL import Image, ImageDraw, ImageTk
from gui import theme
from gui.timeline_geometry import TimelineGeometry
from gui.timeline_raster import TrackRaster
from domain.touch_timeline import detail_timeline, overview_timeline


# Timeline playhead dimensions in design pixels.
PLAYHEAD_CAP_W, PLAYHEAD_CAP_H = 10, 7
PLAYHEAD_CAP_ROUND = 1.5
PLAYHEAD_STEM_W = 2
PLAYHEAD_SUPERSAMPLE = 8
TIMELINE_CORNER_RADIUS = 6
# Canvas tag of the one image item that shows a track's static content.
TRACK_TAG = "track"
# Horizontal offsets of the three channel-parameter ticks around a frame's centre.
LIMB_TICK_OFFSETS = (-2, 0, 2)
# Onset / offset edge marks in the overview, in pixels.
EDGE_MARK_WIDTH = 2
# A closed interval is filled only when wider than this, inset by half of it.
OVERVIEW_INTERVAL_MIN_PX = 6


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


class _Ticks:
    """Parameter ticks collected per colour, global marks apart from channel marks.

    Drawing them per colour is one array operation each instead of one call
    per tick; channel ticks are painted after (over) all global ticks.
    """

    def __init__(self):
        self._global, self._limb = {}, {}

    def add(self, marks, x, *, global_marks=True):
        if global_marks:
            color = parameter_color(marks.parameter)
            if color:
                self._global.setdefault(color, []).append(x)
        for dx, state in zip(LIMB_TICK_OFFSETS, marks.limb_parameters):
            color = parameter_color(state)
            if color:
                self._limb.setdefault(color, []).append(x + dx)

    def paint(self, raster, geometry):
        for group in (self._global, self._limb):
            for color, xs in group.items():
                raster.vlines(xs, geometry.top, geometry.bottom, color,
                              width=theme.TL_PARAM_MARK_WIDTH, dash=theme.TL_PARAM_MARK_DASH)


def render_touch_detail(geometry, projection, during_color):
    """Paint the detail track; returns (raster, [(note frame, marker x), ...])."""
    g = geometry
    raster = TrackRaster(g.width, g.height, theme.CARD)
    count = len(projection.cells)
    colors = {"on": theme.TL_ON, "off": theme.TL_OFF, "during": during_color,
              "empty": theme.TL_EMPTY, "unavailable": theme.TL_UNAVAILABLE}
    ticks, notes = _Ticks(), []
    for i, (cell, marks) in enumerate(zip(projection.cells, projection.marks)):
        left, right = g.position(i, count), g.position(i + 1, count)
        raster.fill(left, g.top, right, g.bottom, colors[cell])
        if cell == "unavailable":
            raster.line(left + 2, g.bottom - 2, right - 2, g.top + 2, theme.TL_UNAVAILABLE_MARK)
        ticks.add(marks, (left + right) / 2)
        if marks.note:
            notes.append((marks.frame, g.marker_position(i, count, centered=True)))
    ticks.paint(raster, g)
    raster.outline(g.left, g.top, g.right, g.bottom, theme.TL_OUTLINE)
    raster.vlines([g.position(i, count) for i in range(1, count)], g.top, g.bottom, theme.TL_OUTLINE)
    return raster, notes


def render_touch_overview(geometry, projection, total_frames):
    """Paint the overview track; returns (raster, [(note frame, marker x), ...])."""
    g = geometry
    raster = TrackRaster(g.width, g.height, theme.CARD)
    raster.fill(g.left, g.top, g.right, g.bottom, theme.TL_EMPTY)
    raster.outline(g.left, g.top, g.right, g.bottom, theme.TL_OUTLINE)
    inset = OVERVIEW_INTERVAL_MIN_PX / 2
    for start, end in projection.intervals:
        x1, x2 = g.position(start, total_frames), g.position(end, total_frames)
        if x2 - x1 > OVERVIEW_INTERVAL_MIN_PX:
            raster.fill(x1 + inset, g.top + 1, x2 - inset, g.bottom - 1, theme.TL_DURING)
    # Global marks precede all limb marks, then semantic edges and notes.
    ticks = _Ticks()
    for marks in projection.marks:
        ticks.add(marks, g.position(marks.frame, total_frames))
    ticks.paint(raster, g)
    for frames, color in ((projection.onsets, theme.TL_ONSET_MARK), (projection.offsets, theme.TL_OFFSET_MARK)):
        raster.vlines([g.position(frame, total_frames) for frame in frames], g.top, g.bottom,
                      color, width=EDGE_MARK_WIDTH)
    notes = [(frame, g.marker_position(frame, total_frames)) for frame in projection.notes]
    return raster, notes


def rounded_track(raster):
    """The raster's pixels with the card colour over its four corners."""
    return raster.rounded(theme.px(TIMELINE_CORNER_RADIUS), theme.CARD)


def show_track_image(canvas, pixels):
    """Show `pixels` (height x width x 3, uint8) as the canvas's track image.

    The one place a track touches a Tk image. The photo is reused while the
    size holds (a paste, no new Tk image); the image item is created below
    everything else when the canvas has none.
    """
    image = Image.fromarray(pixels)
    canvas.__dict__["_track_pixels"] = pixels
    photo = canvas.__dict__.get("_track_photo")
    fresh = photo is None or (photo.width(), photo.height()) != image.size
    if fresh:
        photo = canvas.__dict__["_track_photo"] = ImageTk.PhotoImage(image, master=canvas)
    else:
        photo.paste(image)
    items = canvas.find_withtag(TRACK_TAG)
    if not items:
        canvas.tag_lower(canvas.create_image(0, 0, image=photo, anchor="nw", tags=TRACK_TAG))
    elif fresh:
        canvas.itemconfigure(items[0], image=photo)


def track_pixels(canvas):
    """The pixel array the canvas's track image currently shows (None before a draw)."""
    return canvas.__dict__.get("_track_pixels")


def present_track(canvas, pixels, notes, bottom):
    """Replace the canvas content: the track image, then its note markers."""
    canvas.delete("all")
    show_track_image(canvas, pixels)
    for frame, x in notes:
        draw_note_marker(canvas, frame, x, bottom)


def draw_touch_detail(canvas, geometry, projection, during_color):
    raster, notes = render_touch_detail(geometry, projection, during_color)
    present_track(canvas, rounded_track(raster), notes, geometry.bottom)


def draw_touch_overview(canvas, geometry, projection, total_frames):
    raster, notes = render_touch_overview(geometry, projection, total_frames)
    present_track(canvas, rounded_track(raster), notes, geometry.bottom)


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
