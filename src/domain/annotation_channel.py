"""One annotation channel's ON/OFF rules, shared by Touch and Pose.

Targets describe where a boundary occurred; they do not create extra channels.
Persistence and mode-specific frame values stay outside this module.
"""
from bisect import bisect_left, bisect_right, insort
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FrameMarks:
    frame: int
    parameter: str | None
    limb_parameters: tuple
    note: bool


@dataclass(frozen=True, slots=True)
class DetailTimeline:
    cells: tuple[str, ...]
    marks: tuple[FrameMarks, ...]
    active: bool
    carry: bool


@dataclass(frozen=True, slots=True)
class OverviewTimeline:
    intervals: tuple[tuple[int, int], ...]
    onsets: tuple[int, ...]
    offsets: tuple[int, ...]
    marks: tuple[FrameMarks, ...]
    notes: tuple[int, ...]


class AnnotationChannel:
    """Sparse, ordered boundaries for exactly one channel; no UI selection."""

    def __init__(self, events=()):
        self._events = dict(events)
        if any(event not in ("ON", "OFF") for event in self._events.values()):
            raise ValueError("Channel boundaries must be ON or OFF")
        self._frames = sorted(self._events)

    def set(self, frame, event):
        if event not in (None, "ON", "OFF"):
            raise ValueError("Channel boundaries must be ON or OFF")
        if event is None:
            if frame in self._events:
                del self._events[frame]
                self._frames.pop(bisect_left(self._frames, frame))
        else:
            if frame not in self._events:
                insort(self._frames, frame)
            self._events[frame] = event

    def latest(self, frame):
        position = bisect_right(self._frames, frame) - 1
        if position < 0:
            return None
        index = self._frames[position]
        return index, self._events[index]

    def active_before(self, frame):
        position = bisect_left(self._frames, frame) - 1
        return position >= 0 and self._events[self._frames[position]] == "ON"

    def detail(self, total_frames, offset, count, marks, *, initial_active=None):
        active = self.active_before(offset) if initial_active is None else initial_active
        cells = []
        for frame in range(offset, offset + count):
            event = self._events.get(frame)
            if frame > total_frames:
                cell = "unavailable"
            elif event is not None:
                active = event == "ON"
                cell = "on" if active else "off"
            else:
                cell = "during" if active else "empty"
            cells.append(cell)
        # Keep Touch's historical final-cell carry rule.
        return DetailTimeline(tuple(cells), tuple(marks), active,
                              bool(cells and cells[-1] == "during"))

    def overview(self, marks, notes):
        intervals, onsets, offsets = [], [], []
        start = None
        for frame in self._frames:
            if self._events[frame] == "ON":
                onsets.append(frame)
                if start is None:
                    start = frame
            else:
                offsets.append(frame)
                if start is not None:
                    intervals.append((start, frame))
                    start = None
        return OverviewTimeline(tuple(intervals), tuple(onsets), tuple(offsets),
                                tuple(marks), tuple(notes))


def active_targets(events, frame):
    """Targets of the latest boundary, matching Touch's last-open-onset dots."""
    rows = [(index, event, target) for index, event, target in events if index <= frame]
    latest = max((index for index, _, _ in rows), default=-1)
    current = [(event, target) for index, event, target in rows if index == latest]
    if any(event == "OFF" for event, _ in current):
        return frozenset()
    return frozenset(target for event, target in current if event == "ON")
