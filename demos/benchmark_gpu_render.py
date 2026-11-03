"""Focused GPU-vs-Tk JPEG display experiment. No annotation app is opened.

Run: uv run demos/benchmark_gpu_render.py. Constants below configure the run.
Workers are isolated by an internal environment variable, not a command-line API.
"""

from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

from PIL import Image
import psutil

from frame_identity import numbered_frame, read_marker
from gpu_render_demo import ROOT, create_renderer, decode, enable_dpi_awareness


OUTPUT_ROOT = ROOT / "demos" / "runtime" / "gpu_render"
MODES = ("tk", "gpu")
SAMPLES = ("sample_1080p", "sample_2160p")
REPEATS = 2
FPS = 25
MEASURED_FRAMES = 100
SOURCE_FRAME_COUNT = 25
IDENTITY_SEQUENCE = (0, 1, 49, 50, 51, 159, 75, 0)
WORKER_ENV = "TINYTOUCH_GPU_RENDER_JOB"


def distribution(values):
    ordered = sorted(values)
    return {"median": statistics.median(ordered),
            "p95": ordered[min(len(ordered) - 1, int(len(ordered) * .95))]}


def identity_checks(renderer, folder):
    observations = []
    for index in IDENTITY_SEQUENCE:
        # Exercise JPEG degradation, then read the rendered output's pixels.
        encoded = io.BytesIO()
        numbered_frame(index).save(encoded, format="JPEG", quality=80)
        encoded.seek(0)
        with Image.open(encoded) as source:
            image = source.convert("RGB")
        # Read Tk's PhotoImage or SDL's render target, not the source PIL image.
        # Neither readback path is timed; these are not physical screen checks.
        renderer.render(image, index)
        time.sleep(.06)
        output = renderer.render(image, index, capture=True)
        actual = read_marker(output)
        if actual != index:
            raise AssertionError(f"Requested {index}, rendered {actual}")
        observations.append({"requested": index, "pixel_id": actual})
        if index == 50:
            output.save(folder / "frame50.png")
    return observations


def worker(job):
    enable_dpi_awareness()
    folder = Path(job["output"])
    folder.mkdir()
    if job["mode"] == "fallback":
        # An SDL dummy video device has no accelerated renderer. Tk still uses
        # the normal desktop. This tests fallback, not physically GPU-free HW.
        os.environ["SDL_VIDEODRIVER"] = "dummy"
    renderer = create_renderer("auto" if job["mode"] == "fallback" else job["mode"])
    result = {"mode": job["mode"], "renderer": renderer.name, "pid": os.getpid()}
    try:
        if job.get("identity"):
            result["identity"] = identity_checks(renderer, folder)
        if job["mode"] == "fallback":
            assert renderer.name == "CPU / Pillow + Tk", renderer.name
        else:
            frames = Path(job["frames"])
            paths = [frames / f"frame{i}.jpg" for i in range(SOURCE_FRAME_COUNT)]
            with Image.open(paths[0]) as header:
                source_size = list(header.size)
            for i in range(5):
                renderer.render(decode(paths[i]), i)
            process = psutil.Process()
            psutil.cpu_percent()
            cpu0 = sum(process.cpu_times()[:2])
            start = time.perf_counter()
            decode_ms, display_ms, rss, durations = [], [], [], []
            for index in range(MEASURED_FRAMES):
                tick = time.perf_counter()
                image = decode(paths[index % len(paths)])
                decoded = time.perf_counter()
                renderer.render(image, index)
                rendered = time.perf_counter()
                decode_ms.append((decoded - tick) * 1000)
                display_ms.append((rendered - decoded) * 1000)
                durations.append((rendered - tick) * 1000)
                rss.append(process.memory_info().rss / 2**20)
                renderer.events()
                time.sleep(max(0, 1 / FPS - (time.perf_counter() - tick)))
            wall = time.perf_counter() - start
            result.update({
                "sample": job["sample"], "repeat": job["repeat"],
                "frames": MEASURED_FRAMES, "source_size": source_size,
                "decoded_size": list(image.size),
                "display_size": [1280, 720], "wall_s": wall,
                "fps": MEASURED_FRAMES / wall,
                "cpu_machine_pct": (sum(process.cpu_times()[:2]) - cpu0) / wall
                                   / (os.cpu_count() or 1) * 100,
                "rss_mean_mib": statistics.mean(rss),
                "system_cpu_pct": psutil.cpu_percent(),
                "decode_ms": distribution(decode_ms),
                "display_ms": distribution(display_ms),
                "total_ms": distribution(durations),
                "frames_over_40ms": sum(value > 40 for value in durations),
                "jpeg_source": str(frames),
            })
    finally:
        renderer.close()
    (folder / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


def cached_frames(sample, output):
    candidates = sorted((ROOT / "demos" / "runtime" / "benchmarks").glob(
        f"*/{sample}_frames"))
    for folder in candidates:
        if all((folder / f"frame{i}.jpg").exists() for i in range(SOURCE_FRAME_COUNT)):
            return folder
    # Reproduction on a fresh checkout: extract only the measured source frames.
    import imageio_ffmpeg

    source = ROOT / "videos" / f"{sample}.mp4"
    if not source.exists():
        raise FileNotFoundError(f"Place the benchmark video at {source}")
    folder = output / f"{sample}_frames"
    folder.mkdir()
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(source),
                    "-frames:v", str(SOURCE_FRAME_COUNT), "-q:v", "2", "-start_number", "0",
                    str(folder / "frame%d.jpg")], check=True, timeout=90)
    return folder


def main():
    if WORKER_ENV in os.environ:
        worker(json.loads(os.environ[WORKER_ENV]))
        return
    output = OUTPUT_ROOT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output.mkdir(parents=True)
    sources = {sample: cached_frames(sample, output) for sample in SAMPLES}
    jobs = [{"mode": "fallback", "identity": True, "output": str(output / "fallback")}]
    for repeat in range(REPEATS):
        for sample in SAMPLES:
            for mode in MODES if repeat % 2 == 0 else reversed(MODES):
                jobs.append({"sample": sample, "repeat": repeat, "mode": mode,
                             "frames": str(sources[sample]),
                             "identity": repeat == 0 and sample == SAMPLES[0],
                             "output": str(output / f"{sample}-{mode}-{repeat}")})
    results = []
    for job in jobs:
        environment = os.environ.copy()
        environment[WORKER_ENV] = json.dumps(job)
        process = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                                 env=environment, capture_output=True, text=True, timeout=90)
        (output / f"{Path(job['output']).name}.log").write_text(
            process.stdout + process.stderr, encoding="utf-8")
        if process.returncode:
            raise RuntimeError(f"Worker failed; inspect {output}: {process.stderr[-1800:]}")
        result = json.loads((Path(job["output"]) / "result.json").read_text(encoding="utf-8"))
        results.append(result)
        print(f"{Path(job['output']).name}: {result['renderer']} "
              f"{result.get('cpu_machine_pct', 0):.2f}% CPU, "
              f"{result.get('fps', 0):.2f} FPS", flush=True)
    summary = {"created_utc": datetime.now(timezone.utc).isoformat(),
               "logical_cpus": os.cpu_count(), "results": results,
               "source_hashes": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in (Path(__file__), Path(__file__).with_name("gpu_render_demo.py"))}}
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Evidence: {output}", flush=True)


if __name__ == "__main__":
    main()
