"""Main-app JPEG/GPU integration, frame identity, and automatic CPU fallback."""

import csv
import importlib.util
from pathlib import Path
from tkinter import ttk

import cv2
import numpy as np
from PIL import Image, ImageTk
import pytest

from adapters import config
import labeling_app
from gui.video_surface import VideoRendererError
from gui_driver import click, load_video, pump, save, wait_until, walk


pytestmark = pytest.mark.gui
spec = importlib.util.spec_from_file_location(
    "gpu_app_marker", Path(__file__).resolve().parents[2] / "demos" / "frame_identity.py")
marker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(marker)


@pytest.fixture(scope="module")
def marked_video(tmp_path_factory):
    path = tmp_path_factory.mktemp("gpu_app_video") / "gpu_4k.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25, (3840, 2160))
    assert writer.isOpened()
    try:
        for index in range(6):
            image = marker.numbered_frame(index).resize((3840, 2160))
            writer.write(cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR))
    finally:
        writer.release()
    return str(path)


def automatic_app(workspace, app_factory, video):
    settings = config.load_config()
    settings["video_renderer"] = "auto"
    config.save_config(settings)
    app = app_factory()
    load_video(app, workspace, video)
    wait_until(app, lambda: app.displayed_frame == 0, what="first frame painted")
    return app


def test_main_app_gpu_1080p_frames_navigation_resize_and_failure(
        workspace, app_factory, marked_video, monkeypatch):
    app = automatic_app(workspace, app_factory, marked_video)
    if app._gpu_video is None:
        pytest.skip("No accelerated foreign-window renderer on this machine")
    assert app._renderer_status.get() == "GPU"
    with Image.open(Path(app.video.frames_dir) / "frame0.jpg") as image:
        assert image.size == (1920, 1080)
    for target in (0, 1, 4, 5, 2, 0):
        if target != app.video.current_frame:
            app.next_frame(target - app.video.current_frame)
        wait_until(app, lambda: app.displayed_frame == target, what=f"GPU frame {target}")
        assert marker.read_marker(app._gpu_video.capture_frame()) == target
        assert app.frame_counter_label.cget("text") == f"{target} / 5"
    app.geometry("900x800")
    pump(app, .2)
    assert marker.read_marker(app._gpu_video.capture_frame()) == 0

    # The annotation/export must refer to the same independently read GPU ID.
    app.parameter_dic_insert(1)
    save(app)
    with open(workspace.project("gpu_4k").export_csv, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["Frame"] == "0"
    assert rows[0]["Parameter_1"] == "ON"
    assert rows[1]["Parameter_1"] == ""
    # A paused image must survive an expose without a navigation event.
    app._gpu_video.widget.event_generate("<Expose>")
    pump(app)
    assert marker.read_marker(app._gpu_video.capture_frame()) == 0

    def fail_upload(*args):
        raise VideoRendererError("injected GPU upload failure")

    monkeypatch.setattr(app._gpu_video, "show", fail_upload)
    app.next_frame(1)
    wait_until(app, lambda: app.displayed_frame == 1 and app._gpu_video is None,
               what="CPU fallback painted the requested frame")
    assert app._renderer_status.get() == "CPU (GPU unavailable)"
    assert app.frame_label.winfo_ismapped()
    assert marker.read_marker(ImageTk.getimage(app.image)) == 1
    assert app._buffer_context().resize_in_worker
    assert workspace.errors() == []


def test_no_gpu_initialization_keeps_cpu_playback_usable(workspace, app_factory, monkeypatch):
    def unavailable(*args):
        raise VideoRendererError("no accelerated renderer")

    monkeypatch.setattr(labeling_app, "GpuVideoSurface", unavailable)
    app = automatic_app(workspace, app_factory, workspace.video)
    assert app._gpu_video is None
    assert app.frame_label.winfo_ismapped()
    app.next_frame(1)
    wait_until(app, lambda: app.displayed_frame == 1, what="CPU frame 1")
    assert app.frame_counter_label.cget("text") == "1 / 9"
    assert workspace.errors() == []


def test_renderer_setting_switches_without_losing_annotations(workspace, app_factory, marked_video):
    app = automatic_app(workspace, app_factory, marked_video)
    if app._gpu_video is None:
        pytest.skip("No accelerated foreign-window renderer on this machine")
    app.video.frames.setdefault(0, {})["Note"] = "keep annotation"
    app._set_note_entry_text("unsaved draft")
    for mode in ("cpu", "auto", "cpu"):
        app.open_settings()
        window = app._settings_win
        selector = next(widget for widget in walk(window)
                        if isinstance(widget, ttk.Combobox)
                        and "Automatic (GPU preferred)" in widget.cget("values"))
        selector.set("CPU" if mode == "cpu" else "Automatic (GPU preferred)")
        click(window, "Save")  # applies and closes the window
        assert config.load_config()["video_renderer"] == mode
        wait_until(app, lambda: app.displayed_frame == 0 and app.frame_buffer.get(0) is not None,
                   what=f"frame rebuilt for {mode}")
        if mode == "cpu":
            assert app._gpu_video is None
            assert app.frame_label.winfo_ismapped()
            assert marker.read_marker(ImageTk.getimage(app.image)) == 0
        else:
            assert app._gpu_video is not None
            assert marker.read_marker(app._gpu_video.capture_frame()) == 0
        assert app.video.current_frame == 0
        assert app.video.frames[0]["Note"] == "keep annotation"
        assert app._get_note_entry_text() == "unsaved draft"
    assert workspace.errors() == []
