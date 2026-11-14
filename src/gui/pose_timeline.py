"""Cached Pose timelines using sparse data and bounded overview pixel bins."""
from math import ceil

from gui import theme, timeline
from gui.timeline_geometry import TimelineGeometry

POSE_DETAIL_HEIGHT = 50
POSE_OVERVIEW_HEIGHT = 30
BODY_COLOR = "#3b93d1"
HEAD_COLOR = "#cf83d8"


class PoseTimelineView:
    def __init__(self, canvas):
        self.canvas = canvas
        self.reset()

    def reset(self):
        self._key = None
        self._dirty = set()
        self._playhead = None

    def invalidate(self):
        self._key = None

    def changed(self, frame, events_changed=False):
        self._dirty.add(frame)

    def draw(self, index, total_frames, current_frame, *, offset=0, count=None):
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
            if overview:
                timeline.draw_touch_overview(self.canvas, g, index.overview(), max(1, total_frames))
            else:
                timeline.draw_touch_detail(self.canvas, g, index.detail(total_frames, offset, count), theme.TL_DURING)
            changed_bins = range(bins)
        else:
            changed_bins = {min(bins - 1, int((frame - offset) * bins / count))
                            for frame in self._dirty if offset <= frame < offset + count}
        for column in changed_bins:
            # Integer boundaries give every recorded frame exactly one bin.
            start = offset + ceil(column * count / bins)
            stop = min(total_frames + 1, offset + ceil((column + 1) * count / bins))
            marks = index.column(start, stop) if stop > start else None
            self._column(g, column, bins, marks)
        self._dirty.clear()
        self._key = key
        # Keep notes and rounded corners above the scale overlay.
        self.canvas.tag_raise("note_marker")
        self.canvas.tag_raise("track_corner")
        self._playhead = timeline.update_playhead(
            self.canvas, self._playhead,
            g.marker_position(current_frame if overview else current_frame - offset,
                              max(1, total_frames) if overview else count, centered=not overview),
            g.top, g.bottom)

    def _row(self, g, row):
        height = (g.bottom - g.top) / 2
        return g.top + row * height, height

    def _column(self, g, column, bins, marks):
        c = self.canvas
        tag = f"pose_column:{column}"
        c.delete(tag)
        if marks is None:
            return
        left, right = g.position(column, bins), g.position(column + 1, bins)
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
            c.create_rectangle(left, y1 - 1, max(left + 1, right), y2 + 1,
                               fill=color, outline="", tags=tag)
