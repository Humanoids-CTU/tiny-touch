"""Independent Pose labels and painted-frame editing rules; no I/O or GUI.

Quality is one global label per frame, independent of zone ON/OFF events. Scale
and quality carry belong to a short-lived editing session, never to the saved labels.
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


# Forward navigation that carries head/body scale onto each painted frame.
CARRY_NAVIGATION = (Navigation.FORWARD_STEP, Navigation.FORWARD_HOLD, Navigation.PLAY)


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


def _scale_order(key):
    frame, kind = key
    return frame, kind.value


@dataclass(frozen=True)
class PoseChanges:
    """Labels edited since a tracked baseline: current values plus removed keys.

    `upserts` is a validated `PoseSnapshot` of the changed labels that still
    exist; the `deleted_*` tuples name keys that no longer exist. A key never
    appears in both.
    """

    upserts: PoseSnapshot = PoseSnapshot()
    deleted_events: tuple[tuple[int, str], ...] = ()
    deleted_quality: tuple[int, ...] = ()
    deleted_scales: tuple[tuple[int, ScaleKind], ...] = ()

    def __post_init__(self):
        if not isinstance(self.upserts, PoseSnapshot):
            raise ValueError("Expected a PoseSnapshot")
        for keys in (self.deleted_events, self.deleted_quality, self.deleted_scales):
            if type(keys) is not tuple:
                raise ValueError("Deleted keys must be immutable tuples")
        for frame, zone in self.deleted_events:
            _frame(frame)
            _zone(zone)
        for frame in self.deleted_quality:
            _frame(frame)
        for frame, kind in self.deleted_scales:
            _frame(frame)
            _enum(kind, ScaleKind)
        if (set(self.deleted_events) & {row[:2] for row in self.upserts.events}
                or set(self.deleted_quality) & {row[0] for row in self.upserts.quality}
                or set(self.deleted_scales) & {row[:2] for row in self.upserts.scales}):
            raise ValueError("A changed label cannot be both written and deleted")

    @property
    def is_empty(self) -> bool:
        upserts = self.upserts
        return not (upserts.events or upserts.quality or upserts.scales
                    or self.deleted_events or self.deleted_quality or self.deleted_scales)


@dataclass(frozen=True)
class PoseTables:
    """Detached copies of the three label tables, for bulk readers (the export).

    Keys are (frame, zone), frame and (frame, kind), as in `PoseLabels`; the
    values are immutable. Unlike `PoseSnapshot` nothing is sorted or validated
    again, so taking one costs milliseconds even for dense labels.
    """

    events: dict
    quality: dict
    scales: dict


class PoseLabels:
    """Sparse recorded labels. Reads do not create records or infer defaults.

    Read methods return immutable values. Clearing one kind of label never
    deletes another kind at the same frame/zone.

    Change tracking: every setter remembers the key it touched. A storage
    adapter calls `start_tracking()` once its store holds exactly these labels
    and keeps the returned token. Later, `pending_changes()` lists what differs
    from that baseline, and `mark_saved()` forgets it after a commit. The token
    lets the adapter tell whether this object's baseline is its own store: a new
    `start_tracking()` (for example by another store) issues a different token.
    """

    def __init__(self):
        self._events: dict[tuple[int, str], ZoneEvent] = {}
        self._quality: dict[int, float] = {}
        self._scales: dict[tuple[int, ScaleKind], ScaleLabel] = {}
        self._changed_events: set[tuple[int, str]] = set()
        self._changed_quality: set[int] = set()
        self._changed_scales: set[tuple[int, ScaleKind]] = set()
        self._tracking_token: object | None = None

    @property
    def tracking_token(self) -> object | None:
        """Opaque baseline identity; None until a store starts tracking."""
        return self._tracking_token

    def start_tracking(self) -> object:
        """Declare the current labels a store's baseline; forget older edits."""
        self._changed_events.clear()
        self._changed_quality.clear()
        self._changed_scales.clear()
        self._tracking_token = object()
        return self._tracking_token

    @property
    def has_pending_changes(self) -> bool:
        """True when any label was touched since the baseline (or ever, untracked)."""
        return bool(self._changed_events or self._changed_quality or self._changed_scales)

    def tables(self) -> PoseTables:
        """Detached label tables; later edits here never reach the copy."""
        return PoseTables(dict(self._events), dict(self._quality), dict(self._scales))

    def pending_changes(self) -> PoseChanges:
        """Edits since the baseline, in key order; cost follows the edit count."""
        events, quality, scales = self._events, self._quality, self._scales
        changed_events = sorted(self._changed_events)
        changed_quality = sorted(self._changed_quality)
        changed_scales = sorted(self._changed_scales, key=_scale_order)
        return PoseChanges(
            upserts=PoseSnapshot(
                events=tuple((frame, zone, events[frame, zone])
                             for frame, zone in changed_events if (frame, zone) in events),
                quality=tuple((frame, quality[frame])
                              for frame in changed_quality if frame in quality),
                scales=tuple((frame, kind, scales[frame, kind])
                             for frame, kind in changed_scales if (frame, kind) in scales),
            ),
            deleted_events=tuple(key for key in changed_events if key not in events),
            deleted_quality=tuple(frame for frame in changed_quality if frame not in quality),
            deleted_scales=tuple(key for key in changed_scales if key not in scales),
        )

    def mark_saved(self, changes: PoseChanges) -> None:
        """Forget saved changes, keeping keys edited again after their capture."""
        for frame, zone, event in changes.upserts.events:
            if self._events.get((frame, zone)) == event:
                self._changed_events.discard((frame, zone))
        for frame, value in changes.upserts.quality:
            if self._quality.get(frame) == value:
                self._changed_quality.discard(frame)
        for frame, kind, label in changes.upserts.scales:
            if self._scales.get((frame, kind)) == label:
                self._changed_scales.discard((frame, kind))
        for key in changes.deleted_events:
            if key not in self._events:
                self._changed_events.discard(key)
        for frame in changes.deleted_quality:
            if frame not in self._quality:
                self._changed_quality.discard(frame)
        for key in changes.deleted_scales:
            if key not in self._scales:
                self._changed_scales.discard(key)

    def snapshot(self) -> PoseSnapshot:
        """Capture labels independently of the active editing session."""
        return PoseSnapshot(
            events=tuple((frame, zone, event) for (frame, zone), event
                         in sorted(self._events.items())),
            quality=tuple(sorted(self._quality.items())),
            scales=tuple((frame, kind, label) for (frame, kind), label
                         in sorted(self._scales.items(),
                                   key=lambda item: _scale_order(item[0]))),
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
                    self._changed_events.add((frame, target))
            self._events[frame, zone] = event
        self._changed_events.add((frame, zone))

    def set_quality(self, frame: int, value: float | None,
                    *, displayed_frame: int | None) -> None:
        """Set/delete independent quality without creating or changing events."""
        _painted(frame, displayed_frame)
        if value is None:
            self._quality.pop(frame, None)
        else:
            _number(value, 0.0, 1.0)
            self._quality[frame] = float(value)
        self._changed_quality.add(frame)

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
        self._changed_scales.add((frame, kind))

    def active_zones(self, frame: int) -> frozenset[str]:
        """Any OFF closes the global interval, regardless of its clicked zone."""
        _frame(frame)
        return active_targets(((index, event.value, zone)
                               for (index, zone), event in self._events.items()), frame)



class PoseScaleSession:
    """Independent body/head/quality carry, initially inactive even for existing labels.

    Construct a fresh instance when opening a session. Control refreshes and
    view-only navigation must not initialize/change carry from displayed labels.
    """

    def __init__(self, labels: PoseLabels):
        self.labels = labels
        self._carry: dict[ScaleKind, float] = {}
        self._quality_carry: float | None = None
        # Quality has no stored provenance, so only frames this session carried
        # onto may be overwritten by a later carry; every other value is a barrier.
        self._quality_carried_frames: set[int] = set()

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

    def carried_quality(self) -> float | None:
        return self._quality_carry

    def quality_was_carried(self, frame: int) -> bool:
        """True when this session's carry wrote the frame's current quality."""
        _frame(frame)
        return frame in self._quality_carried_frames

    def edit_quality(self, frame: int, value: float | None,
                     *, displayed_frame: int | None) -> None:
        """Set quality and carry it forward like scale; None clears and stops carry."""
        self.labels.set_quality(frame, value, displayed_frame=displayed_frame)
        self._quality_carried_frames.discard(frame)
        self._quality_carry = None if value is None else float(value)

    def arrive(self, previous_frame: int, frame: int, navigation: Navigation,
               *, displayed_frame: int | None) -> None:
        """Call after a successful paint; only forward step/hold/play can write.

        Only this displayed destination is considered, never skipped frames.
        Manual labels are barriers that update carry independently per scale.
        Quality follows the same rule; a value this session did not carry is a
        barrier.
        """
        _frame(previous_frame)
        _frame(frame)
        _enum(navigation, Navigation)
        if navigation not in CARRY_NAVIGATION:
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
        existing = self.labels.quality(frame)
        if existing is not None and frame not in self._quality_carried_frames:
            self._quality_carry = existing
        elif self._quality_carry is not None:
            self.labels.set_quality(frame, self._quality_carry, displayed_frame=displayed_frame)
            self._quality_carried_frames.add(frame)
