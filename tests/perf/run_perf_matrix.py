"""
tests/perf/run_perf_matrix.py

Runs the robot-user perf scenario (tests/e2e/test_perf_scenario.py) over the
whole SMOOTHNESS_PLAN.md matrix — every video x panel variant, REPEATS times,
each run in a fresh process — then prints the median of the runs per variant,
next to the COMPARE_WITH label when results for it exist.

Label a run through the environment (not a CLI, by project rule):
  $env:TINYTOUCH_PERF_LABEL = "step1"
  uv run python tests/perf/run_perf_matrix.py

With TINYTOUCH_PERF_SUMMARY_ONLY=1 it skips running and only re-prints the
summary of the JSONs already in tests/perf/results/.
"""

import glob
import json
import os
import statistics
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
RESULTS_DIR = os.path.join(_HERE, "results")

# --- Tunables -----------------------------------------------------------------
VIDEOS = [os.path.join("videos", "sample_1080p.mp4"),
          os.path.join("videos", "sample_2160p.mp4")]
PANELS = ["default", "fullscreen"]
REPEATS = 3
COMPARE_WITH = "baseline"
# (json key, lower is better?) — the headline metrics of the plan.
METRICS = [
    ("load_s", True),
    ("step_ms_median", True),
    ("step_ms_p95", True),
    ("jump_ms_median", True),
    ("jump_ms_p95", True),
    ("jump_ms_max", True),
    ("playback_fps", False),
    ("playback_stall_pct", True),
    ("playback_jitter_ms", True),
    ("playback_interval_ms_p95", True),
    ("resize_to_sharp_ms", True),
    ("resize_decodes", True),
    ("lag.load.lag_max_ms", True),
    ("lag.steps.lag_p95_ms", True),
    ("lag.jumps.lag_p95_ms", True),
    ("lag.playback.lag_p95_ms", True),
    ("lag.playback.lag_max_ms", True),
    ("perf.display_frame_photo.avg_ms", True),
    ("perf.ui_marshal.total_ms", True),
    ("perf.ui_marshal_play.total_ms", True),
    ("perf.ui_status.total_ms", True),
    ("perf.duplicate_decode.n", True),
]


def run_one(label, video, panel):
    env = dict(os.environ,
               TINYTOUCH_PERF="1",
               TINYTOUCH_PERF_LABEL=label,
               TINYTOUCH_PERF_VIDEO=video,
               TINYTOUCH_PERF_PANEL=panel)
    cmd = [sys.executable, "-m", "pytest", "tests/e2e/test_perf_scenario.py",
           "-m", "gui", "-q", "-p", "no:cacheprovider"]
    proc = subprocess.run(cmd, cwd=_ROOT, env=env, capture_output=True, text=True)
    tail = proc.stdout.strip().splitlines()[-1:] or [""]
    print(f"    rc={proc.returncode} {tail[0]}")
    if proc.returncode != 0:
        print(proc.stdout[-3000:])
        print(proc.stderr[-2000:])


def lookup(result, dotted):
    head, _, rest = dotted.partition(".")
    if head == "perf":
        name, _, field = rest.rpartition(".")
        return result.get("perf_counters", {}).get(name, {}).get(field)
    node = result
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def load_results(label):
    grouped = {}
    for path in glob.glob(os.path.join(RESULTS_DIR, f"perf_{label}_*.json")):
        with open(path, encoding="utf-8") as fh:
            result = json.load(fh)
        if result.get("label") != label or "panel" not in result:
            continue
        grouped.setdefault((result["video"], result["panel"]), []).append(result)
    return grouped


def median_of(results, key):
    values = [v for v in (lookup(r, key) for r in results) if v is not None]
    return statistics.median(values) if values else None


def spread_of(results, key):
    values = [v for v in (lookup(r, key) for r in results) if v is not None]
    return (max(values) - min(values)) if len(values) > 1 else None


def fmt(value):
    return "-" if value is None else f"{value:g}"


def summarize(label):
    current = load_results(label)
    reference = load_results(COMPARE_WITH) if label != COMPARE_WITH else {}
    for variant in sorted(current):
        runs = current[variant]
        ref_runs = reference.get(variant, [])
        print(f"\n## {variant[0]} / {variant[1]}  "
              f"({label}: {len(runs)} runs"
              + (f", {COMPARE_WITH}: {len(ref_runs)} runs)" if ref_runs else ")"))
        header = f"  {'metric':34} {label:>10} {'spread':>8}"
        if ref_runs:
            header += f" {COMPARE_WITH:>10} {'change':>8}"
        print(header)
        for key, lower_is_better in METRICS:
            now = median_of(runs, key)
            line = f"  {key:34} {fmt(now):>10} {fmt(spread_of(runs, key)):>8}"
            if ref_runs:
                before = median_of(ref_runs, key)
                change = ""
                if now is not None and before not in (None, 0):
                    pct = (now - before) / before * 100
                    better = pct < 0 if lower_is_better else pct > 0
                    change = f"{pct:+.0f}%" + (" ok" if better else "")
                line += f" {fmt(before):>10} {change:>8}"
            print(line)


def main():
    label = os.environ.get("TINYTOUCH_PERF_LABEL", "run")
    if not os.environ.get("TINYTOUCH_PERF_SUMMARY_ONLY"):
        for video in VIDEOS:
            if not os.path.exists(os.path.join(_ROOT, video)):
                sys.exit(f"{video} missing — run tests/perf/make_sample_videos.py")
        for video in VIDEOS:
            for panel in PANELS:
                for i in range(REPEATS):
                    print(f"  {label}: {os.path.basename(video)} / {panel} run {i + 1}/{REPEATS}")
                    run_one(label, video, panel)
    summarize(label)


if __name__ == "__main__":
    main()
