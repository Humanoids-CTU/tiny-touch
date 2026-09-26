"""
tests/perf/make_sample_videos.py

Regenerates the synthetic perf-sample videos in videos/ (gitignored) from the
checked-in-elsewhere source clip videos/cat3.mp4, using the recipe recorded in
RESULTS.md: loop the clip to SAMPLE_SECONDS, lanczos-scale it, add temporal
grain (so JPEG decode cost is realistic instead of flat-colour cheap) and
encode with libx264 crf 20.

The genuine-4K Big Buck Bunny sample is NOT generated here — it is a download
(see RESULTS.md, "Sample videos").

Run:  uv run python tests/perf/make_sample_videos.py
Existing outputs are kept; delete a file to force regeneration.
"""

import os
import subprocess
import sys
import time

import imageio_ffmpeg

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))

# --- Tunables -----------------------------------------------------------------
SOURCE_VIDEO = os.path.join(_ROOT, "videos", "cat3.mp4")
OUTPUT_DIR = os.path.join(_ROOT, "videos")
SAMPLE_SECONDS = 30
SAMPLES = [  # (output filename, width, height)
    ("sample_480p.mp4", 854, 480),
    ("sample_1080p.mp4", 1920, 1080),
    ("sample_2160p.mp4", 3840, 2160),
]
GRAIN_FILTER = "noise=alls=8:allf=t"
CRF = "20"


def make_sample(ffmpeg, out_name, width, height):
    out_path = os.path.join(OUTPUT_DIR, out_name)
    if os.path.exists(out_path):
        print(f"  {out_name}: exists, skipped")
        return
    cmd = [
        ffmpeg, "-y", "-v", "error",
        "-stream_loop", "-1", "-i", SOURCE_VIDEO,
        "-t", str(SAMPLE_SECONDS),
        "-vf", f"scale={width}:{height}:flags=lanczos,{GRAIN_FILTER}",
        "-an", "-c:v", "libx264", "-crf", CRF, "-pix_fmt", "yuv420p",
        out_path,
    ]
    started = time.perf_counter()
    subprocess.run(cmd, check=True)
    print(f"  {out_name}: {width}x{height}, {time.perf_counter() - started:.0f}s")


def main():
    if not os.path.exists(SOURCE_VIDEO):
        sys.exit(f"source clip missing: {SOURCE_VIDEO}")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    print(f"generating perf samples from {os.path.relpath(SOURCE_VIDEO, _ROOT)}")
    for out_name, width, height in SAMPLES:
        make_sample(ffmpeg, out_name, width, height)


if __name__ == "__main__":
    main()
