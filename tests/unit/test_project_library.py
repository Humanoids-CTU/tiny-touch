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
    assert inspect_coding_setup(paths) == (setup, True)


def test_reliability_offers_local_setup_for_review(tmp_path):
    from dataclasses import replace
    normal = ProjectPaths("clip", str(tmp_path))
    Path(normal.state_dir).mkdir(parents=True)
    repo = SqliteRepository(normal.state_db)
    setup = replace(default_coding_setup(), channel_labels={"RH":"A", "LH":"B", "RL":"C", "LL":"D"})
    repo.save_coding_setup(setup)
    repo.mark_prepared()
    repo.close()
    reliability = ProjectPaths.for_video("clip", reliability=True, base_dir=str(tmp_path))
    assert inspect_coding_setup(reliability) == (setup, False)


@pytest.mark.parametrize("prepared", [False, True])
def test_reliability_without_normal_can_prepare_and_resume(tmp_path, prepared):
    paths = ProjectPaths.for_video("clip", reliability=True, base_dir=str(tmp_path))
    setup = default_coding_setup("general") if prepared else default_coding_setup()
    if prepared:
        repo = SqliteRepository(paths.state_db)
        repo.save_coding_setup(setup)
        repo.mark_prepared()
        repo.close()
    assert inspect_coding_setup(paths) == (setup, prepared)
    assert not Path(paths.original.video_dir).exists()


@pytest.mark.parametrize("local_normal", [False, True])
def test_reliability_load_reviews_setup_before_copying(tmp_path, monkeypatch, local_normal):
    """The load flow offers manual/import setup even when Normal is available."""
    from types import SimpleNamespace
    import labeling_app

    paths = ProjectPaths.for_video("clip", reliability=True, base_dir=str(tmp_path))
    if local_normal:
        repo = SqliteRepository(paths.original.state_db)
        repo.save_coding_setup(default_coding_setup())
        repo.mark_prepared()
        repo.close()
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.db")}
    entry = SimpleNamespace(source=str(tmp_path / "clip.mp4"), paths=paths)
    monkeypatch.setattr(labeling_app, "list_projects", lambda: [entry])
    monkeypatch.setattr(labeling_app, "choose_video", lambda *a, **kw: entry)
    reviewed = []

    def configure(parent, initial, **kwargs):
        reviewed.append(initial)
        # A manually chosen or imported template may differ from local Normal.
        return default_coding_setup("general")

    monkeypatch.setattr(labeling_app, "configure_video", configure)
    monkeypatch.setattr(labeling_app.project_service, "DEFAULT_VIDEOS_DIR", str(tmp_path / "videos"))
    errors = []
    monkeypatch.setattr(labeling_app.messagebox, "showerror", lambda *a, **kw: errors.append(a))
    copied = []
    app = SimpleNamespace(_prepare_video_copy=lambda source: copied.append(source))
    labeling_app.LabelingApp._load_video_flow(app)
    assert reviewed == [default_coding_setup()]
    assert copied == [entry.source]
    assert errors == []
    assert not Path(paths.video_dir).exists()
    assert all(p.read_bytes() == content for p, content in before.items())


def test_draft_setup_is_retryable_and_inspection_does_not_write(tmp_path):
    paths = ProjectPaths("clip", str(tmp_path))
    Path(paths.state_dir).mkdir(parents=True)
    repo = SqliteRepository(paths.state_db)
    setup = default_coding_setup("alternate")
    repo.save_coding_setup(setup)
    repo.close()
    before = Path(paths.state_db).read_bytes()
    assert inspect_coding_setup(paths) == (setup, False)
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
def test_each_pass_restores_its_own_snapshot(tmp_path, opening_reliability):
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
        if reliability == opening_reliability:
            expected = setup
    assert inspect_coding_setup(ProjectPaths.for_video(
        "clip", reliability=opening_reliability, base_dir=str(tmp_path))) == (expected, True)


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
