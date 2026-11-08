from pathlib import Path

from domain.project import ProjectPaths
from service_layer.project_copy import next_copy_project


def test_copy_has_fresh_name_without_creating_files(tmp_path):
    original = ProjectPaths("clip", str(tmp_path))
    assert next_copy_project(original).video_name == "clip_copy"
    assert list(tmp_path.iterdir()) == []


def test_copy_skips_existing_projects_and_reliability_pairs(tmp_path):
    for name in ("clip_copy", "clip_copy2_reliability"):
        (tmp_path / name).mkdir()
    original = ProjectPaths("clip_reliability", str(tmp_path))
    result = next_copy_project(original)
    assert result.video_name == "clip_copy3"
    assert result.base_dir == str(tmp_path)
    assert not Path(result.video_dir).exists()
