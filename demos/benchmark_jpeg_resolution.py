"""Compare original JPEG extraction with a 1920x1080 cap, without a GUI.

Run with uv run demos/benchmark_jpeg_resolution.py. All outputs are isolated
under demos/runtime; production extraction and existing projects are untouched.
"""

from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

import cv2
import imageio_ffmpeg
import psutil
from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "demos"))
from adapters.frame_buffer import compute_target_size
from frame_identity import numbered_frame, read_marker

OUTPUT_ROOT = ROOT / "demos" / "runtime" / "jpeg_resolution"
MAX_SIZE = (1920, 1080)
SAMPLES = ("sample_1080p", "sample_2160p")
FRAME_COUNT = 100
REPEATS = 2
DISPLAYS = ((1280, 720), (1920, 1080))
IDENTITY_IDS = (0, 1, 49, 50, 51, 99, 100, 101, 159, 255)


def capped_size(width, height):
    """Fit within 1920x1080 without upscaling, cropping, or stretching.

    Integer dimensions can introduce less than one pixel of rounding.
    """
    if width <= 0 or height <= 0:
        raise ValueError("Source dimensions must be positive")
    ratio = min(Fraction(1), Fraction(MAX_SIZE[0], width), Fraction(MAX_SIZE[1], height))
    return max(1, int(width * ratio)), max(1, int(height * ratio))


def source_size(video):
    capture = cv2.VideoCapture(str(video))
    try:
        if not capture.isOpened():
            raise RuntimeError(f"Cannot open {video}")
        return (int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    finally:
        capture.release()


def extract(video, folder, frame_count, cap):
    """Same JPEG quality/numbering as production, optionally resize before encoding."""
    size = source_size(video)
    output_size = capped_size(*size) if cap else size
    folder.mkdir()
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-nostats", "-loglevel", "error",
               "-i", str(video), "-frames:v", str(frame_count)]
    if output_size != size:
        command += ["-vf", f"scale={output_size[0]}:{output_size[1]}:flags=bilinear"]
    command += ["-q:v", "2", "-start_number", "0", str(folder / "frame%d.jpg")]
    started = time.perf_counter()
    subprocess.run(command, check=True, capture_output=True, timeout=180)
    elapsed = time.perf_counter() - started
    files = list(folder.glob("frame*.jpg"))
    expected_names = {f"frame{i}.jpg" for i in range(frame_count)}
    if {path.name for path in files} != expected_names:
        raise AssertionError("Extraction frame count/numbering changed")
    with Image.open(folder / "frame0.jpg") as image:
        if image.size != output_size:
            raise AssertionError((image.size, output_size))
    return {"wall_s": elapsed, "bytes": sum(path.stat().st_size for path in files),
            "size": output_size, "frame_count": len(files), "command": command}


def decode_one(path, display):
    """Mirror FrameBuffer's draft/copy/resize; time decode and resize separately."""
    started = time.perf_counter_ns()
    cpu_started = time.process_time_ns()
    with Image.open(path) as opened:
        target = compute_target_size(*opened.size, *display, 1.0)
        opened.draft("RGB", target)
        image = opened.copy()
    decoded = time.perf_counter_ns()
    cpu_decoded = time.process_time_ns()
    draft_size = image.size
    if image.size != target:
        image = image.resize(target, Image.Resampling.BILINEAR)
    finished = time.perf_counter_ns()
    cpu_finished = time.process_time_ns()
    return image, {"decode_wall_ms": (decoded - started) / 1e6,
                   "resize_wall_ms": (finished - decoded) / 1e6,
                   "total_wall_ms": (finished - started) / 1e6,
                   "decode_cpu_ms": (cpu_decoded - cpu_started) / 1e6,
                   "resize_cpu_ms": (cpu_finished - cpu_decoded) / 1e6,
                   "total_cpu_ms": (cpu_finished - cpu_started) / 1e6,
                   "draft_size": draft_size, "output_size": image.size}


def measure_decode(folder, display):
    # Warm filesystem/decoder before measured sequential, single-thread loading.
    for index in range(5):
        image, _ = decode_one(folder / f"frame{index}.jpg", display)
        image.close()
    observations = []
    for index in range(FRAME_COUNT):
        image, measurement = decode_one(folder / f"frame{index}.jpg", display)
        image.close()
        observations.append(measurement)
    result = {key: statistics.mean(row[key] for row in observations)
              for key in observations[0] if key.endswith("_ms")}
    result.update({"display": display, "draft_size": observations[0]["draft_size"],
                   "output_size": observations[0]["output_size"],
                   "decoded_rgb_bytes": observations[0]["output_size"][0] *
                   observations[0]["output_size"][1] * 3})
    return result


def verify_identity(folder):
    """Encode marked frames to 4K, then verify every original/capped extracted ID."""
    video = folder / "numbered_4k.mp4"
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-f", "rawvideo",
               "-pixel_format", "rgb24", "-video_size", "640x360", "-framerate", "25",
               "-i", "-", "-vf", "scale=3840:2160:flags=neighbor", "-c:v", "libx264",
               "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p",
               "-bf", "3", str(video)]
    with (folder / "identity_encode.log").open("w") as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        try:
            for index in IDENTITY_IDS:
                process.stdin.write(numbered_frame(index).tobytes())
            process.stdin.close()
            if process.wait(timeout=90) != 0:
                raise RuntimeError("Identity encoding failed; see identity_encode.log")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    checks = []
    for cap in (False, True):
        frames = folder / ("identity_capped" if cap else "identity_original")
        extract(video, frames, len(IDENTITY_IDS), cap)
        for position, expected in enumerate(IDENTITY_IDS):
            with Image.open(frames / f"frame{position}.jpg") as image:
                actual = read_marker(image)
                if actual != expected:
                    raise AssertionError((cap, position, expected, actual))
            checks.append({"cap": cap, "position": position, "expected": expected, "actual": actual})
    if read_marker(numbered_frame(51)) == 50:
        raise AssertionError("Negative control failed")
    return checks


def quality_comparison(original, capped, folder):
    """Pixel difference at the same 1080p display size; not annotation acceptance."""
    left, _ = decode_one(original / "frame50.jpg", MAX_SIZE)
    right, _ = decode_one(capped / "frame50.jpg", MAX_SIZE)
    rms = ImageStat.Stat(ImageChops.difference(left, right)).rms
    left.save(folder / "original_display_frame50.png")
    right.save(folder / "capped_display_frame50.png")
    comparison = Image.new("RGB", (1920, 540))
    comparison.paste(left.resize((960, 540)), (0, 0))
    comparison.paste(right.resize((960, 540)), (960, 0))
    comparison.save(folder / "comparison_frame50.png")
    return {"rgb_rmse_255": (sum(value ** 2 for value in rms) / 3) ** .5,
            "comparison": str(folder / "comparison_frame50.png")}


def main():
    folder = OUTPUT_ROOT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder.mkdir(parents=True)
    baseline_load = psutil.cpu_percent(interval=.2)
    psutil.cpu_percent()
    result = {"system": {"platform": platform.platform(), "logical_cpus": os.cpu_count(),
                         "pillow": Image.__version__, "idle_sample_cpu_pct": baseline_load},
              "frame_count": FRAME_COUNT, "repeats": REPEATS, "max_size": MAX_SIZE,
              "identity": verify_identity(folder), "runs": [], "quality": {}}
    for repeat in range(REPEATS):
        for sample in SAMPLES:
            variants = (False, True) if repeat == 0 else (True, False)
            paths = {}
            for cap in variants:
                mode = "capped" if cap else "original"
                frames = folder / f"{sample}_{mode}_{repeat}"
                paths[mode] = frames
                extraction = extract(ROOT / "videos" / f"{sample}.mp4", frames, FRAME_COUNT, cap)
                decoding = [measure_decode(frames, display) for display in DISPLAYS]
                row = {"sample": sample, "repeat": repeat, "mode": mode,
                       "extraction": extraction, "decoding": decoding}
                result["runs"].append(row)
                print(json.dumps(row), flush=True)
            if repeat == 0:
                result["quality"][sample] = quality_comparison(paths["original"], paths["capped"], folder)
                if sample == "sample_1080p":
                    same = all(hashlib.sha256((paths["original"] / f"frame{i}.jpg").read_bytes()).digest() ==
                               hashlib.sha256((paths["capped"] / f"frame{i}.jpg").read_bytes()).digest()
                               for i in range(FRAME_COUNT))
                    if not same:
                        raise AssertionError("1080p no-op cap altered JPEG bytes")
                    result["unchanged_1080p_sha256_checks"] = FRAME_COUNT
                # Preserve per-sample comparisons before the next sample overwrites these names.
                for name in ("comparison_frame50.png", "original_display_frame50.png", "capped_display_frame50.png"):
                    (folder / name).rename(folder / f"{sample}_{name}")
                result["quality"][sample]["comparison"] = str(folder / f"{sample}_comparison_frame50.png")
    result["system"]["run_mean_cpu_pct"] = psutil.cpu_percent()
    (folder / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Results: {folder}")


if __name__ == "__main__":
    main()
