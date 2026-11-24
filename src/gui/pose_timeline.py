"""Cached Pose timelines using sparse data and bounded overview pixel bins."""
from math import ceil
import time

from gui import theme, timeline
from gui.timeline_geometry import TimelineGeometry

POSE_DETAIL_HEIGHT = 50
POSE_OVERVIEW_HEIGHT = 30
BODY_COLOR = "#3b93d1"
HEAD_COLOR = "#cf83d8"
# Quality band along the bottom of each Pose track: red at 0, green at 1.
# A middle stop keeps 0.5 a clear amber instead of a muddy red/green mix.
QUALITY_BAD_COLOR = (0xe0, 0x4a, 0x3f)
QUALITY_MID_COLOR = (0xe8, 0xb0, 0x30)
QUALITY_GOOD_COLOR = (0x3f, 0xb9, 0x5a)
QUALITY_BAND_HEIGHT = 6   # design px
QUALITY_BAND_GAP = 4      # design px kept clear between the lowest scale trace and the band
# While playing, scale traces carried onto played frames reach the screen at
# most this often: every update re-sends the track image to Tk (about 1 ms per
# canvas), which a 100 FPS frame cannot afford twice. Pauses, stalls, steps and
# edits show them at once.
POSE_TRACK_FLUSH_INTERVAL_S = 0.1
# The detail track shows each frame as a wide column, so a 0.1 s batch leaves a
# visible gap behind the playhead (the quality band most of all). It flushes
# about once per 25 FPS frame instead; the overview keeps the longer batch.
POSE_DETAIL_FLUSH_INTERVAL_S = 0.04


class PoseTimelineView:
    """One Pose track: a static picture plus scale/quality columns painted into it.

    `_base` is the Touch-style content (cells, ticks, edges); `_raster` adds
    the head/body scale traces and the quality band. A changed column is restored from `_base` and
    repainted in the array, then the whole picture goes to the canvas's single
    track image (`flush`). Note markers and the playhead are canvas items.
    """

    def __init__(self, canvas, flush_interval=POSE_TRACK_FLUSH_INTERVAL_S):
        self.canvas = canvas
        self.flush_interval = flush_interval
        self.reset()

    def reset(self):
        self._key = None
        self._dirty = set()
        self._playhead = None
        self._base = None      # static content, without scale columns
        self._raster = None    # what the canvas shows (before corner rounding)
        self._columns = {}     # column -> drawn (head, body) extents
        self._stale = False    # _raster changed since it was last shown
        self._shown_at = 0.0

    def invalidate(self):
        self._key = None

    def changed(self, frame, events_changed=False):
        self._dirty.add(frame)

    def draw(self, index, total_frames, current_frame, *, offset=0, count=None, defer=False):
        """Bring the track up to date and move the playhead.

        `defer` (a played frame) lets changed scale columns wait up to
        `flush_interval` before they are shown.
        """
        overview = count is None
        count = total_frames + 1 if overview else count
        if count <= 0:
            return
        g = TimelineGeometry(self.canvas.winfo_width(), self.canvas.winfo_height())
        bins = min(count, max(1, int(g.right - g.left))) if overview else count
        key = (id(index), total_frames, offset, count, bins, g.width, g.height,
               theme.TL_EMPTY, theme.TL_OUTLINE, theme.TL_PARAM_ON_MARK, index.presentation_revision)
        full = key != self._key
        if full:
            self._playhead = None
            self._columns = {}
            if overview:
                self._base, notes = timeline.render_touch_overview(
                    g, index.overview(), max(1, total_frames))
            else:
                self._base, notes = timeline.render_touch_detail(
                    g, index.detail(total_frames, offset, count), theme.TL_DURING)
            self._raster = self._base.copy()
            changed_bins = range(bins)
        else:
            changed_bins = {min(bins - 1, int((frame - offset) * bins / count))
                            for frame in self._dirty if offset <= frame < offset + count}
        for column in changed_bins:
            # Integer boundaries give every recorded frame exactly one bin.
            start = offset + ceil(column * count / bins)
            stop = min(total_frames + 1, offset + ceil((column + 1) * count / bins))
            marks = index.column(start, stop) if stop > start else None
            if self._column(g, column, bins, marks):
                self._stale = True
        self._dirty.clear()
        self._key = key
        if full:
            timeline.present_track(self.canvas, timeline.rounded_track(self._raster), notes, g.bottom)
            self._stale = False
            self._shown_at = time.perf_counter()
        elif self._stale and (
                not defer or time.perf_counter() - self._shown_at >= self.flush_interval):
            self.flush()
        self._playhead = timeline.update_playhead(
            self.canvas, self._playhead,
            g.marker_position(current_frame if overview else current_frame - offset,
                              max(1, total_frames) if overview else count, centered=not overview),
            g.top, g.bottom)

    def flush(self):
        """Show scale columns that a played frame left waiting."""
        if self._stale and self._raster is not None:
            timeline.show_track_image(self.canvas, timeline.rounded_track(self._raster))
            self._stale = False
            self._shown_at = time.perf_counter()

    def _band_top(self, g):
        return max(g.top + 1, g.bottom - theme.px(QUALITY_BAND_HEIGHT))

    def _row(self, g, row):
        height = (self._band_top(g) - theme.px(QUALITY_BAND_GAP) - g.top) / 2
        return g.top + row * height, height

    def _column(self, g, column, bins, marks):
        """(Re)paint one column in the array; True when its pixels changed."""
        drawn = None if marks is None else (marks.head, marks.body, marks.quality)
        if column in self._columns and self._columns[column] == drawn:
            return False   # e.g. a carry into an overview bin that already shows it
        previous = self._columns.get(column)
        self._columns[column] = drawn
        blank = (None, None, None)
        if (previous or blank) == blank and (drawn or blank) == blank:
            return False   # nothing was painted here and nothing is now
        left, right = g.position(column, bins), g.position(column + 1, bins)
        right = max(left + 1, right)
        x1, x2 = int(round(left)), int(round(right))
        self._raster.pixels[:, x1:x2] = self._base.pixels[:, x1:x2]
        if marks is None:
            return True
        for row, extent, color in ((0, marks.head, HEAD_COLOR),
                                   (1, marks.body, BODY_COLOR)):
            top, height = self._row(g, row)
            if extent is None:
                continue
            low, high = extent
            low, high = low - .5, high - .5
            bottom = top + height * .96
            y1, y2 = bottom - high * height * .54, bottom - low * height * .54
            # A point/neutral/zero remains visible; no line crosses unset gaps.
            self._raster.fill(left, y1 - 1, right, y2 + 1, color)
        if marks.quality is not None:
            # A bin's worst quality wins so short bad stretches stay visible.
            self._raster.fill(left, self._band_top(g), right, g.bottom,
                              quality_color(marks.quality[0]))
        return True


def quality_color(value):
    """Hex color from QUALITY_BAD_COLOR (0) via QUALITY_MID_COLOR to QUALITY_GOOD_COLOR (1)."""
    value = min(1.0, max(0.0, value))
    low, high = ((QUALITY_BAD_COLOR, QUALITY_MID_COLOR) if value < .5
                 else (QUALITY_MID_COLOR, QUALITY_GOOD_COLOR))
    t = value * 2 if value < .5 else value * 2 - 1
    return "#" + "".join(f"{round(a + (b - a) * t):02x}" for a, b in zip(low, high))
