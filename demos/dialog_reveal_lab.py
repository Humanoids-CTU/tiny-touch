"""Dialog reveal lab: half-built frames when each TinyTouch window opens.

Opens every Toplevel the app can show, one per process, over a neutral
backdrop, and records (Windows) every frame the compositor presents plus (any
platform) every Tk geometry change. Reuses the capture and frame
classification of ``demos/loading_lab.py``; see its docstring for what counts
as a dirty frame.

Approaches:
    today   ``BASELINE_SRC`` (the code before the reveal hook: withdraw, centre,
            deiconify, 30 ms + 3-step fade)
    hooked  this checkout's ``src`` (gui.window_reveal: place_on_reveal, modal_grab)

Per dialog and approach: dirty frames, time to first visible frame, time to
the settled frame, and Tk ``<Configure>`` changes after the reveal (the
non-visual check, which also runs on Linux).

Screen runs take a desktop-wide lock (``CAPTURE_LOCK``) per case, so other
capture jobs never overlap. Run from the repository root:

    uv run demos/dialog_reveal_lab.py
"""

import ctypes
import json
import multiprocessing as mp
import os
import queue
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from types import MethodType, SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "demos"))
import loading_lab as lab  # noqa: E402

# --- Tunables ---------------------------------------------------------------
DIALOGS = ("confirm_close", "labeling_mode", "settings", "frame_dialog", "open_touches", "template",
           "zone_names", "special_zones", "progress_copy", "progress_frames", "export", "library",
           "duplicate", "wizard", "dropdown")
APPROACHES = ("today", "hooked")
REPEATS = 3
BASELINE_SRC = Path(os.environ.get("TINYTOUCH_BASELINE_SRC", ROOT / "src"))
OUTPUT_DIR = Path(tempfile.gettempdir()) / "tinytouch_loading_lab" / "dialogs"
CAPTURE_LOCK = Path(tempfile.gettempdir()) / "tinytouch_capture_lock"
LOCK_RETRY_S = 3
LOCK_GIVE_UP_S = 900
OPEN_HOLD_MS = 2200          # watch this long after the open action
COPY_UPDATES = 12            # synchronous progress window: update() calls
COPY_UPDATE_MS = 40
BACKDROP_GEOMETRY = lab.BACKDROP_GEOMETRY
CASE_TIMEOUT_S = 40
ES_FLAGS = 0x80000000 | 0x2 | 0x1   # ES_CONTINUOUS | ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED

IS_WINDOWS = sys.platform == "win32"


# =============================================================================
# Case process
# =============================================================================
def _install_reveal_log(rec):
    import tkinter as tk
    original = tk.Wm.wm_attributes

    def attributes(self, *args, **kwargs):
        if len(args) >= 2 and args[0] == "-alpha" and str(self) != rec.root_path:
            if float(args[1]) > 0:
                rec.reveal(str(self), f"alpha={args[1]}")
        return original(self, *args, **kwargs)
    tk.Wm.wm_attributes = tk.Wm.attributes = attributes


def _lab_root(workdir):
    """The backdrop, doubling as the fake LabelingApp the dialogs need."""
    import tkinter as tk
    from labeling_app import LabelingApp

    class LabRoot(tk.Tk):
        pass

    root = LabRoot()
    root.config = SimpleNamespace(appearance="light", video_renderer="cpu")   # shadows Misc.config on purpose
    root._renderer_status = tk.StringVar(master=root, value="CPU")
    root.zone_display = SimpleNamespace(show_names=False, labels={})
    root.video = None
    root.coding_setup = None
    root.diagram_scale = 1.0
    root.labeling_mode = "Normal"
    for name in ("change_project_template", "edit_project_zone_names", "_open_logs_folder",
                 "apply_runtime_settings", "_save_zone_display"):
        setattr(root, name, lambda *a, **k: True)
    root._assert_ui_thread = lambda: None
    root._format_duration = MethodType(LabelingApp._format_duration, root)
    return root


def _openers(root, workdir):
    import tkinter as tk
    from tkinter import ttk
    from gui import app_dialogs
    from gui.app_dialogs import center_over_parent
    from labeling_app import LabelingApp
    from domain.templates import TEMPLATE_LABELS
    from domain.zone_display import ZoneDisplaySettings
    template = next(iter(TEMPLATE_LABELS))

    def progress_copy():
        update, close = LabelingApp._open_progress_window(root, "Copying Video", "Copying video to project...")
        for _ in range(COPY_UPDATES):   # the copy loop: work, then update() pumps events
            time.sleep(COPY_UPDATE_MS / 1000)
            update(0, 100, "Starting...", 0.0)
        root.after(OPEN_HOLD_MS - 600, close)

    def progress_frames():
        worker = threading.Thread(target=time.sleep, args=((OPEN_HOLD_MS - 400) / 1000,), daemon=True)
        job = SimpleNamespace(thread=worker, cancel_event=threading.Event(), progress=None,
                              start=worker.start, cancel=lambda: None)
        LabelingApp._open_progress_window(root, "Preparing Frames", "Preparing frames...", frame_job=job)

    def export():
        LabelingApp._run_export_with_progress(root, lambda: time.sleep((OPEN_HOLD_MS - 400) / 1000))

    def dropdown():
        DropdownList = __import__("gui.widgets", fromlist=["DropdownList"]).DropdownList
        DropdownList(root._lab_combo)

    from gui.special_zones_app import SpecialZonesApp
    from gui.frame_dialog import FrameDialog
    from gui.open_touches_dialog import OpenTouchesDialog
    from gui.template_dialog import choose_template
    from gui.zone_names_dialog import edit_zone_names
    from gui.video_library import choose_video, choose_existing_video
    from gui.coding_setup_wizard import configure_video
    touches = [SimpleNamespace(start_frame=100 * i + 7, limb=("LH", "RH", "LF")[i % 3]) for i in range(5)]
    zones = [f"ZONE_{i:02d}" for i in range(18)]
    entries = lab.library_entries(workdir)
    return {
        "confirm_close": lambda: app_dialogs.custom_confirm_close(root),
        "labeling_mode": lambda: app_dialogs.ask_labeling_mode(root),
        "settings": lambda: app_dialogs.open_settings(root),
        "frame_dialog": lambda: FrameDialog(root, 10, 1000),
        "open_touches": lambda: OpenTouchesDialog(root, touches, lambda limb: limb),
        "template": lambda: choose_template(root, template, center=center_over_parent),
        "zone_names": lambda: edit_zone_names(root, zones, ZoneDisplaySettings(), lambda labels: True,
                                              center=center_over_parent),
        "special_zones": lambda: SpecialZonesApp(root, lambda *a, **k: None, lambda *a, **k: None),
        "progress_copy": progress_copy,
        "progress_frames": progress_frames,
        "export": export,
        "library": lambda: choose_video(root, entries, center=center_over_parent),
        "duplicate": lambda: choose_existing_video(root, "session.mp4", "session (2).mp4",
                                                   center=center_over_parent),
        "wizard": lambda: configure_video(root, None, center=center_over_parent),
        "dropdown": dropdown,
    }


def run_dialog(dialog, approach, out_q, workdir):
    import tkinter as tk
    from tkinter import ttk
    from gui import theme
    rec = lab.Recorder(out_q)
    root = _lab_root(workdir)
    w, h, x, y = BACKDROP_GEOMETRY
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.title("Dialog reveal lab backdrop")
    root.attributes("-topmost", True)
    theme.init_style(root, "light")
    root.configure(bg=theme.WIN)
    rec.install(root)
    _install_reveal_log(rec)
    # An animated bar would read as dirty frames in both approaches alike.
    ttk.Progressbar.start = lambda self, interval=None: None
    combo = ttk.Combobox(root, values=("Automatic (GPU preferred)", "CPU", "Third option"), state="readonly",
                         width=28)
    combo.set("CPU")
    combo.place(x=theme.px(600), y=theme.px(300))
    root._lab_combo = combo
    opener = _openers(root, workdir)[dialog]

    def finish():
        rec.mark("finish")
        out_q.put(("result", rec.result()))
        out_q.put(("done",))
        out_q.close()
        out_q.join_thread()
        os._exit(0)   # closes any modal loop still on the stack

    def act():
        rec.mark("open")
        t = time.perf_counter()
        try:
            opener()
        finally:
            rec.marks.append((time.perf_counter(), f"open:returned:{(time.perf_counter() - t) * 1000:.0f}ms"))

    def start():
        root.update_idletasks()
        out_q.put(("region", (root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height(), 1)))
        root.after(OPEN_HOLD_MS + lab.CAPTURE_LEAD_MS, finish)   # timers run inside modal loops too
        root.after(lab.CAPTURE_LEAD_MS, act)
    root.after(lab.BACKDROP_SETTLE_MS, start)
    root.mainloop()


def case_main(dialog, approach, out_q, workdir):
    try:
        if IS_WINDOWS:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        src = BASELINE_SRC if approach == "today" else ROOT / "src"
        sys.path.insert(0, str(src))
        os.chdir(workdir)
        config_path = Path(workdir) / "config.json"
        config_path.write_text(json.dumps(lab.APP_CONFIG), encoding="utf-8")
        from adapters import config
        config.get_app_dir = lambda: str(workdir)
        config.get_config_path = lambda: str(config_path)
        import labeling_app  # noqa: F401  (imported up front, as in the running app)
        out_q.put(("src", str(Path(labeling_app.__file__).parent)))
        run_dialog(dialog, approach, out_q, workdir)
    except Exception:
        out_q.put(("error", traceback.format_exc()))
    out_q.put(("done",))


# =============================================================================
# Orchestrator
# =============================================================================
class CaptureLock:
    """Desktop-wide mutex shared with other capture jobs (mkdir is atomic)."""

    def __enter__(self):
        deadline = time.time() + LOCK_GIVE_UP_S
        while True:
            try:
                CAPTURE_LOCK.mkdir()
                return self
            except FileExistsError:
                if time.time() > deadline:
                    raise TimeoutError(f"capture lock {CAPTURE_LOCK} held too long")
                time.sleep(LOCK_RETRY_S)

    def __exit__(self, *exc):
        try:
            CAPTURE_LOCK.rmdir()
        except OSError:
            pass


def run_case(capture, dialog, approach, repeat):
    ctx = mp.get_context("spawn")
    backdrop_stop = ctx.Event()
    backdrop = ctx.Process(target=lab.screen_backdrop_main, args=(backdrop_stop,), daemon=True)
    backdrop.start()
    time.sleep(1.2)
    out_q = ctx.Queue()
    workdir = OUTPUT_DIR / "work" / f"{dialog}-{approach}-{repeat}"
    workdir.mkdir(parents=True, exist_ok=True)
    process = ctx.Process(target=case_main, args=(dialog, approach, out_q, str(workdir)), daemon=True)
    process.start()
    stop, holder, thread = threading.Event(), {}, None
    result = error = src = None
    deadline = time.time() + CASE_TIMEOUT_S
    try:
        while time.time() < deadline:
            try:
                message = out_q.get(timeout=0.5)
            except queue.Empty:
                if not process.is_alive():
                    break
                continue
            if message[0] == "region" and capture is not None:
                x, y, w, h, down = holder["region"] = message[1]
                thread = threading.Thread(target=lambda: holder.update(
                    zip(("frames", "missed"), capture.record((x, y, w, h), stop, down))), daemon=True)
                thread.start()
            elif message[0] == "region":
                holder["region"] = message[1]
            elif message[0] == "src":
                src = message[1]
            elif message[0] == "result":
                result = message[1]
            elif message[0] == "error":
                error = message[1]
            elif message[0] == "done":
                break
    finally:
        case_end = time.perf_counter()
        time.sleep(0.2)
        stop.set()
        if thread is not None:
            thread.join(timeout=5)
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
        backdrop_stop.set()
        backdrop.join(timeout=5)
        if backdrop.is_alive():
            backdrop.kill()
    if error or result is None:
        return {"error": error or "no result (timeout)"}
    finish = next((t for t, label in result["marks"] if label == "finish"), case_end)
    frames = holder.get("frames", [])
    segments = lab.analyse(frames, result, finish, holder.get("region"))
    return {"segments": segments, "frames_total": len(frames), "src": src, "result": result}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    capture = None
    if IS_WINDOWS:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        ctypes.windll.kernel32.SetThreadExecutionState(ES_FLAGS)
        try:
            capture = lab.DesktopCapture()
        except OSError as exc:
            print(f"Desktop capture unavailable ({exc}); Tk-side metrics only.")
    else:
        print("Desktop capture is Windows-only; Tk-side metrics only.")
    dialogs = [d for d in os.environ.get("LAB_DIALOGS", ",".join(DIALOGS)).split(",") if d]
    approaches = [a for a in os.environ.get("LAB_APPROACHES", ",".join(APPROACHES)).split(",") if a]
    repeats = int(os.environ.get("LAB_REPEATS", REPEATS))
    summary = []
    try:
        for dialog in dialogs:
            for approach in approaches:
                for repeat in range(repeats):
                    with CaptureLock():
                        outcome = run_case(capture, dialog, approach, repeat)
                    if "error" in outcome:
                        print(f"{dialog:16} {approach:7} r{repeat}: ERROR {outcome['error'].strip().splitlines()[-1]}",
                              flush=True)
                        summary.append({"dialog": dialog, "approach": approach, "repeat": repeat,
                                        "error": outcome["error"]})
                        continue
                    for seg in outcome["segments"]:
                        if repeat == 0:
                            lab.frame_strip(OUTPUT_DIR / f"strip_{dialog}_{approach}.png",
                                            f"{dialog} / {approach}", seg["rows"])
                        row = {k: v for k, v in seg.items() if k != "rows"}
                        row.update(dialog=dialog, approach=approach, repeat=repeat, src=outcome["src"],
                                   kinds="".join(r["kind"][0] for r in seg["rows"]),
                                   frames_total=outcome["frames_total"],
                                   returned=[m for _, m in outcome["result"]["marks"] if ":returned:" in m])
                        summary.append(row)
                        print(f"{dialog:16} {approach:7} r{repeat} dirty={seg['dirty']:2} ({seg['dirty_ms']:6.1f} ms) "
                              f"visible={seg['visible_ms']} settled={seg['settled_ms']} reveal={seg['reveal_ms']} "
                              f"tk_after={seg['tk_changes_after_reveal']:3} kinds={row['kinds'][:40]}", flush=True)
    finally:
        if IS_WINDOWS:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        (OUTPUT_DIR / "results.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print_table(summary)
    print(f"\nFrame strips and results.json: {OUTPUT_DIR}")


def print_table(summary):
    from statistics import median
    groups = {}
    for row in summary:
        if "error" not in row:
            groups.setdefault((row["dialog"], row["approach"]), []).append(row)
    print("\ndialog           approach dirty(max) dirty_ms(med) visible_ms(med) settled_ms(med) tk_after(max) n")
    for (dialog, approach), rows in groups.items():
        def med(key):
            values = [r[key] for r in rows if r[key] is not None]
            return median(values) if values else float("nan")
        print(f"{dialog:16} {approach:8} {max(r['dirty'] for r in rows):10} {med('dirty_ms'):13.1f} "
              f"{med('visible_ms'):15.1f} {med('settled_ms'):15.1f} {max(r['tk_changes_after_reveal'] for r in rows):13} "
              f"{len(rows)}")


if __name__ == "__main__":
    main()
