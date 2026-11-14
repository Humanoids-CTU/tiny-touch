"""Pure Touch display projections. These deliberately preserve the two views'
different historical rules: detail events require coordinates, overview events
use Onset alone; only closed overview intervals receive a fill.
"""

from domain.annotation_channel import AnnotationChannel, FrameMarks, DetailTimeline, OverviewTimeline


def parameter_state(params):
    values = (params or {}).values()
    if "ON" in values:
        return "ON"
    if "OFF" in values:
        return "OFF"
    return None


def frame_marks(frame, bundle, limb):
    params = bundle.get(limb, {}).get("LimbParams", {})
    return FrameMarks(
        frame, parameter_state(bundle.get("Params")),
        (params.get("Par1"), params.get("Par2"), params.get("Par3")),
        bool((bundle.get("Note") or "").strip()),
    )


def detail_timeline(frames, limb, total_frames, offset, frame_count, initial_touch=False):
    events, marks = [], []
    for frame in range(offset, offset + frame_count):
        bundle = frames.get(frame, {})
        details = bundle.get(limb, {})
        xs = details.get("X", [])
        # Touch's legacy detail contract requires coordinates. Missing Onset
        # with coordinates historically behaves as OFF.
        if xs and xs[0] is not None:
            events.append((frame, "ON" if details.get("Onset") == "ON" else "OFF"))
        marks.append(frame_marks(frame, bundle, limb))
    return AnnotationChannel(events).detail(total_frames, offset, frame_count, marks,
                                            initial_active=initial_touch)


def overview_timeline(frames, limb):
    events, marks = [], []
    for frame in sorted(frames):
        bundle = frames[frame]
        event = bundle.get(limb, {}).get("Onset")
        if event in ("ON", "OFF"):
            events.append((frame, event))
        marks.append(frame_marks(frame, bundle, limb))
    # Preserve insertion order of overlapping notes and Touch's Onset-only rule.
    notes = (frame for frame, bundle in frames.items() if (bundle.get("Note") or "").strip())
    return AnnotationChannel(events).overview(marks, notes)
