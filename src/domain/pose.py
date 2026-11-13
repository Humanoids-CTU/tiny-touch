"""Independent Pose labels and painted-frame editing rules; no I/O or GUI.

Quality is one global label per frame, independent of joint ON/OFF events. Scale
carry belongs to a short-lived editing session, never to the saved labels.
"""

from dataclasses import dataclass
from enum import Enum
from math import isfinite


POSE_JOINTS = (
    "L_ANKLE", "R_ANKLE", "L_KNEE", "R_KNEE", "L_HIP", "R_HIP",
    "L_WRIST", "R_WRIST", "L_ELBOW", "R_ELBOW",
    "L_SHOULDER", "R_SHOULDER", "NECK",
)
SCALE_MIN = 0.5
SCALE_MAX = 1.5
SCALE_NEUTRAL = 1.0


class JointEvent(Enum):
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


def _joint(joint: str) -> None:
    if not isinstance(joint, str) or joint not in POSE_JOINTS:
        raise ValueError(f"Unknown Pose joint: {joint!r}")


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


class PoseLabels:
    """Sparse recorded labels. Reads do not create records or infer defaults.

    Read methods return immutable values. Clearing one kind of label never
    deletes another kind at the same frame/joint.
    """

    def __init__(self):
        self._events: dict[tuple[int, str], JointEvent] = {}
        self._quality: dict[int, float] = {}
        self._scales: dict[tuple[int, ScaleKind], ScaleLabel] = {}

    def event(self, frame: int, joint: str) -> JointEvent | None:
        _frame(frame)
        _joint(joint)
        return self._events.get((frame, joint))

    def quality(self, frame: int) -> float | None:
        _frame(frame)
        return self._quality.get(frame)

    def scale(self, frame: int, kind: ScaleKind) -> ScaleLabel | None:
        _frame(frame)
        _enum(kind, ScaleKind)
        return self._scales.get((frame, kind))

    def set_event(self, frame: int, joint: str, event: JointEvent | None,
                  *, displayed_frame: int | None) -> None:
        """Set/replace the boundary, or delete it with None; preserve quality."""
        _painted(frame, displayed_frame)
        _joint(joint)
        if event is None:
            self._events.pop((frame, joint), None)
        else:
            _enum(event, JointEvent)
            self._events[frame, joint] = event

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

    def active_joints(self, frame: int) -> frozenset[str]:
        """ON-inclusive/OFF-exclusive projection, recomputed after boundary edits.

        Repeated ON is idempotent; unmatched OFF leaves the joint inactive.
        Quality has no effect on interval membership.
        """
        _frame(frame)
        active = set()
        for (index, joint), event in sorted(self._events.items()):
            if index > frame:
                break
            if event is JointEvent.ON:
                active.add(joint)
            else:
                active.discard(joint)
        return frozenset(active)


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
