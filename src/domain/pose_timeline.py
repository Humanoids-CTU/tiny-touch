"""Sparse Pose display indexes; no inferred scale/quality labels or GUI state.

Build once on project open. Edits read only the changed frame; event boundaries
are indexed separately so playback never snapshots or sorts the saved labels.
"""
from bisect import bisect_left, bisect_right, insort
from dataclasses import dataclass

from domain.pose import POSE_ZONES, ZoneEvent, ScaleKind
from domain.touch_timeline import parameter_state
from domain.annotation_channel import AnnotationChannel, FrameMarks


class SparseTrack:
    def __init__(self):
        self.frames = []
        self.values = {}

    def set(self, frame, value):
        old = self.values.get(frame)
        if old == value:
            return False
        if value is None:
            if frame in self.values:
                del self.values[frame]
                self.frames.pop(bisect_left(self.frames, frame))
        else:
            if frame not in self.values:
                insort(self.frames, frame)
            self.values[frame] = value
        return True

    def between(self, start, stop):
        """Read a half-open interval from the sorted sparse keys."""
        return tuple((frame, self.values[frame]) for frame in
                     self.frames[bisect_left(self.frames, start):bisect_left(self.frames, stop)])

    def at_or_before(self, frame):
        position = bisect_right(self.frames, frame) - 1
        return self.values[self.frames[position]] if position >= 0 else None


@dataclass(frozen=True)
class PoseColumn:
    body: tuple[float, float] | None
    head: tuple[float, float] | None
    quality: tuple[float, float] | None
    active: int
    onset: bool
    offset: bool
    parameter: str | None
    note_frame: int | None


class PoseTimelineIndex:
    def __init__(self, labels, frames):
        self.labels = labels
        self.scales = {kind: SparseTrack() for kind in ScaleKind}
        self.quality = SparseTrack()
        self.events = {zone: SparseTrack() for zone in POSE_ZONES}
        self.channel = AnnotationChannel()
        self.notes = SparseTrack()
        self.parameters = SparseTrack()
        self.presentation_revision = 0
        snapshot = labels.snapshot()
        for frame, kind, label in snapshot.scales:
            self.scales[kind].set(frame, label)
        for frame, value in snapshot.quality:
            self.quality.set(frame, value)
        for frame, zone, event in snapshot.events:
            self.events[zone].set(frame, event)
        for frame in sorted({frame for track in self.events.values() for frame in track.frames}):
            self._update_boundary(frame)
        for frame, bundle in frames.items():
            self._update_shared(frame, bundle)

    def _update_shared(self, frame, bundle):
        changed = self.notes.set(frame, True if (bundle.get("Note") or "").strip() else None)
        changed |= self.parameters.set(frame, parameter_state(bundle.get("Params")))
        return changed

    def update(self, frame, bundle):
        """Refresh one frame and report whether subsequent zone state changed."""
        changed = False
        for zone, track in self.events.items():
            changed |= track.set(frame, self.labels.event(frame, zone))
        self._update_boundary(frame)
        for kind, track in self.scales.items():
            track.set(frame, self.labels.scale(frame, kind))
        self.quality.set(frame, self.labels.quality(frame))
        shared_changed = self._update_shared(frame, bundle)
        if changed or shared_changed:
            self.presentation_revision += 1
        return changed

    def _marks(self, frame):
        return FrameMarks(frame, self.parameters.values.get(frame), (), frame in self.notes.values)

    def detail(self, total_frames, offset, count):
        return self.channel.detail(total_frames, offset, count,
                                   (self._marks(f) for f in range(offset, offset + count)))

    def _update_boundary(self, frame):
        events = [track.values.get(frame) for track in self.events.values()]
        self.channel.set(frame, "OFF" if ZoneEvent.OFF in events else
                         "ON" if ZoneEvent.ON in events else None)

    def overview(self):
        return self.channel.overview((self._marks(f) for f in self.parameters.frames), self.notes.frames)

    def active_zones(self, frame):
        latest = self.channel.latest(frame)
        if latest is None or latest[1] != "ON":
            return frozenset()
        return frozenset(zone for zone, track in self.events.items()
                         if track.values.get(latest[0]) is ZoneEvent.ON)

    def active_count(self, frame):
        return len(self.active_zones(frame))

    def column(self, start, stop):
        """Summarize recorded points in one detail frame / overview pixel bin.

        Numeric extrema preserve zero and explicit neutral. A gap is None.
        Event ticks show both edge kinds even when their interval is sub-pixel.
        The active strip samples the bin's final frame; detail bins are exact.
        """
        def extent(rows):
            values = [value for _, value in rows]
            return (min(values), max(values)) if values else None

        scales = [extent((frame, label.value) for frame, label in track.between(start, stop))
                  for track in self.scales.values()]
        events = [event for track in self.events.values() for _, event in track.between(start, stop)]
        notes = self.notes.between(start, stop)
        params = dict(self.parameters.between(start, stop))
        return PoseColumn(*scales, extent(self.quality.between(start, stop)),
                          self.active_count(stop - 1), ZoneEvent.ON in events,
                          ZoneEvent.OFF in events, parameter_state(params),
                          notes[0][0] if notes else None)
