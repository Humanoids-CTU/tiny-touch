"""Every Pose save publishes the Pose export; a failed export loses no label.

The Pose database is written first and stays the source of truth. These tests
drive the real `LabelingApp.save_data` over a real Pose database and export
folder, with the Tk parts replaced (see test_save_outcome.py for Touch).

- a save publishes `<video>_pose_export.csv` and `<video>_pose_metadata.json`,
- a failed publish is `SaveOutcome.EXPORT_STALE`: the database has the edit and
  the published files are untouched,
- the Save button, close and switching videos treat that like Touch does,
- a failed database save stays `NOT_SAVED` and publishes nothing,
- closing with "Don't save" writes nothing.
"""
import csv
import json
import os
import threading
from types import SimpleNamespace

import pytest

import labeling_app
from adapters.pose_sqlite_repo import PoseSqliteRepository
from domain.pose import ScaleKind, ScaleLabel, ScaleSource, ZoneEvent
from domain.pose_setup import PoseCodingSetup
from domain.project import ProjectPaths
from gui.app_dialogs import CLOSE_DISCARD
from labeling_app import LabelingApp
from service_layer import pose_export_service
from service_layer.pose_project_service import PoseProjectSession
from service_layer.save_service import SaveOutcome
from video_model import Video


def _run_on_worker(export_fn):
    """Like the real progress window: the export runs off the calling thread,
    so any use of the thread-bound SQLite connection would raise."""
    result = {}

    def work():
        try:
            result["value"] = export_fn()
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=work)
    thread.start()
    thread.join(30)
    assert not thread.is_alive()
    if "error" in result:
        raise result["error"]
    return result["value"]


def _pose_app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = ProjectPaths("vid", annotation_type="Pose")
    repo = PoseSqliteRepository(paths.pose_state_db)
    repo.save_coding_setup(PoseCodingSetup(), "ready")
    session = PoseProjectSession.from_repository(repo)
    return _attach(repo, session), paths, repo


def _attach(repo, session):
    video = Video("vid.mp4", 9)
    video.frames_dir = "frames"
    video.frames = repo.load_frames()
    app = SimpleNamespace(
        annotation_type="Pose", video=video, video_name="vid", state_repo=repo,
        pose_session=session, labeling_mode="Normal", frame_rate=25.0,
        coding_setup=repo.load_coding_setup(), _zone_masks=[],
        _current_video_time_s=lambda: 60.0,
        _run_export_with_progress=_run_on_worker,
    )
    app._save_pose_workspace = lambda: LabelingApp._save_pose_workspace(app)
    app._publish_pose_export = lambda: LabelingApp._publish_pose_export(app)
    app.save_data = lambda: LabelingApp.save_data(app)
    return app


def _label(app, frame, quality):
    app.pose_session.labels.set_quality(frame, quality, displayed_frame=frame)


def _note(app, frame, text):
    app.video.frames[frame] = {"Note": text, "Params": {}, "Changed": True}


def _rows(paths):
    with open(paths.pose_export_csv, encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _stored_quality(paths, frame):
    """Read through a second connection, as a reopened project would."""
    observer = PoseSqliteRepository(paths.pose_state_db)
    try:
        return observer.load().quality(frame)
    finally:
        observer.close()


def _lock(monkeypatch, target):
    """Make publishing `target` fail the way Windows does when Excel holds it."""
    original = pose_export_service.os.replace

    def replace(source, destination):
        if destination == target:
            raise PermissionError(13, "The process cannot access the file", destination)
        return original(source, destination)

    monkeypatch.setattr(pose_export_service.os, "replace", replace)
    return lambda: monkeypatch.setattr(pose_export_service.os, "replace", original)


# === a save publishes the export ==============================================
def test_save_publishes_csv_and_metadata_from_a_worker_thread(tmp_path, monkeypatch):
    app, paths, repo = _pose_app(tmp_path, monkeypatch)
    try:
        labels = app.pose_session.labels
        labels.set_event(2, "L", ZoneEvent.ON, displayed_frame=2)
        labels.set_event(5, "B", ZoneEvent.OFF, displayed_frame=5)
        labels.set_scale(2, ScaleKind.BODY, ScaleLabel(1.2, ScaleSource.MANUAL), displayed_frame=2)
        _label(app, 2, 0.0)
        app.video.frames[5] = {"Note": "rolled, twice", "Params": {"Par1": "ON"}, "Changed": True}
        app.pose_session.special_zones = ((1, 10.0, 20.0, "B"),)
        app.pose_session.special_note = "socks"

        assert LabelingApp.save_data(app) is SaveOutcome.SAVED

        rows = _rows(paths)
        assert len(rows) == 10                       # frames 0..9
        assert rows[2]["Zones_On"] == '["L"]' and rows[5]["Zones_Off"] == '["B"]'
        assert (rows[2]["Body_Scale"], rows[2]["Body_Scale_Source"]) == ("1.20", "manual")
        assert rows[2]["Quality"] == "0.00" and rows[3]["Quality"] == ""
        assert (rows[5]["Parameter_1"], rows[5]["Note"]) == ("ON", "rolled, twice")
        meta = json.load(open(paths.pose_export_metadata, encoding="utf-8"))
        assert meta["Annotation Type"] == "Pose" and meta["Video Name"] == "vid"
        assert meta["Labeling Mode"] == "Normal" and meta["Total Frames"] == 10
        assert meta["Special Zones"] == ["B"] and meta["Special Zones Note"] == "socks"
        assert meta["Coding Setup"]["template"] == "alternate"
        assert app.video.frames[5]["Changed"] is False
        # Only the two published files remain: no staging folder, no temp file.
        assert sorted(os.listdir(paths.export_dir)) == ["vid_pose_export.csv", "vid_pose_metadata.json"]
        # Nothing was written under Touch's names.
        assert not os.path.exists(paths.export_csv) and not os.path.exists(paths.export_metadata)
    finally:
        repo.close()


def test_an_edit_after_an_export_reaches_the_next_csv(tmp_path, monkeypatch):
    app, paths, repo = _pose_app(tmp_path, monkeypatch)
    try:
        _label(app, 1, 0.5)
        assert LabelingApp.save_data(app) is SaveOutcome.SAVED
        _label(app, 3, 0.25)
        assert LabelingApp.save_data(app) is SaveOutcome.SAVED
        _note(app, 4, "only a note changed")
        assert LabelingApp.save_data(app) is SaveOutcome.SAVED
        rows = _rows(paths)
        assert (rows[1]["Quality"], rows[3]["Quality"]) == ("0.50", "0.25")
        assert rows[4]["Note"] == "only a note changed"
    finally:
        repo.close()


def test_reopened_project_without_an_export_publishes_on_its_next_save(tmp_path, monkeypatch):
    app, paths, repo = _pose_app(tmp_path, monkeypatch)
    _label(app, 1, 0.5)
    app.pose_session.save_workspace(
        app.video.frames, last_frame=0, total_frames=9, labeling_time_seconds=1,
        special_zones=(), special_note=None, special_scale=1.0)   # a database with no export yet
    repo.close()
    assert not os.path.exists(paths.export_dir)

    repo = PoseSqliteRepository(paths.pose_state_db)
    try:
        app = _attach(repo, PoseProjectSession.from_repository(repo))
        assert LabelingApp.save_data(app) is SaveOutcome.SAVED   # nothing edited
        assert _rows(paths)[1]["Quality"] == "0.50"
        assert os.path.exists(paths.pose_export_metadata)
    finally:
        repo.close()


# === a failed export ==========================================================
def test_locked_csv_keeps_labels_and_reports_stale_export(tmp_path, monkeypatch):
    app, paths, repo = _pose_app(tmp_path, monkeypatch)
    try:
        _label(app, 1, 0.5)
        assert LabelingApp.save_data(app) is SaveOutcome.SAVED
        csv_before = open(paths.pose_export_csv, "rb").read()
        meta_before = open(paths.pose_export_metadata, "rb").read()

        _label(app, 4, 0.75)
        _note(app, 4, "typed while Excel had the CSV open")
        app._current_video_time_s = lambda: 7200.0
        unlock = _lock(monkeypatch, paths.pose_export_csv)
        assert LabelingApp.save_data(app) is SaveOutcome.EXPORT_STALE

        # The database has the edit; both published files were left untouched.
        assert _stored_quality(paths, 4) == 0.75
        assert repo.load_frames()[4]["Note"] == "typed while Excel had the CSV open"
        assert open(paths.pose_export_csv, "rb").read() == csv_before
        assert open(paths.pose_export_metadata, "rb").read() == meta_before
        assert sorted(os.listdir(paths.export_dir)) == ["vid_pose_export.csv", "vid_pose_metadata.json"]

        # Nothing is dirty any more, yet the next save still rewrites the CSV.
        assert LabelingApp.save_data(app) is SaveOutcome.EXPORT_STALE
        unlock()
        assert LabelingApp.save_data(app) is SaveOutcome.SAVED
        assert _rows(paths)[4]["Quality"] == "0.75"
        assert _rows(paths)[4]["Note"] == "typed while Excel had the CSV open"
    finally:
        repo.close()


def test_failed_metadata_publish_restores_the_previous_csv(tmp_path, monkeypatch):
    app, paths, repo = _pose_app(tmp_path, monkeypatch)
    try:
        _label(app, 1, 0.5)
        assert LabelingApp.save_data(app) is SaveOutcome.SAVED
        csv_before = open(paths.pose_export_csv, "rb").read()
        _label(app, 2, 0.5)
        _lock(monkeypatch, paths.pose_export_metadata)
        assert LabelingApp.save_data(app) is SaveOutcome.EXPORT_STALE
        # The pair stays consistent: the already replaced CSV was put back.
        assert open(paths.pose_export_csv, "rb").read() == csv_before
        assert _stored_quality(paths, 2) == 0.5
    finally:
        repo.close()


def test_unchanged_save_succeeds_while_the_csv_is_held_open(tmp_path, monkeypatch):
    """Nothing changed since this session's export: the CSV is not rewritten,
    the metadata is, and no worker thread or progress window is needed."""
    app, paths, repo = _pose_app(tmp_path, monkeypatch)
    try:
        _label(app, 1, 0.5)
        assert LabelingApp.save_data(app) is SaveOutcome.SAVED
        _lock(monkeypatch, paths.pose_export_csv)
        app._run_export_with_progress = lambda fn: pytest.fail("the CSV was rewritten")
        app._current_video_time_s = lambda: 7200.0
        assert LabelingApp.save_data(app) is SaveOutcome.SAVED
        meta = json.load(open(paths.pose_export_metadata, encoding="utf-8"))
        assert meta["Total Labeling Time (hours)"] == 2.0
    finally:
        repo.close()


def test_csv_replaced_outside_the_app_is_rewritten(tmp_path, monkeypatch):
    app, paths, repo = _pose_app(tmp_path, monkeypatch)
    try:
        _label(app, 1, 0.5)
        assert LabelingApp.save_data(app) is SaveOutcome.SAVED
        with open(paths.pose_export_csv, "w", encoding="utf-8") as stream:
            stream.write("edited by hand")
        assert LabelingApp.save_data(app) is SaveOutcome.SAVED
        assert _rows(paths)[1]["Quality"] == "0.50"
        os.remove(paths.pose_export_csv)
        assert LabelingApp.save_data(app) is SaveOutcome.SAVED
        assert _rows(paths)[1]["Quality"] == "0.50"
    finally:
        repo.close()


def test_database_failure_is_not_saved_and_publishes_nothing(tmp_path, monkeypatch):
    app, paths, repo = _pose_app(tmp_path, monkeypatch)
    errors = []
    monkeypatch.setattr(labeling_app.messagebox, "showerror",
                        lambda title, message, **kw: errors.append(message))
    try:
        _label(app, 1, 0.5)

        def broken(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(app.pose_session, "save_workspace", broken)
        assert LabelingApp.save_data(app) is SaveOutcome.NOT_SAVED
        assert not os.path.exists(paths.export_dir)
        assert len(errors) == 1 and "disk full" in errors[0]
        assert app.pose_session.labels.has_pending_changes
    finally:
        repo.close()


def test_edit_followed_by_a_failed_database_save_still_rewrites_the_csv_later(tmp_path, monkeypatch):
    app, paths, repo = _pose_app(tmp_path, monkeypatch)
    monkeypatch.setattr(labeling_app.messagebox, "showerror", lambda *a, **kw: None)
    try:
        _label(app, 1, 0.5)
        assert LabelingApp.save_data(app) is SaveOutcome.SAVED
        _label(app, 2, 0.25)
        def broken(*args, **kwargs):
            raise OSError("busy")

        with monkeypatch.context() as patch:
            patch.setattr(app.pose_session, "save_workspace", broken)
            assert LabelingApp.save_data(app) is SaveOutcome.NOT_SAVED
        assert LabelingApp.save_data(app) is SaveOutcome.SAVED
        assert _rows(paths)[2]["Quality"] == "0.25"
    finally:
        repo.close()


# === what the user sees =======================================================
def test_save_button_warns_once_about_a_stale_pose_export(monkeypatch):
    shown = []
    monkeypatch.setattr(labeling_app.messagebox, "showerror", lambda *a, **kw: pytest.fail("error"))
    monkeypatch.setattr(labeling_app.messagebox, "showwarning",
                        lambda title, message, **kw: shown.append(message))
    app = SimpleNamespace(annotation_type="Pose", save_data=lambda: SaveOutcome.EXPORT_STALE)
    LabelingApp.save_from_button(app)
    assert len(shown) == 1
    text = shown[0].lower()
    assert all(words in text for words in ("annotations are saved", "out of date", "close the csv"))
    assert "pose export" in text and "diagram" not in text


@pytest.mark.parametrize("outcome", [SaveOutcome.SAVED, SaveOutcome.NOT_SAVED])
def test_save_button_adds_no_dialog_for_other_pose_outcomes(monkeypatch, outcome):
    """A failed Pose database save already showed its error inside save_data."""
    for kind in ("showerror", "showwarning", "showinfo"):
        monkeypatch.setattr(labeling_app.messagebox, kind, lambda *a, **kw: pytest.fail("dialog"))
    LabelingApp.save_from_button(SimpleNamespace(annotation_type="Pose", save_data=lambda: outcome))


def _closing_app(events, outcome):
    app = SimpleNamespace(
        annotation_type="Pose", video=SimpleNamespace(frames={}), video_name="vid",
        save_data=lambda: events.append("save") or outcome,
        save_last_position=lambda: events.append("last_position"),
        _finalize_video_time=lambda: events.append("finalize_time"),
        _close_state_repo=lambda: events.append("close_state_repo"),
        frame_buffer=SimpleNamespace(shutdown=lambda **kw: events.append("shutdown")),
        _cancel_pending_timers=lambda: None,
        destroy=lambda: events.append("destroy"),
    )
    app._ask_how_to_close = lambda: LabelingApp._ask_how_to_close(app)
    return app


@pytest.mark.parametrize("answer", [True, False])
def test_close_after_stale_pose_export_asks_once_then_follows_the_answer(monkeypatch, answer):
    events, questions = [], []
    app = _closing_app(events, SaveOutcome.EXPORT_STALE)
    monkeypatch.setattr(labeling_app, "custom_confirm_close", lambda root, **kw: True)
    monkeypatch.setattr(labeling_app.messagebox, "showerror", lambda *a, **kw: pytest.fail("false save error"))
    monkeypatch.setattr(labeling_app.messagebox, "askyesno",
                        lambda title, message, **kw: questions.append(message) or answer)

    LabelingApp.on_close(app)

    assert len(questions) == 1
    assert "annotations are saved" in questions[0].lower() and "NOT on disk" not in questions[0]
    if answer:
        assert events[-1] == "destroy" and "close_state_repo" in events
    else:
        assert events == ["save"] and app._closing is False


def test_close_after_a_failed_pose_database_save_still_refuses(monkeypatch):
    events, errors = [], []
    app = _closing_app(events, SaveOutcome.NOT_SAVED)
    monkeypatch.setattr(labeling_app, "custom_confirm_close", lambda root, **kw: True)
    monkeypatch.setattr(labeling_app.messagebox, "askyesno", lambda *a, **kw: pytest.fail("offered to close"))
    monkeypatch.setattr(labeling_app.messagebox, "showerror",
                        lambda title, message, **kw: errors.append(message))
    LabelingApp.on_close(app)
    assert events == ["save"] and app._closing is False and len(errors) == 1


@pytest.mark.parametrize("answer", [True, False])
def test_switching_video_after_stale_pose_export_needs_one_confirmation(monkeypatch, answer):
    events, questions = [], []
    app = SimpleNamespace(
        annotation_type="Pose", video=object(), video_name="old", _special_zones_app=None,
        _last_step_sign=1, stop_video=lambda: None, _cancel_arrow_hold_state=lambda: None,
        _cancel_wheel_scroll=lambda: None,
        save_data=lambda: events.append("save") or SaveOutcome.EXPORT_STALE,
        save_last_position=lambda: events.append("last_position"),
        _finalize_video_time=lambda: None,
    )
    monkeypatch.setattr(labeling_app.messagebox, "askyesno",
                        lambda title, message, **kw: questions.append(message) or answer)
    monkeypatch.setattr(labeling_app.messagebox, "showerror", lambda *a, **kw: pytest.fail("false save error"))

    if answer:
        # Past the confirmation the unload continues into Tk teardown, which
        # test_save_outcome.py covers; here only the decision matters.
        class Proceeded(Exception):
            pass

        def proceed():
            raise Proceeded

        app.save_last_position = proceed
        with pytest.raises(Proceeded):
            LabelingApp._unload_current_video(app)
    else:
        assert LabelingApp._unload_current_video(app) is False
        assert events == ["save"] and app.video_name == "old"
    assert len(questions) == 1 and "pose export" in questions[0].lower()


def test_special_zones_close_succeeds_when_only_the_export_failed(monkeypatch):
    warnings = []
    monkeypatch.setattr(labeling_app.messagebox, "showwarning",
                        lambda title, message, **kw: warnings.append(message))
    monkeypatch.setattr(labeling_app.theme, "set_button_state", lambda *a: None)
    outcome = {"value": SaveOutcome.EXPORT_STALE}
    app = SimpleNamespace(annotation_type="Pose", pose_session=SimpleNamespace(), _zone_masks=[],
                          special_zones_btn=object(), save_data=lambda: outcome["value"])
    assert LabelingApp.update_data_special_zones(app, {}, 1.0, "note") is True
    assert len(warnings) == 1
    outcome["value"] = SaveOutcome.NOT_SAVED
    assert LabelingApp.update_data_special_zones(app, {}, 1.0, "note") is False
    assert len(warnings) == 1


# === Don't save ===============================================================
def test_discard_close_publishes_nothing_and_saves_no_label(tmp_path, monkeypatch):
    app, paths, repo = _pose_app(tmp_path, monkeypatch)
    events = []
    _label(app, 1, 0.5)
    assert LabelingApp.save_data(app) is SaveOutcome.SAVED
    csv_before = open(paths.pose_export_csv, "rb").read()
    meta_before = open(paths.pose_export_metadata, "rb").read()

    _label(app, 2, 0.9)
    _note(app, 2, "discard me")
    app._current_video_time_s = lambda: 7200.0
    app._ask_how_to_close = lambda: LabelingApp._ask_how_to_close(app)
    app._confirm_discard = lambda unsaved: True
    app.save_last_position = lambda: LabelingApp.save_last_position(app)
    app._finalize_video_time = lambda: None
    app._close_state_repo = lambda: (events.append("close_state_repo"), repo.close())
    app.frame_buffer = SimpleNamespace(shutdown=lambda **kw: None)
    app._cancel_pending_timers = lambda: None
    app.destroy = lambda: events.append("destroy")
    app.save_data = lambda: pytest.fail("Don't save must not save")
    app._publish_pose_export = lambda: pytest.fail("Don't save must not export")
    monkeypatch.setattr(labeling_app, "custom_confirm_close", lambda root, **kw: CLOSE_DISCARD)

    LabelingApp.on_close(app)

    assert events == ["close_state_repo", "destroy"]
    assert open(paths.pose_export_csv, "rb").read() == csv_before
    assert open(paths.pose_export_metadata, "rb").read() == meta_before
    assert _stored_quality(paths, 2) is None and _stored_quality(paths, 1) == 0.5


def test_discard_close_of_a_never_exported_project_creates_no_export_folder(tmp_path, monkeypatch):
    app, paths, repo = _pose_app(tmp_path, monkeypatch)
    _label(app, 2, 0.9)
    app._ask_how_to_close = lambda: CLOSE_DISCARD
    app.save_last_position = lambda: None
    app._finalize_video_time = lambda: None
    app._close_state_repo = repo.close
    app.frame_buffer = SimpleNamespace(shutdown=lambda **kw: None)
    app._cancel_pending_timers = lambda: None
    app.destroy = lambda: None

    LabelingApp.on_close(app)

    assert not os.path.exists(paths.export_dir)
