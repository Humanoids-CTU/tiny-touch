"""Pure Touch display projections. These deliberately preserve the two views'
different historical rules: detail events require coordinates, overview events
use Onset alone; only closed overview intervals receive a fill.
"""

from dataclasses import dataclass


def parameter_state(params):
    values = (params or {}).values()
    if "ON" in values:
        return "ON"
    if "OFF" in values:
        return "OFF"
    return None


@dataclass(frozen=True, slots=True)
class FrameMarks:
    frame: int
    parameter: str | None
    limb_parameters: tuple
    note: bool


def frame_marks(frame, bundle, limb):
    params = bundle.get(limb, {}).get("LimbParams", {})
    return FrameMarks(
        frame, parameter_state(bundle.get("Params")),
        (params.get("Par1"), params.get("Par2"), params.get("Par3")),
        bool((bundle.get("Note") or "").strip()),
    )


@dataclass(frozen=True, slots=True)
class DetailTimeline:
    cells: tuple[str, ...]
    marks: tuple[FrameMarks, ...]
    active: bool
    carry: bool


def detail_timeline(frames, limb, total_frames, offset, frame_count, initial_touch=False):
    active = initial_touch
    cells, marks = [], []
    for frame in range(offset, offset + frame_count):
        bundle = frames.get(frame, {})
        details = bundle.get(limb, {})
        xs = details.get("X", [])
        if frame > total_frames:
            cell = "unavailable"
        elif xs and xs[0] is not None:
            active = details.get("Onset") == "ON"
            cell = "on" if active else "off"
        else:
            cell = "during" if active else "empty"
        cells.append(cell)
        marks.append(frame_marks(frame, bundle, limb))
    # The old detail view propagated only a DURING final cell, not an ON edge.
    return DetailTimeline(tuple(cells), tuple(marks), active, bool(cells and cells[-1] == "during"))


@dataclass(frozen=True, slots=True)
class OverviewTimeline:
    intervals: tuple[tuple[int, int], ...]
    onsets: tuple[int, ...]
    offsets: tuple[int, ...]
    marks: tuple[FrameMarks, ...]
    notes: tuple[int, ...]


def overview_timeline(frames, limb):
    intervals, onsets, offsets, marks = [], [], [], []
    active = None
    for frame in sorted(frames):
        bundle = frames[frame]
        onset = bundle.get(limb, {}).get("Onset")
        if onset == "ON":
            onsets.append(frame)
            if active is None:
                active = frame
        elif onset == "OFF":
            offsets.append(frame)
            if active is not None:
                intervals.append((active, frame))
                active = None
        marks.append(frame_marks(frame, bundle, limb))
    # Retain insertion order for overlapping note markers, independently of the
    # chronological event scan.
    notes = tuple(frame for frame, bundle in frames.items() if (bundle.get("Note") or "").strip())
    return OverviewTimeline(tuple(intervals), tuple(onsets), tuple(offsets), tuple(marks), notes)
