"""A failed export must not be reported as a failed save.

The state DB is written first and is the source of truth. When only the
export publish fails (typical on Windows: the CSV is open in Excel, so
`os.replace` raises `PermissionError`), the annotations ARE on disk:

- `save_data` reports `SaveOutcome.EXPORT_STALE` instead of raising,
- the Save button shows a dialog that says the annotations are saved and the
  export files are out of date,
- closing the app or switching videos asks once and then proceeds, without
  the false "your latest changes are NOT on disk" warning,
- Analysis refuses to build a report from the out-of-date export.

A failed state-DB write keeps the strict behavior (`SaveOutcome.NOT_SAVED`).
"""
import os
from types import SimpleNamespace

import pytest

import labeling_app
from adapters.sqlite_repo import SqliteRepository
from domain.model import empty_bundle
from domain.project import ProjectPaths
from labeling_app import LabelingApp
from service_layer import save_service
from service_layer.save_service import SaveOutcome
from video_model import Video


# === a real Touch save over a real state DB and export folder =================
def _touch_app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = ProjectPaths("vid")
    os.makedirs(paths.state_dir, exist_ok=True)
    repo = SqliteRepository(paths.state_db)
    repo.save_template(repo.load_template().choose("default"))
    video = Video("vid.mp4", 9)
    video.frames_dir = "frames"
    button = SimpleNamespace(cget=lambda key: "P")
    app = SimpleNamespace(
        annotation_type="Touch", video=video, video_name="vid", state_repo=repo,
        labeling_mode="Normal", frame_rate=25.0, coding_setup=None,
        zone_display=SimpleNamespace(labels={}),
        par1_btn=button, par2_btn=button, par3_btn=button,
        _persist_video_time=lambda: None,
        preview_before_save=lambda changed_only=True: None,
        _limb_param_labels_for_export=lambda: None,
        _current_video_time_s=lambda: 60.0,
        # The modal progress window is Tk; run the export inline instead.
        _run_export_with_progress=lambda export_fn: export_fn(),
    )
    app.save_data = lambda: LabelingApp.save_data(app)
    return app, paths, repo


def _annotate(app, frame, note):
    bundle = empty_bundle()
    bundle["Note"] = note
    bundle["Changed"] = True
    app.video.frames[frame] = bundle


def _lock(monkeypatch, target):
    """Make publishing `target` fail the way Windows does when Excel holds it."""
    original = save_service.os.replace

    def replace(source, destination):
        if destination == target:
            raise PermissionError(13, "The process cannot access the file", destination)
        return original(source, destination)

    monkeypatch.setattr(save_service.os, "replace", replace)
    return lambda: monkeypatch.setattr(save_service.os, "replace", original)


def test_locked_csv_keeps_annotations_and_reports_stale_export(tmp_path, monkeypatch):
    app, paths, repo = _touch_app(tmp_path, monkeypatch)
    try:
        _annotate(app, 3, "first")
        assert LabelingApp.save_data(app) is SaveOutcome.SAVED
        before = open(paths.export_csv, "rb").read()

        _annotate(app, 4, "typed while Excel had the CSV open")
        unlock = _lock(monkeypatch, paths.export_csv)
        assert LabelingApp.save_data(app) is SaveOutcome.EXPORT_STALE

        # The state DB has the edit; the published export was left untouched.
        assert repo.load_frames()[4]["Note"] == "typed while Excel had the CSV open"
        assert open(paths.export_csv, "rb").read() == before
        assert app.video.frames[4]["Changed"] is True  # still owed to the export

        unlock()
        assert LabelingApp.save_data(app) is SaveOutcome.SAVED
        assert b"typed while Excel had the CSV open" in open(paths.export_csv, "rb").read()
        assert app.video.frames[4]["Changed"] is False
    finally:
        repo.close()


def test_unchanged_save_succeeds_while_the_csv_is_held_open(tmp_path, monkeypatch):
    """No frame changed since the last export this session: the CSV is not
    rewritten, so a CSV held open elsewhere does not block the save."""
    app, paths, repo = _touch_app(tmp_path, monkeypatch)
    try:
        _annotate(app, 3, "exported")
        assert LabelingApp.save_data(app) is SaveOutcome.SAVED
        _lock(monkeypatch, paths.export_csv)
        app._current_video_time_s = lambda: 7200.0
        assert LabelingApp.save_data(app) is SaveOutcome.SAVED
        # The metadata is still rewritten on every save.
        assert '"Total Labeling Time (hours)": 2.0' in open(paths.export_metadata, encoding="utf-8").read()
    finally:
        repo.close()


def test_failed_export_forces_the_next_save_to_rewrite_the_csv(tmp_path, monkeypatch):
    app, paths, repo = _touch_app(tmp_path, monkeypatch)
    try:
        _annotate(app, 3, "exported")
        assert LabelingApp.save_data(app) is SaveOutcome.SAVED
        unlock = _lock(monkeypatch, paths.export_metadata)
        assert LabelingApp.save_data(app) is SaveOutcome.EXPORT_STALE  # no dirty frame here
        unlock()
        _lock(monkeypatch, paths.export_csv)
        # The CSV rewrite is attempted (and blocked), proving it was not skipped.
        assert LabelingApp.save_data(app) is SaveOutcome.EXPORT_STALE
    finally:
        repo.close()


def test_a_new_session_rewrites_the_csv(tmp_path, monkeypatch):
    app, paths, repo = _touch_app(tmp_path, monkeypatch)
    try:
        assert LabelingApp.save_data(app) is SaveOutcome.SAVED
        app.video = Video("vid.mp4", 9)  # the video was unloaded and loaded again
        app.video.frames_dir = "frames"
        _lock(monkeypatch, paths.export_csv)
        assert LabelingApp.save_data(app) is SaveOutcome.EXPORT_STALE
    finally:
        repo.close()


def test_state_db_failure_is_reported_as_not_saved(tmp_path, monkeypatch):
    app, paths, repo = _touch_app(tmp_path, monkeypatch)
    try:
        _annotate(app, 3, "never reaches the DB")

        def broken(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(save_service, "persist_state", broken)
        assert LabelingApp.save_data(app) is SaveOutcome.NOT_SAVED
        assert not os.path.exists(paths.export_csv)
        assert app.video.frames[3]["Changed"] is True
    finally:
        repo.close()


@pytest.mark.parametrize("outcome, words", [
    (SaveOutcome.EXPORT_STALE, ("annotations are saved", "out of date", "close the csv")),
    (SaveOutcome.NOT_SAVED, ("not saved",)),
])
def test_save_button_shows_every_failure(monkeypatch, outcome, words):
    shown = []
    for kind in ("showerror", "showwarning", "showinfo"):
        monkeypatch.setattr(labeling_app.messagebox, kind,
                            lambda title, message, **kw: shown.append(message))
    app = SimpleNamespace(annotation_type="Touch", save_data=lambda: outcome)

    LabelingApp.save_from_button(app)

    assert len(shown) == 1
    assert all(word in shown[0].lower() for word in words)


def test_save_button_is_silent_on_success(monkeypatch):
    monkeypatch.setattr(labeling_app.messagebox, "showerror", lambda *a, **kw: pytest.fail("dialog"))
    monkeypatch.setattr(labeling_app.messagebox, "showwarning", lambda *a, **kw: pytest.fail("dialog"))
    app = SimpleNamespace(annotation_type="Touch", save_data=lambda: SaveOutcome.SAVED)
    LabelingApp.save_from_button(app)


# === close / switch video after a stale export ================================
def _closing_app(events, outcome):
    return SimpleNamespace(
        video=SimpleNamespace(frames={}),
        save_data=lambda: events.append("save") or outcome,
        save_last_position=lambda: events.append("last_position"),
        _finalize_video_time=lambda: events.append("finalize_time"),
        _close_state_repo=lambda: events.append("close_state_repo"),
        frame_buffer=SimpleNamespace(shutdown=lambda **kw: events.append("shutdown")),
        _cancel_pending_timers=lambda: None,
        destroy=lambda: events.append("destroy"),
    )


@pytest.mark.parametrize("answer", [True, False])
def test_close_after_stale_export_asks_without_data_loss_warning(monkeypatch, answer):
    events, questions = [], []
    app = _closing_app(events, SaveOutcome.EXPORT_STALE)
    monkeypatch.setattr(labeling_app, "custom_confirm_close", lambda root: True)
    monkeypatch.setattr(labeling_app.messagebox, "askyesno",
                        lambda title, message, **kw: questions.append(message) or answer)

    LabelingApp.on_close(app)

    assert len(questions) == 1
    assert "NOT on disk" not in questions[0]
    assert "annotations are saved" in questions[0].lower()
    if answer:
        assert events[-1] == "destroy" and "last_position" in events
    else:
        assert events == ["save"] and app._closing is False


@pytest.mark.parametrize("answer", [True, False])
def test_switching_video_after_stale_export_is_possible_after_confirming(monkeypatch, answer):
    events, questions = [], []
    app = SimpleNamespace(
        video=object(), video_name="old", _special_zones_app=None, _last_step_sign=1,
        stop_video=lambda: None, _cancel_arrow_hold_state=lambda: None,
        _cancel_wheel_scroll=lambda: None,
        save_data=lambda: events.append("save") or SaveOutcome.EXPORT_STALE,
        save_last_position=lambda: events.append("last_position"),
        _finalize_video_time=lambda: None, _reset_zone_cache=lambda: None,
        _redraw_diagram=lambda: None, _set_note_entry_text=lambda text: None,
        _refresh_jump_label=lambda: None, update_frame_counter=lambda: None,
        _set_mode_button_states=lambda: None, special_zones_btn=object(),
        name_label=SimpleNamespace(config=lambda **kw: None),
        framerate_label=SimpleNamespace(config=lambda **kw: None),
        frame_buffer=SimpleNamespace(buffer_ready=True),
        _buffer_reset=lambda: None,
        _close_state_repo=lambda: events.append("close_repo"),
    )
    monkeypatch.setattr(labeling_app.theme, "set_button_state", lambda *a: None)
    monkeypatch.setattr(labeling_app.messagebox, "askyesno",
                        lambda title, message, **kw: questions.append(message) or answer)
    monkeypatch.setattr(labeling_app.messagebox, "showerror", lambda *a, **kw: pytest.fail("false save error"))

    assert LabelingApp._unload_current_video(app) is answer

    assert len(questions) == 1 and "annotations are saved" in questions[0].lower()
    if answer:
        assert app.video is None and "close_repo" in events
    else:
        assert events == ["save"] and app.video_name == "old"


# === Analysis never reads an out-of-date export ===============================
@pytest.mark.parametrize("outcome", [SaveOutcome.EXPORT_STALE, SaveOutcome.NOT_SAVED])
def test_analysis_stops_when_the_export_was_not_updated(monkeypatch, outcome):
    errors = []
    monkeypatch.setattr(labeling_app.analysis_service, "run_analysis",
                        lambda *a, **kw: pytest.fail("analysis read a stale export"))
    monkeypatch.setattr(labeling_app.messagebox, "showerror",
                        lambda title, message, **kw: errors.append(message))
    app = SimpleNamespace(annotation_type="Touch", video=object(), video_name="vid",
                          _resolve_open_touches_before_analysis=lambda: True,
                          save_data=lambda: outcome)

    LabelingApp.analysis(app)

    assert len(errors) == 1 and "analysis" in errors[0].lower()
