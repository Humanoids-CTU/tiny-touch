"""Shared timeline coordinates and click mapping, independent of annotation type."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TimelineGeometry:
    width: int
    height: int
    left: int = field(default=1, init=False)
    top: int = field(default=1, init=False)
    right: int = field(init=False)
    bottom: int = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "right", max(self.left + 1, self.width - 2))
        object.__setattr__(self, "bottom", max(self.top + 1, self.height - 2))

    def position(self, frame, frame_count, *, centered=False):
        return self.left + ((frame + (0.5 if centered else 0)) / frame_count) * (self.right - self.left)

    def marker_position(self, frame, frame_count, *, centered=False):
        x = self.position(frame, frame_count, centered=centered)
        return min(max(x, self.left + 4), self.right - 4)


def timeline_click_frame(x, canvas_width, frame_count, offset=0):
    """Retain canvas-wide seek mapping (distinct from inset drawing geometry)."""
    return int(x / canvas_width * frame_count) + offset
