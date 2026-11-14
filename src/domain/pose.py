"""Independent Pose labels and painted-frame editing rules; no I/O or GUI.

Quality is one global label per frame, independent of zone ON/OFF events. Scale
carry belongs to a short-lived editing session, never to the saved labels.
"""

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from domain.annotation_channel import active_targets


POSE_ZONES = tuple("ABCDEFGHIJKLMNOPQRST") + ("QB", "RB", "SB", "TB") + tuple(
    f"BOX{i}" for i in range(1, 7))
SCALE_MIN = 0.5
SCALE_MAX = 1.5
SCALE_NEUTRAL = 1.0


class ZoneEvent(Enum):
    ON = "ON"
    OFF = "OFF"


class ScaleKind(Enum):
    BODY = "body"
    HEAD = "head"


class ScaleSource(Enum):
    MANUAL = "manual"
    CARRIED = "carried"


class Navigation(Enum):
    FORWARD_STEP = "forward_step"
    FORWARD_HOLD = "forward_hold"
    PLAY = "play"
    BACKWARD = "backward"
    JUMP = "jump"
    REFRESH = "refresh"


def _frame(frame: int) -> None:
    if type(frame) is not int or frame < 0:
        raise ValueError("Frame must be a non-negative integer")


def _zone(zone: str) -> None:
    if not isinstance(zone, str) or zone not in POSE_ZONES:
        raise ValueError(f"Unknown Pose zone: {zone!r}")


def _enum(value, enum_type) -> None:
    if not isinstance(value, enum_type):
        raise ValueError(f"Expected {enum_type.__name__}, got {value!r}")


def _number(value: float, minimum: float, maximum: float) -> None:
    if (type(value) not in (int, float) or not minimum <= value <= maximum
            or not isfinite(value)):
        raise ValueError(f"Value must be finite and between {minimum} and {maximum}")


def _painted(frame: int, displayed_frame: int | None) -> None:
    _frame(frame)
    if displayed_frame is None:
        raise ValueError("No frame has been painted")
    _frame(displayed_frame)
    if displayed_frame != frame:
        raise ValueError("Target frame has not been painted")


@dataclass(frozen=True)
class ScaleLabel:
    value: float
    source: ScaleSource

    def __post_init__(self):
        _number(self.value, SCALE_MIN, SCALE_MAX)
        _enum(self.source, ScaleSource)


@dataclass(frozen=True)
class PoseSnapshot:
    """Immutable saved labels; no painted-frame or transient carry state.

    Records are (frame, zone, event), (frame, quality), and
    (frame, kind, scale label). Duplicate keys are invalid.
    """

    events: tuple[tuple[int, str, ZoneEvent], ...] = ()
    quality: tuple[tuple[int, float], ...] = ()
    scales: tuple[tuple[int, ScaleKind, ScaleLabel], ...] = ()

    def __post_init__(self):
        for rows, width in ((self.events, 3), (self.quality, 2), (self.scales, 3)):
            if type(rows) is not tuple or any(
                    type(row) is not tuple or len(row) != width for row in rows):
                raise ValueError("Snapshot records must be immutable tuples")
        event_keys, quality_keys, scale_keys = set(), set(), set()
        for frame, zone, event in self.events:
            _frame(frame)
            _zone(zone)
            _enum(event, ZoneEvent)
            if (frame, zone) in event_keys:
                raise ValueError("Duplicate zone event")
            event_keys.add((frame, zone))
        for frame, value in self.quality:
            _frame(frame)
            _number(value, 0.0, 1.0)
            if frame in quality_keys:
                raise ValueError("Duplicate frame quality")
            quality_keys.add(frame)
        for frame, kind, label in self.scales:
            _frame(frame)
            _enum(kind, ScaleKind)
            if not isinstance(label, ScaleLabel):
                raise ValueError("Expected a ScaleLabel")
            if (frame, kind) in scale_keys:
                raise ValueError("Duplicate frame scale")
            scale_keys.add((frame, kind))


class PoseLabels:
    """Sparse recorded labels. Reads do not create records or infer defaults.

    Read methods return immutable values. Clearing one kind of label never
    deletes another kind at the same frame/zone.
    """

    def __init__(self):
        self._events: dict[tuple[int, str], ZoneEvent] = {}
        self._quality: dict[int, float] = {}
        self._scales: dict[tuple[int, ScaleKind], ScaleLabel] = {}

    def snapshot(self) -> PoseSnapshot:
        """Capture labels independently of the active editing session."""
        return PoseSnapshot(
            events=tuple((frame, zone, event) for (frame, zone), event
                         in sorted(self._events.items())),
            quality=tuple(sorted(self._quality.items())),
            scales=tuple((frame, kind, label) for (frame, kind), label
                         in sorted(self._scales.items(),
                                   key=lambda item: (item[0][0], item[0][1].value))),
        )

    @classmethod
    def from_snapshot(cls, snapshot: PoseSnapshot) -> "PoseLabels":
        """Rehydrate validated storage without pretending any frame was painted.

        Interactive mutations still require an actually painted target frame.
        """
        if not isinstance(snapshot, PoseSnapshot):
            raise ValueError("Expected a PoseSnapshot")
        labels = cls()
        labels._events = {(frame, zone): event
                          for frame, zone, event in snapshot.events}
        labels._quality = dict(snapshot.quality)
        labels._scales = {(frame, kind): label
                          for frame, kind, label in snapshot.scales}
        return labels

    def event(self, frame: int, zone: str) -> ZoneEvent | None:
        _frame(frame)
        _zone(zone)
        return self._events.get((frame, zone))

    def quality(self, frame: int) -> float | None:
        _frame(frame)
        return self._quality.get(frame)

    def scale(self, frame: int, kind: ScaleKind) -> ScaleLabel | None:
        _frame(frame)
        _enum(kind, ScaleKind)
        return self._scales.get((frame, kind))

    def set_event(self, frame: int, zone: str, event: ZoneEvent | None,
                  *, displayed_frame: int | None) -> None:
        """Set/replace the boundary, or delete it with None; preserve quality."""
        _painted(frame, displayed_frame)
        _zone(zone)
        if event is None:
            self._events.pop((frame, zone), None)
        else:
            _enum(event, ZoneEvent)
            # Like Touch's whole-record Onset: the newest click determines
            # the single channel boundary for every target on this frame.
            for target in POSE_ZONES:
                if (frame, target) in self._events:
                    self._events[frame, target] = event
            self._events[frame, zone] = event

    def set_quality(self, frame: int, value: float | None,
                    *, displayed_frame: int | None) -> None:
        """Set/delete independent quality without creating or changing events."""
        _painted(frame, displayed_frame)
        if value is None:
            self._quality.pop(frame, None)
        else:
            _number(value, 0.0, 1.0)
            self._quality[frame] = float(value)

    def set_scale(self, frame: int, kind: ScaleKind, label: ScaleLabel | None,
                  *, displayed_frame: int | None) -> None:
        _painted(frame, displayed_frame)
        _enum(kind, ScaleKind)
        if label is None:
            self._scales.pop((frame, kind), None)
        elif not isinstance(label, ScaleLabel):
            raise ValueError("Expected a ScaleLabel or None")
        else:
            self._scales[frame, kind] = label

    def active_zones(self, frame: int) -> frozenset[str]:
        """Any OFF closes the global interval, regardless of its clicked zone."""
        _frame(frame)
        return active_targets(((index, event.value, zone)
                               for (index, zone), event in self._events.items()), frame)



class PoseScaleSession:
    """Independent body/head carry, initially inactive even for existing labels.

    Construct a fresh instance when opening a session. Control refreshes and
    view-only navigation must not initialize/change carry from displayed labels.
    """

    def __init__(self, labels: PoseLabels):
        self.labels = labels
        self._carry: dict[ScaleKind, float] = {}

    def carried_value(self, kind: ScaleKind) -> float | None:
        _enum(kind, ScaleKind)
        return self._carry.get(kind)

    def edit(self, frame: int, kind: ScaleKind, value: float,
             *, displayed_frame: int | None) -> None:
        label = ScaleLabel(value, ScaleSource.MANUAL)
        self.labels.set_scale(frame, kind, label, displayed_frame=displayed_frame)
        self._carry[kind] = float(value)

    def reset(self, frame: int, kind: ScaleKind,
              *, displayed_frame: int | None) -> None:
        self.edit(frame, kind, SCALE_NEUTRAL, displayed_frame=displayed_frame)

    def arrive(self, previous_frame: int, frame: int, navigation: Navigation,
               *, displayed_frame: int | None) -> None:
        """Call after a successful paint; only forward step/hold can write.

        Only this displayed destination is considered, never skipped frames.
        Manual labels are barriers that update carry independently per scale.
        """
        _frame(previous_frame)
        _frame(frame)
        _enum(navigation, Navigation)
        if navigation not in (Navigation.FORWARD_STEP, Navigation.FORWARD_HOLD):
            return
        _painted(frame, displayed_frame)
        if frame <= previous_frame:
            raise ValueError("Forward arrival must advance the frame")
        for kind in ScaleKind:
            existing = self.labels.scale(frame, kind)
            if existing is not None and existing.source is ScaleSource.MANUAL:
                self._carry[kind] = existing.value
            elif kind in self._carry:
                self.labels.set_scale(
                    frame, kind, ScaleLabel(self._carry[kind], ScaleSource.CARRIED),
                    displayed_frame=displayed_frame,
                )
