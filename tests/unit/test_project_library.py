"""Project library identity and resumable preparation behavior."""
from pathlib import Path
import pytest
from adapters.sqlite_repo import SqliteRepository
from adapters.project_catalog import list_projects, SOURCE_META
from domain.project import ProjectPaths
from domain.coding_setup import default_coding_setup
from service_layer.project_service import plan_video_copy, inspect_coding_setup, validate_source_association


def test_same_size_different_video_is_rejected(tmp_path):
    source = tmp_path / "source" / "clip.mp4"
    source.parent.mkdir()
    source.write_bytes(b"AAAA")
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / source.name).write_bytes(b"BBBB")
    with pytest.raises(ValueError, match="different video"):
        plan_video_copy(str(source), str(videos))
    (videos / source.name).write_bytes(source.read_bytes())
    assert plan_video_copy(str(source), str(videos))[1] == "existing"


def test_catalog_and_resume_restore_setup_without_machine_preferences(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")
    paths = ProjectPaths("clip", str(tmp_path / "data"))
    Path(paths.state_dir).mkdir(parents=True)
    repo = SqliteRepository(paths.state_db)
    setup = default_coding_setup("general")
    repo.save_coding_setup(setup)
    repo.set_meta(SOURCE_META, str(source))
    repo.mark_prepared()
    repo.close()
    entry, = list_projects(paths.base_dir, str(tmp_path / "videos"))
    assert entry.title == "clip"
    assert entry.source == str(source)
    assert entry.template == "general"
    assert inspect_coding_setup(paths) == (setup, True, False)


def test_reliability_inherits_full_setup(tmp_path):
    from dataclasses import replace
    normal = ProjectPaths("clip", str(tmp_path))
    Path(normal.state_dir).mkdir(parents=True)
    repo = SqliteRepository(normal.state_db)
    setup = replace(default_coding_setup(), channel_labels={"RH":"A", "LH":"B", "RL":"C", "LL":"D"})
    repo.save_coding_setup(setup)
    repo.mark_prepared()
    repo.close()
    reliability = ProjectPaths.for_video("clip", reliability=True, base_dir=str(tmp_path))
    assert inspect_coding_setup(reliability) == (setup, False, True)


def test_draft_setup_is_retryable_and_inspection_does_not_write(tmp_path):
    paths = ProjectPaths("clip", str(tmp_path))
    Path(paths.state_dir).mkdir(parents=True)
    repo = SqliteRepository(paths.state_db)
    setup = default_coding_setup("alternate")
    repo.save_coding_setup(setup)
    repo.close()
    before = Path(paths.state_db).read_bytes()
    assert inspect_coding_setup(paths) == (setup, False, False)
    assert Path(paths.state_db).read_bytes() == before


def test_source_overwritten_in_place_is_rejected(tmp_path):
    from service_layer.project_service import source_fingerprint
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"original")
    paths = ProjectPaths("clip", str(tmp_path / "data"))
    Path(paths.state_dir).mkdir(parents=True)
    repo = SqliteRepository(paths.state_db)
    repo.set_meta(SOURCE_META, str(source))
    repo.set_meta("source_video_sha256", source_fingerprint(source))
    repo.close()
    source.write_bytes(b"replaced")
    with pytest.raises(ValueError, match="content changed"):
        validate_source_association(paths, str(source))


@pytest.mark.parametrize("opening_reliability", [False, True])
def test_reliability_conflicting_snapshot_rejected(tmp_path, opening_reliability):
    from dataclasses import replace
    for reliability in (False, True):
        paths = ProjectPaths.for_video("clip", reliability=reliability, base_dir=str(tmp_path))
        Path(paths.state_dir).mkdir(parents=True)
        repo = SqliteRepository(paths.state_db)
        setup = default_coding_setup()
        if reliability:
            setup = replace(setup, parameter_labels={"Par1":"Different", "Par2":"P2", "Par3":"P3"})
        repo.save_coding_setup(setup)
        repo.mark_prepared()
        repo.close()
    with pytest.raises(ValueError, match="conflict"):
        inspect_coding_setup(ProjectPaths.for_video("clip", reliability=opening_reliability, base_dir=str(tmp_path)))


def test_catalog_corrupt_template_is_unavailable(tmp_path):
    paths = ProjectPaths("clip", str(tmp_path))
    Path(paths.state_dir).mkdir(parents=True)
    repo = SqliteRepository(paths.state_db)
    repo.set_meta("template", "unknown-template")
    repo.close()
    entry, = list_projects(str(tmp_path))
    assert entry.preparation_state == "unavailable"
    assert entry.source is None


@pytest.mark.parametrize("recorded_hash, content, accepted", [(True, b"original", True), (True, b"unrelated", False), (False, b"original", False)])
def test_moved_project_source_requires_verified_content(tmp_path, recorded_hash, content, accepted):
    from service_layer.project_service import source_fingerprint
    source = tmp_path / "relocated" / "clip.mp4"
    source.parent.mkdir()
    source.write_bytes(b"original")
    paths = ProjectPaths("clip", str(tmp_path / "data"))
    Path(paths.state_dir).mkdir(parents=True)
    repo = SqliteRepository(paths.state_db)
    repo.set_meta(SOURCE_META, str(tmp_path / "missing-original-folder" / source.name))
    if recorded_hash:
        repo.set_meta("source_video_sha256", source_fingerprint(source))
    repo.close()
    source.write_bytes(content)
    if accepted:
        validate_source_association(paths, str(source))
    else:
        with pytest.raises(ValueError):
            validate_source_association(paths, str(source))
