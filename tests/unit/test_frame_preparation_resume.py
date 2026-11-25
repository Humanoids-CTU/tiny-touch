"""Interrupted preparation must retain usable work without changing frame IDs."""
from pathlib import Path
import os
from threading import Event

import cv2
import numpy as np
import pytest

from adapters import frame_extractor
from adapters.sqlite_repo import SqliteRepository
from domain.coding_setup import default_coding_setup
from domain.project import ProjectPaths
from service_layer import project_service


@pytest.mark.parametrize("state", ["draft", "preparing"])
def test_accepted_setup_resumes_without_becoming_ready(tmp_path, state):
    paths = ProjectPaths("clip", str(tmp_path))
    Path(paths.state_dir).mkdir(parents=True)
    repo = SqliteRepository(paths.state_db)
    try:
        setup = default_coding_setup("alternate")
        repo.save_coding_setup(setup, preparation_state=state)
    finally:
        repo.close()
    assert project_service.can_resume_preparation(paths)
    assert project_service.inspect_coding_setup(paths) == (setup, False)
    reliability = ProjectPaths.for_video("clip", reliability=True, base_dir=str(tmp_path))
    assert project_service.inspect_coding_setup(reliability) == (default_coding_setup(), False)


def test_database_without_saved_setup_reopens_the_wizard_with_defaults(tmp_path):
    # A load can stop after the database exists but before the wizard's setup
    # is saved; that project starts over like a new one.
    paths = ProjectPaths("clip", str(tmp_path))
    repo = project_service.open_state(paths)
    try:
        project_service.apply_project_template(repo, project_service.TemplatePlan("alternate"))
    finally:
        repo.close()
    assert not project_service.can_resume_preparation(paths)
    assert project_service.inspect_coding_setup(paths) == (default_coding_setup(), False)


def test_missing_frame_is_never_ready_even_with_matching_count(tmp_path):
    for index in (0, 2, 3):
        (tmp_path / f"frame{index}.jpg").write_bytes(b"placeholder")
    assert not frame_extractor.check_items_count(str(tmp_path), 2)


@pytest.mark.parametrize("backend", ["ffmpeg", "opencv"])
def test_resume_preserves_prefix_and_repairs_truncated_tail(tmp_path, backend):
    video = tmp_path / "source.avi"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 25, (64, 48))
    assert writer.isOpened()
    try:
        for index in range(6):
            writer.write(np.full((48, 64, 3), 20 + index * 35, dtype=np.uint8))
    finally:
        writer.release()
    frames = tmp_path / "frames"
    frames.mkdir()
    extract = getattr(frame_extractor, f"_extract_frames_{backend}")
    assert extract(str(video), str(frames), None, .01)
    saved = [(frames / f"frame{i}.jpg").read_bytes() for i in range(2)]
    for index in (0, 1):
        path = frames / f"frame{index}.jpg"
        path.touch()
        os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    (frames / "frame2.jpg").write_bytes(b"truncated jpeg")
    (frames / "frame3.jpg").unlink()
    assert extract(str(video), str(frames), None, .01)
    assert [p.name for p in sorted(frames.glob("*.jpg"))] == [f"frame{i}.jpg" for i in range(6)]
    for index in range(2):
        path = frames / f"frame{index}.jpg"
        assert path.read_bytes() == saved[index]
        assert path.stat().st_mtime_ns == 1_000_000_000
    for index in range(6):
        image = cv2.imread(str(frames / f"frame{index}.jpg"))
        assert image is not None
        assert abs(float(image.mean()) - (20 + index * 35)) < 5


def test_cancelled_job_keeps_progress_off_ui_thread():
    from service_layer.frame_preparation import FramePreparationJob
    from threading import get_ident
    owner = get_ident()
    entered = Event()

    def extract(*, progress_cb, cancel_event):
        assert get_ident() != owner
        progress_cb(2, 10, "Generating frames", .1)
        entered.set()
        assert cancel_event.wait(2)
        raise frame_extractor.FrameExtractionCancelled("cancelled")

    job = FramePreparationJob(extract)
    job.start()
    assert entered.wait(2)
    assert job.progress == (2, 10, "Generating frames", .1)
    job.cancel()
    job.thread.join(2)
    assert not job.thread.is_alive()
    with pytest.raises(frame_extractor.FrameExtractionCancelled):
        job.result()


def test_progress_window_close_cancels_while_ui_keeps_processing(monkeypatch):
    """Exercise the real progress handler using a display-free event loop."""
    import time
    from threading import get_ident
    from types import SimpleNamespace
    import labeling_app
    from service_layer.frame_preparation import FramePreparationJob

    owner = get_ident()
    entered, cleanup_allowed = Event(), Event()

    def extract(*, progress_cb, cancel_event):
        entered.set()
        progress_cb(1, 10, "Generating frames", .1)
        assert cancel_event.wait(2)
        assert cleanup_allowed.wait(2)
        raise frame_extractor.FrameExtractionCancelled("cancelled")

    job = FramePreparationJob(extract)

    class Widget:
        def __init__(self, *args, **kwargs):
            self.text = kwargs.get("text", "")

        def pack(self, **kwargs):
            assert get_ident() == owner

        def config(self, **kwargs):
            assert get_ident() == owner
            self.text = kwargs.get("text", self.text)

        def __setitem__(self, key, value):
            assert get_ident() == owner

    class Window:
        def __init__(self):
            self.exists = True
            self.callbacks = []
            self.handlers = {}
            self.heartbeats = 0

        def withdraw(self): pass
        def title(self, value): pass
        def geometry(self, value): pass
        def resizable(self, *args): pass
        def transient(self, parent): pass
        def deiconify(self): pass
        def grab_set(self): pass
        def winfo_exists(self): return self.exists

        def protocol(self, name, callback):
            self.handlers[name] = callback

        def after(self, delay, callback):
            assert get_ident() == owner
            self.callbacks.append(callback)

        def destroy(self):
            assert not job.thread.is_alive(), "Window closed before writer cleanup"
            self.exists = False

        def wait_window(self):
            assert entered.wait(2)
            self.handlers["WM_DELETE_WINDOW"]()
            deadline = time.monotonic() + 3
            while self.exists and time.monotonic() < deadline:
                self.heartbeats += 1
                if self.heartbeats > 5:
                    cleanup_allowed.set()
                if self.callbacks:
                    self.callbacks.pop(0)()
                time.sleep(.001)
            assert not self.exists, "Cancellation stranded the progress window"

    window = Window()
    monkeypatch.setattr(labeling_app.tk, "Toplevel", lambda parent: window)
    for name in ("Frame", "Label", "Progressbar"):
        monkeypatch.setattr(labeling_app.ttk, name, Widget)
    monkeypatch.setattr(labeling_app.theme, "bind_colors", lambda *a, **kw: None)
    monkeypatch.setattr(labeling_app, "center_over_parent", lambda *a: None)
    app = SimpleNamespace(_format_duration=str)
    labeling_app.LabelingApp._open_progress_window(app, "Preparing", "Frames", frame_job=job)
    assert window.heartbeats > 5
    assert job.cancel_event.is_set()
    with pytest.raises(frame_extractor.FrameExtractionCancelled):
        job.result()


def test_cancel_before_ui_receives_completed_result_still_cancels():
    from service_layer.frame_preparation import FramePreparationJob
    job = FramePreparationJob(lambda **kwargs: 5)
    job.start()
    job.thread.join(2)
    assert not job.thread.is_alive()
    job.cancel()
    with pytest.raises(frame_extractor.FrameExtractionCancelled):
        job.result()
