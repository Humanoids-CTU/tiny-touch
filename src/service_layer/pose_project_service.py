"""Headless Pose save/reopen use case, ready for a later controller.

No GUI lifecycle, video preparation, export or shared annotation integration is
claimed here. Call save explicitly; close only releases the database connection.
"""

from adapters.pose_sqlite_repo import PoseSqliteRepository
from domain.pose import PoseScaleSession
from domain.project import ProjectPaths


class PoseProjectSession:
    def __init__(self, paths: ProjectPaths):
        self._repo = PoseSqliteRepository(paths.pose_state_db)
        try:
            self.labels = self._repo.load()
        except Exception:
            self._repo.close()
            raise
        # Saved labels never initialize transient carry on reopen.
        self.scales = PoseScaleSession(self.labels)

    def save(self) -> None:
        """Errors propagate; labels and session remain available for retry."""
        self._repo.save(self.labels)

    def close(self) -> None:
        """Release storage; caller is responsible for explicit saving first."""
        self._repo.close()
