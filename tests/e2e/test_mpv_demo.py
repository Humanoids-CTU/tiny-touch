"""Exercise the optional demo with real libmpv and a disposable synthetic video."""

from importlib import import_module
from pathlib import Path
import subprocess
import sys
import tkinter as tk

import cv2
import numpy as np
import pytest

from gui_driver import find_button, pump, wait_until


pytestmark = pytest.mark.gui


def test_mpv_demo_play_step_jump_and_load_failure(tmp_path):
    video = tmp_path / "numbered.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 240))
    assert writer.isOpened()
    try:
        for index in range(60):
            image = np.full((240, 320, 3), index * 4, dtype=np.uint8)
            cv2.putText(image, str(index), (40, 120), cv2.FONT_HERSHEY_SIMPLEX,
                        2, (0, 0, 255), 3)
            writer.write(image)
    finally:
        writer.release()

    # Tk/ttkbootstrap and native player state are process-wide. The standalone
    # demo must not replace the main application's default root or theme state.
    test_file = Path(__file__).resolve()
    root = test_file.parents[2]
    script = (
        "import runpy,sys; from pathlib import Path; "
        "sys.path.insert(0,sys.argv[1]); sys.path.insert(0,sys.argv[2]); "
        "runpy.run_path(sys.argv[3])['_exercise_demo'](Path(sys.argv[4]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(root), str(test_file.parent),
         str(test_file), str(video)],
        cwd=root, capture_output=True, text=True, timeout=45,
    )
    if result.returncode == 77:
        pytest.skip(result.stdout.strip())
    assert result.returncode == 0, result.stdout + result.stderr


def _exercise_demo(video):
    demo = import_module("demos.mpv_demo")
    try:
        mpv = demo.load_mpv()
    except (ImportError, OSError) as error:
        print(f"Optional demo runtime unavailable: {error}")
        raise SystemExit(77) from error

    original_init = tk.Tk.__init__

    def hidden_init(root, *args, **kwargs):
        original_init(root, *args, **kwargs)
        root.attributes("-alpha", 0.0)
        # The GPU swap chain needs a real monitor even for an invisible window.
        root.geometry("+0+0")

    tk.Tk.__init__ = hidden_init
    app = demo.MpvDemo(mpv)
    try:
        app.open_video(video)
        wait_until(app, lambda: app.loaded and app.player.time_pos is not None,
                   what="mpv opens the video")
        assert app.player.pause
        assert app.player.video_out_params["w"] == 320

        app.frame_input.set("20")
        find_button(app, "Jump").invoke()
        wait_until(app, lambda: abs(app.player.time_pos - 2.0) < 0.02,
                   what="frame jump reaches 2 seconds")

        find_button(app, "Previous frame").invoke()
        wait_until(app, lambda: abs(app.player.time_pos - 1.9) < 0.02,
                   what="backward frame step")
        find_button(app, "Next frame").invoke()
        wait_until(app, lambda: abs(app.player.time_pos - 2.0) < 0.02,
                   what="forward frame step")

        find_button(app, "Play / Pause").invoke()
        wait_until(app, lambda: app.player.time_pos > 2.2, what="playback advances")
        find_button(app, "Play / Pause").invoke()
        assert app.player.pause
        position = app.player.time_pos
        pump(app, 0.3)
        assert abs(app.player.time_pos - position) < 0.02

        app.frame_input.set("not a frame")
        find_button(app, "Jump").invoke()
        assert "whole frame number" in app.message.get()
        app.frame_input.set("-1")
        find_button(app, "Jump").invoke()
        assert "start at 0" in app.message.get()
        app.frame_input.set("600")
        find_button(app, "Jump").invoke()
        assert "beyond" in app.message.get()

        app.hardware.set(False)
        app.change_hardware()
        wait_until(app, lambda: app.player.hwdec_current == "no",
                   what="software decoder becomes active")

        app.open_video(video.parent / "missing.mp4")
        wait_until(app, lambda: not app.loaded and str(app.open_button["state"]) == "normal",
                   what="failed load leaves Open enabled")
        app.open_video(video)
        wait_until(app, lambda: app.loaded, what="a valid file opens after an error")
    finally:
        app.close()
        tk.Tk.__init__ = original_init
