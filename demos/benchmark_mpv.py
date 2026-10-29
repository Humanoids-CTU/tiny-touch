"""Playback-component comparison; configuration is in the constants below.

Run with uv run demos/benchmark_mpv.py. No annotation projects are opened.
Workers use the same file, selected internally through an environment variable.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import random
import shutil
import statistics
import subprocess
import sys
import threading
import time
import tkinter as tk

import psutil


ROOT = Path(__file__).resolve().parents[1]
VIDEOS = ("sample_1080p.mp4", "sample_2160p.mp4")
MODES = ("jpeg", "mpv-auto", "mpv-software")
REPEATS = 3
PLAYBACK_SECONDS = 20
PANEL_WIDTH = 1280
PANEL_HEIGHT = 720
STEPS_PER_DIRECTION = 25
JUMP_COUNT = 24
TICK_MS = 10
RESOURCE_INTERVAL_S = 0.25
RUN_TIMEOUT_S = 180
RESULTS_ROOT = ROOT / "demos" / "runtime" / "benchmarks"
CONFIG_PATH = ROOT / "demos" / "benchmark_config.json"


def write_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temp.replace(path)


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def distribution(values):
    if not values:
        return {"n": 0, "median": None, "p95": None, "max": None}
    ordered = sorted(values)
    return {"n": len(values), "median": statistics.median(values),
            "p95": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
            "max": ordered[-1]}


def load_snapshot(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Resources:
    def __init__(self, folder):
        self.folder = folder
        self.process = psutil.Process()
        self.phase = "startup"
        self.samples = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.starts = {}
        self.results = {}
        psutil.cpu_percent()
        self.thread.start()

    def _loop(self):
        while not self.stop.is_set():
            memory = self.process.memory_info()
            self.samples.append({"phase": self.phase, "rss_mb": memory.rss / 2**20,
                                 "private_mb": getattr(memory, "private", memory.rss) / 2**20,
                                 "system_cpu_pct": psutil.cpu_percent()})
            self.stop.wait(RESOURCE_INTERVAL_S)

    def begin(self, phase):
        self.phase = phase
        cpu = self.process.cpu_times()
        self.starts[phase] = (time.perf_counter(), cpu.user + cpu.system)
        write_json(self.folder / "current-job.json", {"pid": os.getpid(), "phase": phase})

    def end(self, phase):
        wall0, cpu0 = self.starts[phase]
        cpu = self.process.cpu_times()
        elapsed = time.perf_counter() - wall0
        samples = [s for s in self.samples if s["phase"] == phase]
        self.results[phase] = {
            "wall_s": elapsed, "cpu_s": cpu.user + cpu.system - cpu0,
            "cpu_machine_pct": (cpu.user + cpu.system - cpu0) / elapsed / (os.cpu_count() or 1) * 100,
            "rss_mean_mb": statistics.mean(s["rss_mb"] for s in samples) if samples else None,
            "rss_peak_mb": max((s["rss_mb"] for s in samples), default=None),
            "private_mean_mb": statistics.mean(s["private_mb"] for s in samples) if samples else None,
            "system_cpu_mean_pct": statistics.mean(s["system_cpu_pct"] for s in samples) if samples else None,
        }


class JpegBackend:
    """Existing FrameBuffer, display-size JPEG decode, PhotoImage paste and pacing."""
    def __init__(self, root, surface, job, notify):
        from PIL import ImageTk
        self.ImageTk = ImageTk
        self.root, self.job, self.notify = root, job, notify
        self.module = load_snapshot(Path(job["snapshot"]) / "frame_buffer.py", "bench_frame_buffer")
        timers = load_snapshot(Path(job["snapshot"]) / "timer_resolution.py", "bench_timers")
        self.timer = timers.PreciseTimers()
        self.current = 0
        self.direction = 1
        self.painted = None
        self.image = None
        self.shown = None
        self.label = tk.Label(surface, bg="black", bd=0)
        self.label.pack(expand=True)
        self.playing = False
        self.due = None
        self.after_id = None
        self.buffer = self.module.FrameBuffer(get_buffer_context=self.context)
        self.thread = threading.Thread(target=self.buffer.background_update, daemon=True)
        self.thread.start()
        self.buffer.poke()

    def context(self):
        return self.module.BufferContext(self.job["frames"], self.current,
                                        self.job["frame_count"] - 1, PANEL_WIDTH, PANEL_HEIGHT,
                                        1.0, int(5 * self.job["fps"]), self.direction)

    def poll(self):
        picture = self.buffer.get(self.current)
        if picture is None or picture is self.shown:
            return
        if self.image is not None and self.shown.size == picture.size:
            self.image.paste(picture)
        else:
            self.image = self.ImageTk.PhotoImage(picture)
            self.label.configure(image=self.image)
        self.shown = picture
        self.painted = self.current
        self.notify(self.current, time.perf_counter())

    def ready(self, target):
        return self.painted == target

    def frame(self):
        return self.painted if self.painted is not None else 0

    def request(self, target, step=None):
        if target != self.current:
            self.direction = 1 if target > self.current else -1
        self.current = target
        self.buffer.request_priority(target)
        self.poll()

    def play(self):
        self.playing = True
        self.due = None
        self.timer.hold("playback")
        self._play_tick()

    def _play_tick(self):
        if not self.playing:
            return
        if not all(i in self.buffer for i in range(self.current, self.current + 4)):
            self.buffer.request_priority(self.current + 1)
            self.due = None
            self.after_id = self.root.after(5, self._play_tick)
            return
        now = time.perf_counter()
        interval = 1 / self.job["fps"]
        if self.due is None or self.due < now - interval:
            self.due = now
        self.due += interval
        self.current += 1
        self.poll()
        self.after_id = self.root.after(max(1, round((self.due - time.perf_counter()) * 1000)), self._play_tick)

    def pause(self):
        self.playing = False
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.timer.release("playback")

    def details(self):
        return {"decoder": "Pillow JPEG / CPU", "dropped_frames": 0}

    def close(self):
        self.pause()
        self.buffer.shutdown(wait=True)
        self.thread.join(timeout=5)


class MpvBackend:
    def __init__(self, root, surface, job, notify):
        from mpv_demo import load_mpv
        self.job = job
        self.notify = notify
        self.last_frame = None
        self.player = load_mpv().MPV(
            wid=str(surface.winfo_id()), config=False, vo="gpu",
            hwdec="auto" if job["mode"] == "mpv-auto" else "no",
            pause=True, keep_open="yes", idle="yes", audio=False, osc=False,
            input_default_bindings=False, input_vo_keyboard=False,
            hr_seek_framedrop=False,
        )
        self.player.observe_property("time-pos", self._position)
        self.player.play(job["video"])

    def _position(self, name, value):
        if value is not None:
            frame = max(0, round(value * self.job["fps"]))
            if frame != self.last_frame:
                self.last_frame = frame
                self.notify(frame, time.perf_counter())

    def poll(self):
        pass

    def frame(self):
        position = self.player.time_pos
        return max(0, round(position * self.job["fps"])) if position is not None else 0

    def ready(self, target):
        return self.player.time_pos is not None and self.frame() == target and not self.player.seeking and bool(self.player.vo_configured)

    def request(self, target, step=None):
        if step is None:
            self.player.seek(target / self.job["fps"], "absolute", "exact")
        elif step < 0:
            self.player.frame_back_step()
        else:
            self.player.frame_step()

    def play(self):
        self.player.pause = False

    def pause(self):
        self.player.pause = True

    def details(self):
        return {"decoder": self.player.hwdec_current,
                "dropped_frames": self.player.frame_drop_count or 0,
                "decoder_dropped_frames": self.player.decoder_frame_drop_count or 0,
                "mpv_version": self.player.mpv_version}

    def close(self):
        self.player.terminate()


@dataclass
class Wait:
    predicate: object
    timeout: float = 30


def delay(seconds):
    deadline = time.perf_counter() + seconds
    return Wait(lambda: time.perf_counter() >= deadline, seconds + 5)


class Scenario:
    def __init__(self, job):
        self.job = job
        self.folder = Path(job["folder"])
        self.root = tk.Tk()
        self.root.title(f"Playback benchmark: {job['mode']} / {Path(job['video']).name}")
        self.root.geometry(f"{PANEL_WIDTH}x{PANEL_HEIGHT + 40}+40+40")
        self.root.resizable(False, False)
        self.status = tk.StringVar(value="Preparing benchmark")
        tk.Label(self.root, textvariable=self.status).pack()
        self.surface = tk.Frame(self.root, width=PANEL_WIDTH, height=PANEL_HEIGHT, bg="black")
        self.surface.pack()
        self.surface.pack_propagate(False)
        self.root.update_idletasks()
        self.resources = Resources(self.folder)
        self.backend = None
        self.events = []
        self.result = {"job": job, "worker_pid": os.getpid(), "harness_sha256": digest(Path(__file__)),
                       "latency_completion": "Tk image upload / mpv target time with seeking=false; not physical screen latency"}
        self.generator = self.run()
        self.wait = None
        self.wait_start = None
        self.root.protocol("WM_DELETE_WINDOW", lambda: self.finish("Benchmark window closed"))

    def notify(self, frame, stamp):
        self.events.append((frame, stamp))

    def phase(self, name):
        self.status.set(name)
        self.resources.begin(name)
        print(json.dumps({"phase": name, "pid": os.getpid()}), flush=True)

    def run(self):
        self.phase("load")
        started = time.perf_counter()
        backend_type = JpegBackend if self.job["mode"] == "jpeg" else MpvBackend
        self.backend = backend_type(self.root, self.surface, self.job, self.notify)
        yield Wait(lambda: self.backend.ready(0))
        self.result["reopen_ready_ms"] = (time.perf_counter() - started) * 1000
        self.resources.end("load")
        yield delay(1)
        self.backend.request(25)
        yield Wait(lambda: self.backend.ready(25))
        self.backend.play()
        yield delay(1)
        self.phase("playback")
        self.events.clear()
        frame0 = self.backend.frame()
        details0 = self.backend.details()
        started = time.perf_counter()
        yield delay(self.job["playback_seconds"])
        self.backend.pause()
        elapsed = time.perf_counter() - started
        frames_advanced = self.backend.frame() - frame0
        self.resources.end("playback")
        details = self.backend.details()
        self.result["playback"] = {
            "wall_s": elapsed, "frames_advanced": frames_advanced,
            "timeline_fps": frames_advanced / elapsed,
            "target_fps": self.job["fps"], "decoder": details["decoder"],
            "dropped_frames": details["dropped_frames"] - details0["dropped_frames"],
            "details": details,
            "notification_interval_ms": distribution([(b[1] - a[1]) * 1000 for a, b in zip(self.events, self.events[1:])]),
        }
        self.result["playback_notifications"] = list(self.events)
        self.backend.request(250)
        yield Wait(lambda: self.backend.ready(250))
        yield delay(0.5)
        for direction, phase in ((1, "forward_steps"), (-1, "backward_steps")):
            self.phase(phase)
            measurements = []
            for _ in range(STEPS_PER_DIRECTION):
                target = self.backend.frame() + direction
                started = time.perf_counter()
                self.backend.request(target, step=direction)
                yield Wait(lambda target=target: self.backend.ready(target))
                measurements.append((time.perf_counter() - started) * 1000)
                yield delay(0.05)
            self.result[phase] = distribution(measurements)
            self.result[phase + "_raw_ms"] = measurements
            self.resources.end(phase)
        self.phase("jumps")
        rng = random.Random(7)
        jumps = []
        for _ in range(JUMP_COUNT):
            target = rng.randrange(10, self.job["frame_count"] - 10)
            started = time.perf_counter()
            self.backend.request(target)
            yield Wait(lambda target=target: self.backend.ready(target))
            jumps.append({"target": target, "ready_ms": (time.perf_counter() - started) * 1000})
            yield delay(0.05)
        self.result["jumps"] = distribution([j["ready_ms"] for j in jumps])
        self.result["jumps_raw"] = jumps
        self.resources.end("jumps")

    def tick(self):
        try:
            if self.backend is not None:
                self.backend.poll()
            if self.wait is None or self.wait.predicate():
                self.wait = next(self.generator)
                self.wait_start = time.perf_counter()
            elif time.perf_counter() - self.wait_start > self.wait.timeout:
                raise TimeoutError(f"Timed out in {self.resources.phase}, current frame {self.backend.frame()}")
        except StopIteration:
            self.finish()
            return
        except Exception as error:
            self.finish(repr(error))
            return
        self.root.after(TICK_MS, self.tick)

    def finish(self, error=None):
        self.resources.stop.set()
        self.resources.thread.join(timeout=2)
        self.result["resources"] = self.resources.results
        self.result["resource_samples"] = self.resources.samples
        self.result["error"] = error
        write_json(Path(self.job["result"]), self.result)
        try:
            if self.backend is not None:
                self.backend.close()
        finally:
            self.root.destroy()


def prepare(folder):
    import cv2
    import imageio_ffmpeg
    snapshot = folder / "source_snapshot"
    snapshot.mkdir()
    hashes = {}
    for name in ("frame_buffer.py", "timer_resolution.py"):
        source = ROOT / "src" / "adapters" / name
        shutil.copyfile(source, snapshot / name)
        hashes[name] = digest(source)
    videos = []
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
    reuse = config.get("reuse_prepared_cache")
    cached_videos = []
    if reuse:
        cache_dir = (ROOT / reuse).resolve()
        cached_videos = json.loads((cache_dir / "metadata.json").read_text(encoding="utf-8"))["videos"]
    for name in VIDEOS:
        video = ROOT / "videos" / name
        capture = cv2.VideoCapture(str(video))
        try:
            fps = capture.get(cv2.CAP_PROP_FPS)
            count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            width, height = int(capture.get(3)), int(capture.get(4))
        finally:
            capture.release()
        if fps <= 0 or count / fps < PLAYBACK_SECONDS + 4:
            raise ValueError(f"Video too short or invalid: {video}")
        cached = next((v for v in cached_videos if v["video"] == str(video)
                       and v["source_bytes"] == video.stat().st_size
                       and v["frame_count"] == count and v["fps"] == fps), None)
        if cached is not None:
            files = list(Path(cached["frames"]).glob("frame*.jpg"))
            if len(files) != count or sum(p.stat().st_size for p in files) != cached["jpeg_bytes"]:
                raise RuntimeError("Prepared cache does not match its recorded inventory")
            videos.append(cached)
            cached["source_sha256"] = digest(video)
            print(f"Reusing validated benchmark JPEG cache for {name}", flush=True)
            continue
        frames = folder / (video.stem + "_frames")
        frames.mkdir()
        print(f"Preparing JPEGs for {name} (isolated benchmark cache)", flush=True)
        started = time.perf_counter()
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-nostats", "-loglevel", "error",
                        "-i", str(video), "-q:v", "2", "-start_number", "0",
                        str(frames / "frame%d.jpg")], check=True)
        extraction_s = time.perf_counter() - started
        files = list(frames.glob("frame*.jpg"))
        if len(files) != count:
            raise RuntimeError(f"Frame-count mismatch: {name}, {len(files)} vs {count}")
        videos.append({"video": str(video), "frames": str(frames), "fps": fps,
                       "frame_count": count, "width": width, "height": height,
                       "source_bytes": video.stat().st_size,
                       "source_sha256": digest(video),
                       "jpeg_bytes": sum(p.stat().st_size for p in files),
                       "extraction_s": extraction_s})
    return videos, hashes


def summarize(folder, records, metadata, show=False):
    grouped = defaultdict(list)
    for record in records:
        grouped[(Path(record["job"]["video"]).stem, record["job"]["mode"])].append(record)
    rows = []
    gpu_samples = []
    gpu_path = folder / "gpu.jsonl"
    if gpu_path.exists():
        for line in gpu_path.read_text(encoding="utf-8-sig").splitlines():
            try:
                gpu_samples.append(json.loads(line))
            except ValueError:
                continue
    for (video, mode), runs in grouped.items():
        def median(getter):
            return statistics.median(getter(r) for r in runs)
        pids = {r["job"]["pid"] for r in runs}
        gpu = [g for g in gpu_samples if g.get("pid") in pids and g.get("phase") == "playback" and g.get("engines")]
        busiest = [max(e["percent"] for e in g["engines"]) for g in gpu]
        row = {"video": video, "mode": mode, "runs": len(runs),
               "reopen_ms": median(lambda r: r["reopen_ready_ms"]),
               "fps": median(lambda r: r["playback"]["timeline_fps"]),
               "cpu_pct": median(lambda r: r["resources"]["playback"]["cpu_machine_pct"]),
               "rss_mb": median(lambda r: r["resources"]["playback"]["rss_mean_mb"]),
               "private_mb": median(lambda r: r["resources"]["playback"]["private_mean_mb"]),
               "forward_p50_ms": median(lambda r: r["forward_steps"]["median"]),
               "backward_p50_ms": median(lambda r: r["backward_steps"]["median"]),
               "jump_p50_ms": median(lambda r: r["jumps"]["median"]),
               "jump_p95_ms": median(lambda r: r["jumps"]["p95"]),
               "notification_p95_ms": median(lambda r: r["playback"]["notification_interval_ms"]["p95"]),
               "drop_max": max(r["playback"]["dropped_frames"] for r in runs),
               "decoders": sorted({str(r["playback"]["decoder"]) for r in runs}),
               "gpu_busiest_engine_mean_pct": statistics.mean(busiest) if busiest else None,
               "gpu_samples": len(busiest)}
        rows.append(row)
    write_json(folder / "summary.json", {"metadata": metadata, "rows": rows,
               "completed_runs": len(records), "campaign_complete": len(records) == len(VIDEOS) * len(MODES) * REPEATS})
    lines = ["# Playback component benchmark", "", f"Results: {folder.name}", "",
             "Medians of completed interleaved runs (three planned per mode/video). CPU is percent of the whole machine; RAM is process working set.", "",
             "| Video | Mode | Reopen ms | FPS | CPU % | RAM MB | Forward ms | Backward ms | Jump median / p95 ms |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in rows:
        lines.append(f"| {row['video']} | {row['mode']} | {row['reopen_ms']:.0f} | {row['fps']:.2f} | {row['cpu_pct']:.2f} | {row['rss_mb']:.0f} | {row['forward_p50_ms']:.1f} | {row['backward_p50_ms']:.1f} | {row['jump_p50_ms']:.1f} / {row['jump_p95_ms']:.1f} |")
    lines.extend(["", "Playback-only shell: existing FrameBuffer and equivalent Tk image upload/pacing; annotation UI excluded.",
                  "mpv uses original video with audio disabled. Both render into the same 1280x720 panel.",
                  "Latency ends at Tk upload or mpv target time with seeking=false, not physical screen presentation.",
                  "FPS is timeline progression; mpv frame-drop counts are reported separately in summary.json.",
                  "Notification jitter is backend-specific and is not a directly comparable screen-smoothness measurement.",
                  "First JPEG extraction is measured once; reopening uses an existing JPEG cache. OS caches are not flushed.",
                  "GPU is the mean busiest per-process engine utilization, not a sum across GPU engines.",
                  "Raw CPU/memory samples, navigation requests, native counters and source hashes are retained."])
    (folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if show:
        print("\n".join(lines), flush=True)


def coordinator():
    folder = RESULTS_ROOT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder.mkdir(parents=True)
    videos, hashes = prepare(folder)
    battery = psutil.sensors_battery()
    metadata = {"utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
                "python": sys.version, "logical_cpus": os.cpu_count(), "ram_gb": psutil.virtual_memory().total / 2**30,
                "power_plugged": battery.power_plugged if battery else None,
                "source_hashes": hashes, "harness_sha256": digest(Path(__file__)),
                "videos": videos, "panel": [PANEL_WIDTH, PANEL_HEIGHT],
                "playback_seconds": PLAYBACK_SECONDS, "repeats": REPEATS}
    write_json(folder / "metadata.json", metadata)
    gpu_process = None
    gpu_out = (folder / "gpu.jsonl").open("w", encoding="utf-8")
    gpu_error = (folder / "gpu-errors.txt").open("w", encoding="utf-8")
    environment = os.environ.copy()
    environment["TINYTOUCH_BENCH_DIR"] = str(folder)
    if os.name == "nt":
        gpu_process = subprocess.Popen(["powershell", "-NoProfile", "-File", str(ROOT / "demos" / "benchmark_gpu.ps1")],
                                       env=environment, stdout=gpu_out, stderr=gpu_error,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
    records = []
    try:
        for video in videos:
            for repeat in range(REPEATS):
                order = MODES if repeat % 2 == 0 else tuple(reversed(MODES))
                for mode in order:
                    name = f"{Path(video['video']).stem}_{repeat + 1}_{mode}"
                    job = {**video, "mode": mode, "repeat": repeat + 1, "folder": str(folder),
                           "snapshot": str(folder / "source_snapshot"), "result": str(folder / (name + ".json")),
                           "playback_seconds": PLAYBACK_SECONDS}
                    path = folder / "job.json"
                    write_json(path, job)
                    environment["TINYTOUCH_BENCH_WORKER"] = str(path)
                    print(f"RUN {name}", flush=True)
                    with (folder / (name + ".stderr.txt")).open("w", encoding="utf-8") as stderr:
                        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve())],
                                                   env=environment, stdout=subprocess.PIPE, stderr=stderr, text=True)
                        try:
                            # Timer enforces the run deadline even if a native driver blocks stdout.
                            timeout = threading.Timer(RUN_TIMEOUT_S, process.kill)
                            timeout.start()
                            for line in process.stdout:
                                print("  " + line.strip(), flush=True)
                            process.wait()
                        finally:
                            timeout.cancel()
                            if process.poll() is None:
                                process.kill()
                                process.wait()
                    if process.returncode != 0 or not Path(job["result"]).exists():
                        raise RuntimeError(f"Worker failed: {name}; inspect {folder}")
                    record = json.loads(Path(job["result"]).read_text(encoding="utf-8"))
                    if record["error"]:
                        raise RuntimeError(f"{name}: {record['error']}")
                    if record["harness_sha256"] != metadata["harness_sha256"]:
                        raise RuntimeError("Benchmark source changed during measurement; campaign incomplete")
                    record["job"]["launcher_pid"] = process.pid
                    record["job"]["pid"] = record["worker_pid"]
                    write_json(Path(job["result"]), record)
                    records.append(record)
                    print(f"  DONE: {record['playback']['timeline_fps']:.2f} fps; CPU {record['resources']['playback']['cpu_machine_pct']:.2f}%", flush=True)
                    summarize(folder, records, metadata)
    finally:
        if gpu_process is not None:
            gpu_process.terminate()
            gpu_process.wait(timeout=10)
        gpu_out.close()
        gpu_error.close()
    summarize(folder, records, metadata, show=True)
    print(f"RESULTS_DIR={folder}", flush=True)


if __name__ == "__main__":
    worker_job = os.environ.get("TINYTOUCH_BENCH_WORKER")
    if worker_job:
        scenario = Scenario(json.loads(Path(worker_job).read_text(encoding="utf-8")))
        scenario.root.after(TICK_MS, scenario.tick)
        scenario.root.mainloop()
        raise SystemExit(1 if scenario.result.get("error") else 0)
    coordinator()
