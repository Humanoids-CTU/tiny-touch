"""Headless Pose workspace saving and restoration (database only).

The Pose export that follows each GUI save lives in `pose_export_service`.

The GUI owns its repository; standalone callers may open a session from paths.
Close only releases storage, so callers explicitly save before detaching.
"""

from copy import deepcopy
import math

from adapters.pose_sqlite_repo import PoseSqliteRepository
from domain.pose import PoseScaleSession
from domain.project import ProjectPaths
from domain.touch import zones_at


def _nonnegative_frame(value):
    if type(value) is not int or value < 0:
        raise ValueError("Frame must be a nonnegative integer")
    return value


def _finite(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("Expected a finite number")
    if value < 0 or positive and value == 0:
        raise ValueError("Value outside its allowed range")
    return value


def special_zone_rows(dots, scale, masks):
    """Freeze project-wide diagram points in the dialog's coordinate system."""
    _finite(scale, positive=True)
    return tuple((dot_id, x, y, ",".join(zones_at(masks, x / scale, y / scale)))
                 for dot_id, (x, y) in dots.items())


class PoseProjectSession:
    def __init__(self, paths: ProjectPaths):
        self._repo = PoseSqliteRepository(paths.pose_state_db)
        try:
            self.labels = self._repo.load()
            self._load_special_zones()
        except Exception:
            self._repo.close()
            raise
        # Saved labels never initialize transient carry on reopen.
        self.scales = PoseScaleSession(self.labels)

    @classmethod
    def from_repository(cls, repo):
        """Attach to the GUI-owned workspace connection without opening twice."""
        session = cls.__new__(cls)
        session._repo = repo
        session.labels = repo.load()
        session.scales = PoseScaleSession(session.labels)
        session._load_special_zones()
        return session

    def _load_special_zones(self):
        self.special_zones = tuple(self._repo.load_special_zone_rows())
        self.special_note = self._repo.special_zones_note()
        scale = self._repo.special_zones_diagram_scale()
        self.special_scale = 1.0 if scale is None else scale

    def save(self) -> None:
        """Errors propagate; labels and session remain available for retry."""
        self._repo.save(self.labels)

    def save_workspace(self, frames, *, last_frame, total_frames,
                       labeling_time_seconds, special_zones, special_note, special_scale):
        """Validate one complete workspace, commit it, then acknowledge dirty frames.

        No time/position checkpoint can escape a failed annotation transaction.
        Existing setup/source metadata is retained; labels-only save stays supported.
        """
        _nonnegative_frame(total_frames)
        if _nonnegative_frame(last_frame) > total_frames:
            raise ValueError("Last position exceeds video length")
        _finite(labeling_time_seconds)
        _finite(special_scale, positive=True)
        if special_note is not None and not isinstance(special_note, str):
            raise ValueError("Special Zones note must be text")
        snapshot = deepcopy(frames)
        for frame in snapshot:
            if _nonnegative_frame(frame) > total_frames:
                raise ValueError("Shared frame exceeds video length")
        points = tuple(tuple(point) for point in special_zones)
        metadata = {"last_frame": str(last_frame), "total_frames": str(total_frames),
                    "labeling_time_seconds": str(labeling_time_seconds),
                    "special_zones_note": special_note or "",
                    "special_zones_diagram_scale": str(special_scale)}
        # Labels past the video end are rejected inside the save transaction,
        # against the stored result, so unchanged labels need no in-memory scan.
        self._repo.save_workspace(self.labels, shared_frames=snapshot,
                                  special_zones=points, metadata=metadata,
                                  max_frame=total_frames)
        for frame, saved in snapshot.items():
            if frames.get(frame) == saved:
                frames[frame]["Changed"] = False

    def close(self) -> None:
        """Release storage; caller is responsible for explicit saving first."""
        self._repo.close()
