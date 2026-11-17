"""Real load/publish routing and repositories with no Tk or frame workers."""
from types import SimpleNamespace

import pytest

import labeling_app
from adapters.project_catalog import SOURCE_META
from labeling_app import LabelingApp
from adapters.pose_sqlite_repo import PoseSqliteRepository
from adapters.sqlite_repo import SqliteRepository
from domain.coding_setup import default_coding_setup
from domain.pose import ScaleKind, ScaleSource
from domain.pose_setup import PoseCodingSetup
from domain.project import ProjectPaths
from service_layer import project_service


class Widget:
    def __init__(self):
        self.options = {}

    def config(self, **options):
        self.options.update(options)

    def set(self, *values):
        self.options["value"] = values


def load_app(monkeypatch):
    app = SimpleNamespace(video=None, video_name=None, state_repo=None,
                          annotation_type="Touch", jump_seconds=1, minimal_touch_length=100,
                          labeling_timer=project_service.LabelingTimer(), frame_rate=25,
                          displayed_frame=None, frame_paint_listeners=[], _special_zones_app=None)
    for name in ("par1_btn", "par2_btn", "par3_btn", "limb_par1_btn", "limb_par2_btn",
                 "limb_par3_btn", "name_label", "framerate_label", "min_touch_length_label",
                 "mode_label", "special_zones_btn"):
        setattr(app, name, Widget())
    for name in ("_prepare_video_renderer", "_reset_zone_cache", "_load_zone_masks",
                 "rebuild_annotation_controls", "_redraw_diagram", "_refresh_jump_label",
                 "draw_timeline", "draw_timeline2", "update_note_entry", "_set_mode_button_states"):
        setattr(app, name, lambda: None)
    app._apply_active_template = lambda template: setattr(app, "template", template)
    app.video_frame = SimpleNamespace(winfo_width=lambda: 640, winfo_height=lambda: 480)
    app.frame_buffer = SimpleNamespace(poke=lambda: None)
    app.background_thread = SimpleNamespace(is_alive=lambda: True)
    app._detail_timeline = app._overview_timeline = SimpleNamespace(reset=lambda: None)
    app._prepare_video_copy = lambda source: source
    app._open_data_progress_window = lambda: (lambda *a: None, lambda: None)
    app._run_with_progress = lambda work, **kw: work()
    app._run_frame_extraction = lambda *a: None
    app.display_first_frame = lambda: setattr(app, "displayed_frame", app.video.current_frame)
    app.restore_last_position = lambda: LabelingApp.restore_last_position(app)
    app._publish_loaded_video = lambda *a: LabelingApp._publish_loaded_video(app, *a)
    app._first_frame_shown = lambda video: LabelingApp._first_frame_shown(app, video)
    app._abort_load_to_clean_state = lambda: pytest.fail("load aborted")

    def unload():
        # Storage detach is real; frame-worker/UI cleanup is outside this harness.
        LabelingApp._close_state_repo(app)
        app.video = None
        return True

    app._unload_current_video = unload
    monkeypatch.setattr(labeling_app.content_swap, "swap_content", lambda app, publish, **kw: publish())
    monkeypatch.setattr(labeling_app.theme, "set_button_state", lambda *a: None)
    monkeypatch.setattr(labeling_app.video_probe, "probe", lambda path: (10, 25))
    monkeypatch.setattr(labeling_app.messagebox, "showerror", lambda *a, **kw: pytest.fail(str(a)))
    return app


@pytest.mark.parametrize("mode", ["Normal", "Reliability"])
def test_load_and_publish_pose_touch_pose_restores_saved_type_and_labels(tmp_path, monkeypatch, mode):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(project_service, "DEFAULT_VIDEOS_DIR", str(tmp_path / "videos"))
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"source")
    entries = []
    for kind, setup in (("Pose", PoseCodingSetup()), ("Touch", default_coding_setup("general"))):
        paths = project_service.prepare_project("clip", mode, kind)
        repo = project_service.open_state(paths)
        repo.save_coding_setup(setup)
        repo.mark_prepared()
        repo.set_meta(SOURCE_META, str(source))
        repo.set_meta("source_video_sha256", project_service.source_fingerprint(str(source)))
        repo.close()
        entries.append(SimpleNamespace(source=str(source), paths=paths))
    app = load_app(monkeypatch)
    monkeypatch.setattr(labeling_app, "list_projects", lambda: entries)
    monkeypatch.setattr(project_service, "frames_ready", lambda *a: True)
    for entry in (entries[0], entries[1], entries[0]):
        monkeypatch.setattr(labeling_app, "choose_video", lambda *a, **kw: entry)
        LabelingApp._load_video_flow(app)
        assert app.annotation_type == entry.paths.annotation_type
        assert app.template == ("alternate" if app.annotation_type == "Pose" else "general")
        assert app.labeling_mode == mode
        assert app.mode_label.options["value"][1] == f"{app.annotation_type} / {mode}"
        assert app.displayed_frame == app.video.current_frame
        if app.annotation_type == "Pose":
            assert isinstance(app.state_repo, PoseSqliteRepository)
            if app.pose_session.labels.quality(0) is None:
                app.pose_session.labels.set_quality(0, 0, displayed_frame=0)
                app.pose_session.scales.edit(0, ScaleKind.BODY, 1.2, displayed_frame=0)
                app.pose_session.scales.arrive(0, 1, labeling_app.Navigation.FORWARD_STEP, displayed_frame=1)
                app.pose_session.save()
            else:
                assert app.pose_session.labels.quality(0) == 0
                assert app.pose_session.labels.scale(1, ScaleKind.BODY).source is ScaleSource.CARRIED
                assert app.pose_session.scales.carried_value(ScaleKind.BODY) is None
        else:
            assert isinstance(app.state_repo, SqliteRepository)
            assert not hasattr(app, "pose_session")
    LabelingApp._close_state_repo(app)
    if mode == "Reliability":
        assert all(not labeling_app.os.path.exists(entry.paths.original.state_db) for entry in entries)


def test_resume_hashes_the_source_once_and_keeps_slow_checks_off_the_ui_thread(tmp_path, monkeypatch):
    """Resuming a long video looked frozen: the source was hashed twice and the
    frames folder was listed on the Tk thread with no window on screen."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(project_service, "DEFAULT_VIDEOS_DIR", str(tmp_path / "videos"))
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"source")
    paths = project_service.prepare_project("clip", "Normal", "Touch")
    repo = project_service.open_state(paths)
    repo.save_coding_setup(default_coding_setup("general"))
    repo.mark_prepared()
    repo.set_meta(SOURCE_META, str(source))
    repo.set_meta("source_video_sha256", project_service.source_fingerprint(str(source)))
    repo.close()
    entry = SimpleNamespace(source=str(source), paths=paths)
    app = load_app(monkeypatch)
    behind_progress = []
    depth = []

    def run_with_progress(work, **options):
        behind_progress.append(options["heading"])
        depth.append(1)
        try:
            return work()
        finally:
            depth.pop()

    app._run_with_progress = run_with_progress
    real_fingerprint = project_service.source_fingerprint
    unprotected = []
    hashed = []

    def fingerprint(path):
        hashed.append(path)
        if not depth:
            unprotected.append("fingerprint")
        return real_fingerprint(path)

    def frames_ready(*args):
        if not depth:
            unprotected.append("frames check")
        return True

    monkeypatch.setattr(project_service, "source_fingerprint", fingerprint)
    monkeypatch.setattr(project_service, "frames_ready", frames_ready)
    monkeypatch.setattr(labeling_app, "list_projects", lambda: [entry])
    monkeypatch.setattr(labeling_app, "choose_video", lambda *a, **kw: entry)

    LabelingApp._load_video_flow(app)

    assert len(hashed) == 1
    assert unprotected == []
    assert behind_progress == ["Checking the video file...", "Checking video frames..."]
    LabelingApp._close_state_repo(app)


def test_cancel_pose_setup_keeps_active_project_and_creates_no_database(tmp_path, monkeypatch):
    paths = ProjectPaths("new", str(tmp_path / "data"), "Pose")
    entry = SimpleNamespace(source=str(tmp_path / "new.mp4"), paths=paths)
    app = SimpleNamespace(video=object(), state_repo=object(), annotation_type="Touch", template="general")
    before = vars(app).copy()
    monkeypatch.setattr(labeling_app, "list_projects", lambda: [entry])
    monkeypatch.setattr(labeling_app, "choose_video", lambda *a, **kw: entry)
    monkeypatch.setattr(labeling_app, "configure_pose_video", lambda *a, **kw: None)
    LabelingApp._load_video_flow(app)
    assert vars(app) == before
    assert not tmp_path.joinpath("data").exists()
