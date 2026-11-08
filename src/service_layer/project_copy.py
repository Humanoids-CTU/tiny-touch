"""Choose a fresh coding-project identity without duplicating source media."""
import os

from domain.project import ProjectPaths


def next_copy_project(paths: ProjectPaths) -> ProjectPaths:
    """Reserve neither files nor folders; skip both Normal/Reliability pairs."""
    original = paths.original
    index = 1
    while True:
        suffix = "_copy" if index == 1 else f"_copy{index}"
        candidate = ProjectPaths(original.video_name + suffix, original.base_dir)
        twin = ProjectPaths.for_video(candidate.video_name, reliability=True,
                                      base_dir=candidate.base_dir)
        if not os.path.exists(candidate.video_dir) and not os.path.exists(twin.video_dir):
            return candidate
        index += 1
