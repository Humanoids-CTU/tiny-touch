"""Video load lab: what the main window shows while a video loads, and playback after it.

One process per case, over a neutral full-screen backdrop: the real
LabelingApp (window reveal on) loads a new video through the real library,
mode and setup dialogs, plays it, then resumes it from the library. For each
load, every frame the compositor presents (DXGI Desktop Duplication, see
``demos/loading_lab.py``) from the moment the load's last dialog was destroyed
is classified against the picture left by that dialog and the final frame:
dirty frames, and the time from the last dialog closing to the final frame.
Playback: frame_paint_listeners intervals and on-screen video updates.

Approaches:
    today   ``BASELINE_SRC`` (set ``TINYTOUCH_BASELINE_SRC`` to a copy of an
            older ``src``)
    app     this checkout's ``src`` (the load's content swap)
Renderers: ``gpu`` (``video_renderer`` auto, direct3d11 when available) and
``cpu``.

Screen runs hold a desktop-wide lock (``CAPTURE_LOCK``) per case and keep the
display awake. Run from the repository root (Windows only):

    uv run demos/video_load_lab.py
"""
import ctypes
import json
import multiprocessing as mp
import os
import queue
import shutil
import statistics
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "demos"))
import loading_lab as lab  # noqa: E402

APPROACHES = ("today", "app")
RENDERERS = ("gpu", "cpu")
REPEATS = 3
BASELINE_SRC = Path(os.environ.get("TINYTOUCH_BASELINE_SRC", ROOT / "src"))
OUTPUT_DIR = Path(tempfile.gettempdir()) / "tinytouch_loading_lab" / "load"
TEST_VIDEO = OUTPUT_DIR / "test_720p.mp4"
TEST_VIDEO_SIZE = (1280, 720)
TEST_VIDEO_FPS = 25.0
TEST_VIDEO_FRAMES = 300
CAPTURE_LOCK = Path(tempfile.gettempdir()) / "tinytouch_capture_lock"
LOCK_RETRY_S = 3
LOCK_GIVE_UP_S = 900
LOCK_STALE_S = 600            # an older lock was left by a killed run
STARTUP_S = 1.5               # main window settled before the capture starts
LOAD_WATCH_S = 1.5            # watch this long after each load's first frame
PLAY_S = 5.0
WAIT_TIMEOUT_S = 20
CASE_TIMEOUT_S = 150
ES_FLAGS = 0x80000000 | 0x2 | 0x1   # ES_CONTINUOUS | ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED
LOADS = ("load_new", "load_resume")


def make_test_video(path=TEST_VIDEO):
    """A synthetic 720p clip: a moving bar and the frame number."""
    if path.exists():
        return path
    import cv2
    path.parent.mkdir(parents=True, exist_ok=True)
    (w, h), partial = TEST_VIDEO_SIZE, path.with_suffix(".part.mp4")
    writer = cv2.VideoWriter(str(partial), cv2.VideoWriter_fourcc(*"mp4v"), TEST_VIDEO_FPS, (w, h))
    for i in range(TEST_VIDEO_FRAMES):
        frame = np.full((h, w, 3), 40, dtype=np.uint8)
        x = int((i * 17) % w)
        frame[:, max(0, x - 40):x + 40] = (60, 180, 240)
        frame[100:200, 100:100 + (i % 100) * 10] = (240, 240, 240)
        cv2.putText(frame, f"{i:04d}", (520, 420), cv2.FONT_HERSHEY_SIMPLEX, 4, (255, 255, 255), 8)
        writer.write(frame)
    writer.release()
    partial.replace(path)
    return path


class CaptureLock:
    """Desktop-wide mutex shared with other capture jobs (mkdir is atomic)."""

    def __enter__(self):
        deadline = time.time() + LOCK_GIVE_UP_S
        while True:
            try:
                CAPTURE_LOCK.mkdir()
                return self
            except FileExistsError:
                try:
                    stale = time.time() - CAPTURE_LOCK.stat().st_mtime > LOCK_STALE_S
                except OSError:
                    continue
                if stale:
                    shutil.rmtree(CAPTURE_LOCK, ignore_errors=True)
                    continue
                if time.time() > deadline:
                    raise TimeoutError(f"capture lock {CAPTURE_LOCK} held too long")
                time.sleep(LOCK_RETRY_S)

    def __exit__(self, *exc):
        shutil.rmtree(CAPTURE_LOCK, ignore_errors=True)


# =============================================================================
# Case process
# =============================================================================
def case_main(approach, renderer, play, video, out_q, workdir):
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        sys.path.insert(0, str(ROOT / "tests" / "e2e"))
        sys.path.insert(0, str(BASELINE_SRC if approach == "today" else ROOT / "src"))
        os.chdir(workdir)
        config_path = Path(workdir) / "config.json"
        config_path.write_text(json.dumps(dict(lab.APP_CONFIG, video_renderer="auto" if renderer == "gpu" else "cpu")),
                               encoding="utf-8")
        from adapters import config
        config.get_app_dir = lambda: str(workdir)
        config.get_config_path = lambda: str(config_path)
        from tkinter import filedialog, messagebox
        filedialog.askopenfilename = lambda **kw: str(video)
        for kind in ("showerror", "showwarning", "showinfo"):
            setattr(messagebox, kind, lambda *a, _k=kind, **k: out_q.put(("log", f"messagebox {_k} {a}")))
        messagebox.askyesno = lambda *a, **k: False
        run_loads(play, video, out_q)
    except BaseException:
        out_q.put(("error", traceback.format_exc()))
        out_q.put(("done",))
        os._exit(1)


def run_loads(play, video, out_q):
    import tkinter as tk
    from gui import theme
    rec = lab.Recorder(out_q)
    rec._on_map = lambda event: None
    original_init_style = theme.init_style

    def init_style(root, *a, **k):
        style = original_init_style(root, *a, **k)
        rec.install(root)
        rec.root_path = "<none>"
        root.attributes("-topmost", True)   # above the backdrop
        return style
    theme.init_style = init_style
    import labeling_app
    covers = []    # when a content swap's cover was on screen (the load's, with "app")
    try:
        from gui import content_swap
        original_over = content_swap._Cover.over

        def over(window):
            cover = original_over(window)
            covers.append(time.perf_counter())
            return cover
        content_swap._Cover.over = staticmethod(over)
    except ImportError:
        pass
    from gui_driver import click, dismiss_dialog, load_video, wait_until
    out_q.put(("src", str(Path(labeling_app.__file__).parent)))
    app = labeling_app.LabelingApp()
    app.state("zoomed")
    destroyed, paints = [], []

    def on_destroy(event):
        if isinstance(event.widget, tk.Toplevel) and str(event.widget).count(".") == 1:
            destroyed.append(time.perf_counter())
    app.bind_all("<Destroy>", on_destroy, add="+")
    app.frame_paint_listeners.append(lambda frame, size: paints.append(time.perf_counter()))
    extra = {"loads": {}}

    def pump(seconds):
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            app.update()
            time.sleep(0.005)

    def one_load(name, start):
        t0 = rec.mark(name)
        closed_before = len(destroyed)
        start()
        pump(LOAD_WATCH_S)
        closes = destroyed[closed_before:]
        last_close = max(closes) if closes else t0
        extra["loads"][name] = {
            "last_close": last_close, "dialogs_closed": len(closes),
            "cover_shown": next((t for t in covers if t >= last_close), None),
            "first_paint": next((t for t in paints if t >= t0), None),
            "renderer": app._renderer_status.get(), "gpu_name": getattr(app._gpu_video, "name", None),
            "painted": app.displayed_frame == app.video.current_frame,
        }
        rec.mark(name + "_end")

    def resume():
        dismiss_dialog(app, "Video library", "Resume")
        app.load_video_btn.invoke()
        wait_until(app, lambda: app.displayed_frame == app.video.current_frame, timeout=WAIT_TIMEOUT_S,
                   what="resumed frame painted")

    pump(STARTUP_S)
    screen = (0, 0, ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1))
    out_q.put(("region", (*screen, lab.MAIN_DOWNSAMPLE)))
    pump(lab.CAPTURE_LEAD_MS / 1000)
    one_load("load_new", lambda: load_video(app, SimpleNamespace(chosen_video=str(video), mode="Normal"), str(video)))
    if play:
        frame = app.video_frame
        extra["video_rect"] = (frame.winfo_rootx(), frame.winfo_rooty(), frame.winfo_width(), frame.winfo_height())
        wait_until(app, lambda: app.frame_buffer.buffer_ready, timeout=WAIT_TIMEOUT_S, what="buffered")
        start_frame = app.video.current_frame
        click(app, "Play")
        t1 = time.perf_counter()
        pump(PLAY_S)
        elapsed = time.perf_counter() - t1
        click(app, "Stop")
        stamps = [t for t in paints if t1 <= t <= t1 + elapsed]
        intervals = [(b - a) * 1e3 for a, b in zip(stamps, stamps[1:])]
        extra["play"] = {"t0": t1, "t1": t1 + elapsed, "paints": len(stamps),
                         "fps": round((app.video.current_frame - start_frame) / elapsed, 2)}
        if len(intervals) > 2:
            extra["play"].update(iv_med=round(statistics.median(intervals), 2),
                                 iv_sd=round(statistics.stdev(intervals), 2),
                                 iv_max=round(max(intervals), 2))
        pump(0.5)
    one_load("load_resume", resume)
    rec.mark("finish")
    result = rec.result()
    result["extra"] = extra
    out_q.put(("result", result))
    out_q.put(("done",))
    out_q.close()
    out_q.join_thread()
    os._exit(0)


# =============================================================================
# Orchestrator
# =============================================================================
def run_case(capture, approach, renderer, repeat, play=True):
    """One process: both loads (and playback); returns {"loads": [...], "play": {...}} or {"error"}."""
    video = make_test_video()
    ctx = mp.get_context("spawn")
    backdrop_stop = ctx.Event()
    backdrop = ctx.Process(target=lab.screen_backdrop_main, args=(backdrop_stop,), daemon=True)
    backdrop.start()
    time.sleep(1.5)
    out_q = ctx.Queue()
    workdir = OUTPUT_DIR / "work" / f"{approach}-{renderer}-{repeat}"
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)
    process = ctx.Process(target=case_main, args=(approach, renderer, play, str(video), out_q, str(workdir)),
                          daemon=True)
    process.start()
    stop, holder, thread = threading.Event(), {}, None
    result = error = None
    logs = []
    deadline = time.time() + CASE_TIMEOUT_S
    try:
        while time.time() < deadline:
            try:
                message = out_q.get(timeout=0.5)
            except queue.Empty:
                if not process.is_alive():
                    break
                continue
            if message[0] == "region":
                x, y, w, h, down = holder["region"] = message[1]
                thread = threading.Thread(target=lambda: holder.update(
                    zip(("frames", "missed"), capture.record((x, y, w, h), stop, down))), daemon=True)
                thread.start()
            elif message[0] == "result":
                result = message[1]
            elif message[0] == "error":
                error = message[1]
            elif message[0] == "log":
                logs.append(message[1])
            elif message[0] == "done":
                break
        else:
            error = error or f"case timed out after {CASE_TIMEOUT_S} s"
    finally:
        time.sleep(0.2)
        stop.set()
        if thread is not None:
            thread.join(timeout=10)
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
        backdrop_stop.set()
        backdrop.join(timeout=5)
        if backdrop.is_alive():
            backdrop.kill()
    if error or result is None:
        return {"error": error or "no result", "logs": logs}
    frames = holder.get("frames", [])
    outcome = {"frames_total": len(frames), "logs": logs,
               "loads": [analyse_load(name, result, frames, holder["region"], f"{approach}_{renderer}", repeat)
                         for name in LOADS]}
    if "play" in result["extra"]:
        outcome["play"] = analyse_play(result["extra"], frames, holder["region"])
    return outcome


def analyse_load(name, result, frames, region, label, repeat):
    """Frames presented after the load's last dialog closed, until the load's end mark."""
    info = result["extra"]["loads"][name]
    end = next(t for t, mark in result["marks"] if mark == name + "_end")
    last_close = info["last_close"]
    row = {"load": name, "renderer": info["renderer"], "gpu": info["gpu_name"], "painted": info["painted"],
           "dialogs_closed": info["dialogs_closed"],
           "first_paint_ms": round((info["first_paint"] - last_close) * 1000) if info["first_paint"] else None}
    after = [f for f in frames if last_close < f[0] < end]
    if not after:   # the screen never changed (resumed on the very frame it showed)
        row.update(frames=0, dirty=0, final_ms=0, kinds="")
        return row
    # The "old" picture: with a cover, what is on screen once the cover is up
    # (a copy of the window without the dialog; DwmFlush has presented it);
    # otherwise the first frame presented after the dialog closed.
    shown = info.get("cover_shown")
    covered = shown is not None and shown < end
    start = shown if covered else after[0][0]
    segment = {"marks": [(start, "open"), (end, "finish")], "changes": result["changes"],
               "reveals": [(start, "-", "now")], "full_mask": True}
    (s,) = lab.analyse(frames, segment, end, region)
    row.update(covered=covered, frames=s["frames"], dirty=s["dirty"], dirty_ms=s["dirty_ms"],
               kinds="".join(r["kind"][0] for r in s["rows"])[:40],
               final_ms=round((start - last_close) * 1000 + (s["settled_ms"] or 0)) if s["frames"] else 0)
    if repeat == 0:
        lab.frame_strip(OUTPUT_DIR / f"strip_{name}_{label}.png", f"{name} after the last dialog / {label}", s["rows"])
    return row


def analyse_play(extra, frames, region):
    play, down = extra["play"], region[4]
    vx, vy, vw, vh = extra["video_rect"]
    crop = (slice(vy // down, (vy + vh) // down), slice(vx // down, (vx + vw) // down))
    shown = [(t, img[crop]) for t, img in frames if play["t0"] <= t <= play["t1"]]
    updates, last = 0, None
    for _, img in shown:
        if last is None or not np.array_equal(img, last):
            updates += 1
            last = img
    row = {k: v for k, v in play.items() if k not in ("t0", "t1")}
    row["screen_ups"] = round(updates / (play["t1"] - play["t0"]), 2)
    if shown:
        row["video_std"] = round(float(shown[-1][1].astype(np.int16).std()), 1)   # not a blank panel
    return row


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    capture = lab.DesktopCapture()
    rows, plays = [], []
    ctypes.windll.kernel32.SetThreadExecutionState(ES_FLAGS)
    try:
        for repeat in range(REPEATS):
            for approach in APPROACHES:
                for renderer in RENDERERS:
                    with CaptureLock():
                        outcome = run_case(capture, approach, renderer, repeat)
                    label = f"{approach}_{renderer}"
                    if "error" in outcome:
                        print(label, repeat, "ERROR", outcome["error"][-1500:], flush=True)
                        continue
                    if not outcome["frames_total"]:
                        print(label, repeat, "no frames captured (screen locked or off?)", flush=True)
                        continue
                    for row in outcome["loads"]:
                        rows.append(dict(row, case=label, repeat=repeat))
                        print(json.dumps(rows[-1]), flush=True)
                    if "play" in outcome:
                        plays.append(dict(outcome["play"], case=label, repeat=repeat))
                        print(json.dumps(plays[-1]), flush=True)
    finally:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
    (OUTPUT_DIR / "results.json").write_text(json.dumps({"loads": rows, "play": plays}, indent=1), encoding="utf-8")
    print("\nload         case        dirty(med/max)  final_ms(med)")
    for name in LOADS:
        for approach in APPROACHES:
            for renderer in RENDERERS:
                rs = [r for r in rows if r["load"] == name and r["case"] == f"{approach}_{renderer}"
                      and r["dirty"] is not None]
                if rs:
                    print(f"{name:12} {approach + '_' + renderer:10} {statistics.median(r['dirty'] for r in rs):5}"
                          f"/{max(r['dirty'] for r in rs):<3} {statistics.median(r['final_ms'] for r in rs):10}")


if __name__ == "__main__":
    main()
