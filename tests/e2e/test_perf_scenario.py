"""
tests/e2e/test_perf_scenario.py

OBJECTIVE, repeatable performance scenario against the REAL app — the
"robot user" that replaces a human driving the .exe, so before/after
comparisons of buffer/decode changes are apples to apples.

Runs the real LabelingApp (hidden, off-screen, real geometry) through a
FIXED, seeded workload via the same widget callbacks a user hits:

  0. idle     — 1 s of nothing: the event-loop lag floor of this machine
  1. load     — Load Video through the button: copy + frame extraction +
                first paint, wall time
  2. steps    — 100 single `>` steps, press -> frame PAINTED latency
  3. jumps    — 30 seeded `<<` / `>>` jumps, press -> frame PAINTED latency
  4. playback — 10 s of Play: achieved fps, stall fraction, and the jitter
                of the intervals between painted frames
  5. resize   — 20 window resizes in 1 s, then time until a frame at the new
                size is painted, and how many decodes that cost
  6. perf     — the app's own PerfLogger counters (load_frame_total,
                display_frame_photo, ui_marshal, duplicate_decode, ...)

The whole scenario runs INSIDE a real `mainloop()`, exactly like production.
This matters: a worker thread's `Tk.after()` only works while the main thread
is in `mainloop()`. From an `update()`-pumping loop (what `gui_driver.pump`
does) tkinter makes the worker wait ~1 s and then raises "main thread is not
in main loop", so the buffer thread's repaints never arrive and every such
call stalls it for a second. The scenario is therefore a generator
(`_scenario`) that yields `Wait` conditions; `_run_in_mainloop` advances it
from an `after()` tick.

"Painted" means a `frame_paint_listeners` call — the frame is on screen —
NOT merely buffered; latencies are taken from those exact paint timestamps.
Throughout every phase a 5 ms `after()` heartbeat measures how late the Tk
event loop runs callbacks (`lag_*`): that lateness is the jank a user feels.

The metric ids (M1..M9) refer to tests/perf/SMOOTHNESS_PLAN.md.

Results are printed AND written as JSON under tests/perf/results/ with the
git revision + a label, so runs can be diffed later
(tests/perf/run_perf_matrix.py runs the whole matrix and summarizes it).

USAGE (deliberately opt-in — this takes 1-2 minutes):
  $env:TINYTOUCH_PERF = "1"
  $env:TINYTOUCH_PERF_LABEL = "baseline"          # optional, default "run"
  $env:TINYTOUCH_PERF_VIDEO = "videos\\sample_2160p.mp4"  # optional
  $env:TINYTOUCH_PERF_PANEL = "fullscreen"        # optional, default "default"
  uv run pytest tests/e2e/test_perf_scenario.py -m gui -s

Default video: videos/sample_1080p.mp4 (tests/perf/make_sample_videos.py
regenerates the samples).
"""

import json
import os
import random
import statistics
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

import pytest
from PIL import Image

from adapters.frame_buffer import compute_target_size
from gui_driver import click, load_video

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RESULTS_DIR = os.path.join(_REPO_ROOT, "tests", "perf", "results")

IDLE_SECONDS = 1.0
STEP_COUNT = 100
JUMP_COUNT = 30
JUMP_SECONDS = 5.0          # -> 125 frames at 25 fps; big enough to leave cache
PLAYBACK_SECONDS = 10.0
RESIZE_COUNT = 20
RESIZE_INTERVAL_S = 0.05    # 20 resizes over ~1 s, like a window-edge drag
RESIZE_STEP_PX = (10, 5)    # (width, height) shrink per resize event
HEARTBEAT_MS = 5
DRIVER_TICK_MS = 1
STALL_SAMPLE_MS = 50
RNG_SEED = 7
PANEL_VARIANTS = ("default", "fullscreen")

pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(
        not os.environ.get("TINYTOUCH_PERF"),
        reason="perf scenario is opt-in: set TINYTOUCH_PERF=1",
    ),
]


# === measurement helpers ======================================================
class Heartbeat:
    """A repeating `after(HEARTBEAT_MS)` whose lateness is the event-loop lag.

    Every tick records how much later than scheduled it ran, tagged with the
    current phase. A busy Tk thread (a slow repaint, a blocking call, a
    `sleep` between nested `update()` pumps) shows up directly as lateness.
    """

    def __init__(self, app):
        self._app = app
        self._due = None
        self._after_id = None
        self.phase = None
        self.samples = {}          # phase -> [lateness ms, ...]

    def start(self):
        self._arm()

    def stop(self):
        if self._after_id is not None:
            try:
                self._app.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _arm(self):
        self._due = time.perf_counter() + HEARTBEAT_MS / 1000.0
        self._after_id = self._app.after(HEARTBEAT_MS, self._tick)

    def _tick(self):
        lateness_ms = (time.perf_counter() - self._due) * 1e3
        if self.phase is not None:
            self.samples.setdefault(self.phase, []).append(lateness_ms)
        self._arm()

    def summary(self, phase):
        xs = sorted(self.samples.get(phase, []))
        if not xs:
            return {"lag_p50_ms": None, "lag_p95_ms": None, "lag_max_ms": None, "n": 0}
        return {
            "lag_p50_ms": round(xs[len(xs) // 2], 1),
            "lag_p95_ms": round(xs[int(len(xs) * 0.95)], 1),
            "lag_max_ms": round(xs[-1], 1),
            "n": len(xs),
        }


class PaintRecorder:
    """Collects (timestamp, frame, size) for every real paint."""

    def __init__(self, app):
        self.paints = []
        app.frame_paint_listeners.append(self._on_paint)

    def _on_paint(self, frame_number, size):
        self.paints.append((time.perf_counter(), frame_number, size))

    def first(self, since, frame, size=None):
        """Timestamp of the first paint of `frame` (at `size`) after `since`."""
        for t, f, s in self.paints:
            if t >= since and f == frame and (size is None or s == size):
                return t
        return None


@dataclass
class Wait:
    """Yielded by the scenario: resume once `predicate()` is true."""
    predicate: Callable[[], bool]
    timeout: float
    what: str
    detail: Callable[[], str] = lambda: ""   # extra state for the timeout message


def _sleep(seconds):
    deadline = time.perf_counter() + seconds
    return Wait(lambda: time.perf_counter() >= deadline, seconds + 5.0, "sleep")


def _run_in_mainloop(app, scenario):
    """Drive the `scenario` generator from inside a real mainloop()."""
    state = {"wait": None, "deadline": None, "error": None}

    def tick():
        try:
            wait = state["wait"]
            if wait is not None:
                if not wait.predicate():
                    if time.perf_counter() >= state["deadline"]:
                        raise AssertionError(
                            f"timed out after {wait.timeout}s waiting for {wait.what}"
                            f"{wait.detail()}")
                    app.after(DRIVER_TICK_MS, tick)
                    return
            wait = next(scenario)
            state["wait"] = wait
            state["deadline"] = time.perf_counter() + wait.timeout
            app.after(0 if wait.predicate() else DRIVER_TICK_MS, tick)
        except StopIteration:
            app.quit()
        except BaseException as exc:  # surfaced to pytest after mainloop returns
            state["error"] = exc
            app.quit()

    app.after(0, tick)
    app.mainloop()
    if state["error"] is not None:
        raise state["error"]


def _percentile(xs, pct):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * pct))]


def _git_rev():
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=_REPO_ROOT,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def _perf_snapshot(app):
    """The app's own PerfLogger counters as plain dicts (ms)."""
    out = {}
    with app.perf._lock:
        for name, s in app.perf._stats.items():
            out[name] = {
                "avg_ms": round(s.total / s.count * 1e3, 2) if s.count else 0,
                "max_ms": round(s.max * 1e3, 2),
                "total_ms": round(s.total * 1e3, 1),
                "n": s.count,
            }
    return out


def _perf_count(app, name):
    with app.perf._lock:
        stats = app.perf._stats.get(name)
        return stats.count if stats else 0


def _sharp_size(app):
    """The size a frame painted at the CURRENT panel geometry must have."""
    frame_path = os.path.join(
        app.video.frames_dir, f"frame{app.video.current_frame}.jpg")
    with Image.open(frame_path) as im:
        orig = im.size
    return compute_target_size(
        *orig,
        app.video_frame.winfo_width(),
        app.video_frame.winfo_height(),
        float(getattr(app, "video_downscale", 1.0) or 1.0),
    )


# === the scenario =============================================================
def _scenario(app, workspace, video, panel, results, heartbeat, paints):
    """The fixed workload. Every `yield` hands control back to mainloop()."""
    if panel == "fullscreen":
        # Windows clamps a larger geometry to the screen, so "fullscreen" is
        # the biggest panel this machine can show.
        app.geometry(f"{app.winfo_screenwidth()}x{app.winfo_screenheight()}")
        yield _sleep(0.3)

    # --- 0) idle: the lag floor of this machine -------------------------------
    heartbeat.phase = "idle"
    yield _sleep(IDLE_SECONDS)

    # --- 1) load: copy + extraction + first frame painted ---------------------
    heartbeat.phase = "load"
    t0 = time.perf_counter()
    load_video(app, workspace, video)
    yield Wait(lambda: app.displayed_frame is not None, 30, "first frame painted")
    results["load_s"] = round(time.perf_counter() - t0, 2)
    results["total_frames"] = app.video.total_frames
    results["frame_rate"] = app.video.frame_rate
    results["display_panel"] = (
        f"{app.video_frame.winfo_width()}x{app.video_frame.winfo_height()}")
    yield Wait(lambda: app.frame_buffer.buffer_ready, 30, "initial window buffered")

    # --- 2) 100 single steps (M1) ---------------------------------------------
    heartbeat.phase = "steps"
    latencies = []
    for _ in range(STEP_COUNT):
        target = app.video.current_frame + 1
        t0 = time.perf_counter()
        click(app, ">")
        yield Wait(lambda: paints.first(t0, target) is not None,
                   10, f"step to frame {target} painted")
        latencies.append((paints.first(t0, target) - t0) * 1e3)
    results["step_ms_median"] = round(statistics.median(latencies), 1)
    results["step_ms_p95"] = round(_percentile(latencies, 0.95), 1)

    # --- 3) 30 seeded jumps (M2) ----------------------------------------------
    heartbeat.phase = "jumps"
    rng = random.Random(RNG_SEED)
    jump = app.jump_frame_count
    total = app.video.total_frames
    latencies = []
    for _ in range(JUMP_COUNT):
        pos = app.video.current_frame
        if pos < 2 * jump:
            direction = 1
        elif pos > total - 2 * jump:
            direction = -1
        else:
            direction = rng.choice((-1, 1))
        target = max(0, min(total, pos + direction * jump))
        t0 = time.perf_counter()
        click(app, ">>" if direction > 0 else "<<")
        yield Wait(lambda: paints.first(t0, target) is not None,
                   15, f"jump to frame {target} painted")
        latencies.append((paints.first(t0, target) - t0) * 1e3)
    results["jump_frames"] = jump
    results["jump_ms_median"] = round(statistics.median(latencies), 1)
    results["jump_ms_p95"] = round(_percentile(latencies, 0.95), 1)
    results["jump_ms_max"] = round(max(latencies), 1)

    # --- 4) 10 s of playback (M3, M5) -----------------------------------------
    heartbeat.phase = None
    while app.video.current_frame > total // 4:    # rewind so playback has room
        click(app, "<<")
        yield _sleep(0.02)
    yield Wait(lambda: app.frame_buffer.buffer_ready, 15, "window buffered before playback")
    heartbeat.phase = "playback"
    start_frame = app.video.current_frame
    stall = {"stalled": 0, "samples": 0, "on": True}

    def sample_stall():
        if not stall["on"]:
            return
        stall["samples"] += 1
        if not app.frame_buffer.buffer_ready:
            stall["stalled"] += 1
        app.after(STALL_SAMPLE_MS, sample_stall)

    app.after(STALL_SAMPLE_MS, sample_stall)
    click(app, "Play")
    t0 = time.perf_counter()
    yield _sleep(PLAYBACK_SECONDS)
    elapsed = time.perf_counter() - t0
    click(app, "Stop")
    stall["on"] = False
    heartbeat.phase = None
    yield _sleep(0.1)
    advanced = app.video.current_frame - start_frame
    results["playback_fps"] = round(advanced / elapsed, 1)
    results["playback_target_fps"] = app.video.frame_rate
    results["playback_stall_pct"] = round(
        100 * stall["stalled"] / max(1, stall["samples"]), 1)
    stamps = [t for t, _, _ in paints.paints if t0 <= t <= t0 + elapsed]
    intervals = [(b - a) * 1e3 for a, b in zip(stamps, stamps[1:])]
    if len(intervals) >= 2:
        results["playback_interval_ms_median"] = round(statistics.median(intervals), 1)
        results["playback_interval_ms_p95"] = round(_percentile(intervals, 0.95), 1)
        results["playback_jitter_ms"] = round(statistics.stdev(intervals), 1)
    else:
        results["playback_interval_ms_median"] = None
        results["playback_interval_ms_p95"] = None
        results["playback_jitter_ms"] = None

    # --- 5) resize burst (M9) -------------------------------------------------
    heartbeat.phase = "resize"
    decodes_before = _perf_count(app, "load_frame_total")
    width, height = app.winfo_width(), app.winfo_height()
    for i in range(1, RESIZE_COUNT + 1):
        app.geometry(f"{width - RESIZE_STEP_PX[0] * i}x{height - RESIZE_STEP_PX[1] * i}")
        last_resize = time.perf_counter()
        yield _sleep(RESIZE_INTERVAL_S)
    app.update_idletasks()  # the final geometry is realized before we read it
    sharp = _sharp_size(app)
    current = app.video.current_frame

    # "Sharp" is a STATE — the latest paint shows the current frame at the
    # final size — not a new paint event: when the last resize steps don't
    # change the fitted image size (a 16:9 frame limited by the panel width
    # ignores height changes), the sharp frame is already on screen and
    # nothing needs repainting. Time is counted from the last geometry call.
    def sharp_on_screen():
        return bool(paints.paints) and paints.paints[-1][1:] == (current, sharp)

    def resize_state():
        """Everything needed to diagnose a missing sharp repaint."""
        shown = app._displayed_image.size if app._displayed_image is not None else None
        buffered = app.frame_buffer.get(app.video.current_frame)
        recent = [(round((t - last_resize) * 1e3), f, s)
                  for t, f, s in paints.paints if t >= last_resize - 1.0]
        return (
            f"\n  panel winfo={app.video_frame.winfo_width()}x"
            f"{app.video_frame.winfo_height()}"
            f" display cache={app._display_w}x{app._display_h}"
            f" current={app.video.current_frame}"
            f"\n  buffered size={buffered.size if buffered else None} shown size={shown}"
            f"\n  paints since last_resize-1s (ms, frame, size): {recent[-12:]}"
        )

    yield Wait(sharp_on_screen, 15,
               f"frame {current} on screen at the new size {sharp}", resize_state)
    results["resize_to_sharp_ms"] = round(
        max(0.0, paints.paints[-1][0] - last_resize) * 1e3, 1)
    results["resize_decodes"] = _perf_count(app, "load_frame_total") - decodes_before
    heartbeat.phase = None


def test_perf_scenario(app_factory, workspace):
    # The scenario needs the app's own perf counters and a real jump size;
    # rewrite the sandbox config BEFORE the app is constructed.
    config_path = os.path.join(str(workspace.root), "config.json")
    with open(config_path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg.update({"perf_enabled": True, "jump_seconds": JUMP_SECONDS})
    with open(config_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)

    video = os.environ.get(
        "TINYTOUCH_PERF_VIDEO", os.path.join("videos", "sample_1080p.mp4"))
    video = os.path.join(_REPO_ROOT, video) if not os.path.isabs(video) else video
    assert os.path.exists(video), (
        f"{video} not found — generate the sample videos first "
        "(uv run python tests/perf/make_sample_videos.py)")
    panel = os.environ.get("TINYTOUCH_PERF_PANEL", "default")
    assert panel in PANEL_VARIANTS, f"TINYTOUCH_PERF_PANEL must be one of {PANEL_VARIANTS}"

    app = app_factory()
    results = {
        "label": os.environ.get("TINYTOUCH_PERF_LABEL", "run"),
        "git_rev": _git_rev(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "video": os.path.basename(video),
        "panel": panel,
        "display_panel": None,   # filled after load
        "lag": {},
    }
    heartbeat = Heartbeat(app)
    paints = PaintRecorder(app)
    heartbeat.start()
    try:
        _run_in_mainloop(
            app, _scenario(app, workspace, video, panel, results, heartbeat, paints))
    finally:
        heartbeat.stop()

    # --- 6) the app's own perf counters + lag summary -------------------------
    for phase in ("idle", "load", "steps", "jumps", "playback", "resize"):
        results["lag"][phase] = heartbeat.summary(phase)
    results["perf_counters"] = _perf_snapshot(app)

    # --- report ----------------------------------------------------------------
    os.makedirs(RESULTS_DIR, exist_ok=True)
    out_name = (f"perf_{results['label']}_{results['git_rev']}_"
                f"{os.path.splitext(results['video'])[0]}_{panel}_"
                f"{time.strftime('%Y%m%d-%H%M%S')}.json")
    out_path = os.path.join(RESULTS_DIR, out_name)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)

    print("\n=== PERF SCENARIO RESULT ===")
    for key in ("label", "git_rev", "video", "panel", "display_panel",
                "total_frames", "load_s", "step_ms_median", "step_ms_p95",
                "jump_frames", "jump_ms_median", "jump_ms_p95", "jump_ms_max",
                "playback_fps", "playback_target_fps", "playback_stall_pct",
                "playback_interval_ms_median", "playback_interval_ms_p95",
                "playback_jitter_ms", "resize_to_sharp_ms", "resize_decodes"):
        print(f"  {key:28} {results[key]}")
    for phase, lag in results["lag"].items():
        print(f"  lag:{phase:24} p50 {lag['lag_p50_ms']} / p95 {lag['lag_p95_ms']}"
              f" / max {lag['lag_max_ms']} ms  (n={lag['n']})")
    top = sorted(results["perf_counters"].items(),
                 key=lambda kv: kv[1]["total_ms"], reverse=True)[:10]
    for name, s in top:
        print(f"  perf:{name:23} avg {s['avg_ms']:>8.2f} ms  "
              f"max {s['max_ms']:>8.2f} ms  n={s['n']}")
    print(f"  saved -> {os.path.relpath(out_path, _REPO_ROOT)}")
