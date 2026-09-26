"""
tests/perf/run_perf_matrix.py

Runs the robot-user perf scenario (tests/e2e/test_perf_scenario.py) over the
whole SMOOTHNESS_PLAN.md matrix — every video x panel variant, REPEATS times,
each run in a fresh process — then prints the median of the runs per variant,
next to a reference label when results for it exist.

Configured through the environment (not a CLI, by project rule):

  $env:TINYTOUCH_PERF_LABEL = "step1"
  $env:TINYTOUCH_PERF_AB_REV = "53daf86"   # recommended, see below
  uv run python tests/perf/run_perf_matrix.py

A/B mode (TINYTOUCH_PERF_AB_REV set): the given commit is checked out into a
temporary git worktree and its runs are INTERLEAVED with the working-tree
runs (A B, B A, A B per variant). A laptop's speed drifts over minutes
(power state, heat, background work) by more than the effects we measure —
the first step-1 matrix, run 40 min after the baseline, showed untouched
code paths 20-70 % slower. Interleaving exposes both sides to the same
drift, so the comparison stays fair. The reference label is then
"ab-<rev>-vs-<label>".

Without A/B mode the reference is COMPARE_WITH ("baseline"), recorded at a
different time — only trust large differences there.

Every run first checks the power source and the matrix stops on battery
(Windows throttles the CPU then); TINYTOUCH_PERF_ALLOW_BATTERY=1 overrides.

With TINYTOUCH_PERF_SUMMARY_ONLY=1 it skips running and only re-prints the
summary of the JSONs already in tests/perf/results/.
"""

import glob
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile

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


# === running ==================================================================
def on_battery():
    """True when the machine runs on battery (the OS throttles the CPU then).

    None when unknown (desktop, no battery info) — that never blocks a run.
    """
    if sys.platform == "win32":
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Battery).BatteryStatus"],
            capture_output=True, text=True,
        )
        status = proc.stdout.strip()
        # Win32_Battery.BatteryStatus: 1 = discharging, 2 = on AC.
        return None if not status.isdigit() else status == "1"
    for path in glob.glob("/sys/class/power_supply/*/online"):
        with open(path, encoding="ascii") as fh:
            return fh.read().strip() == "0"
    return None


def require_mains_power():
    """Stop the matrix on battery: those runs are not comparable."""
    if on_battery() and not os.environ.get("TINYTOUCH_PERF_ALLOW_BATTERY"):
        sys.exit("On battery power — plug in the charger (or set "
                 "TINYTOUCH_PERF_ALLOW_BATTERY=1 to measure anyway).")


def ensure_worktree(rev):
    """A detached checkout of `rev` outside the repo, reused across runs."""
    path = os.path.join(tempfile.gettempdir(), f"tinytouch-perf-{rev}")
    if not os.path.isdir(path):
        subprocess.run(["git", "worktree", "add", "--detach", path, rev],
                       cwd=_ROOT, check=True, capture_output=True, text=True)
    return path


def remove_worktree(path):
    subprocess.run(["git", "worktree", "remove", "--force", path],
                   cwd=_ROOT, capture_output=True, text=True)


def run_one(label, video, panel, repo=_ROOT):
    """One scenario run of the code in `repo`; its JSON ends up in RESULTS_DIR."""
    env = dict(os.environ,
               TINYTOUCH_PERF="1",
               TINYTOUCH_PERF_LABEL=label,
               TINYTOUCH_PERF_VIDEO=os.path.join(_ROOT, video),
               TINYTOUCH_PERF_PANEL=panel)
    # The current interpreter (this repo's venv) runs the other checkout too:
    # its tests/conftest.py puts ITS src/ first on sys.path.
    cmd = [sys.executable, "-m", "pytest", "tests/e2e/test_perf_scenario.py",
           "-m", "gui", "-q", "-p", "no:cacheprovider"]
    proc = subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True)
    tail = proc.stdout.strip().splitlines()[-1:] or [""]
    print(f"    rc={proc.returncode} {tail[0]}", flush=True)
    if proc.returncode != 0:
        print(proc.stdout[-3000:])
        print(proc.stderr[-2000:])
    if repo != _ROOT:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        pattern = os.path.join(repo, "tests", "perf", "results", f"perf_{label}_*.json")
        for path in glob.glob(pattern):
            shutil.move(path, os.path.join(RESULTS_DIR, os.path.basename(path)))


def run_matrix(label, ab_rev):
    worktree = ensure_worktree(ab_rev) if ab_rev else None
    reference = f"ab-{ab_rev}-vs-{label}" if ab_rev else None
    try:
        for video in VIDEOS:
            for panel in PANELS:
                for i in range(REPEATS):
                    name = f"{os.path.basename(video)} / {panel} run {i + 1}/{REPEATS}"
                    order = [(label, _ROOT)]
                    if worktree:
                        order.append((reference, worktree))
                        if i % 2:
                            order.reverse()  # A B, B A, A B: no order bias
                    for run_label, repo in order:
                        require_mains_power()
                        print(f"  {run_label}: {name}", flush=True)
                        run_one(run_label, video, panel, repo)
    finally:
        if worktree:
            remove_worktree(worktree)


# === summarizing ==============================================================
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


def summarize(label, reference_label):
    current = load_results(label)
    reference = load_results(reference_label) if label != reference_label else {}
    for variant in sorted(current):
        runs = current[variant]
        ref_runs = reference.get(variant, [])
        print(f"\n## {variant[0]} / {variant[1]}  "
              f"({label}: {len(runs)} runs"
              + (f", {reference_label}: {len(ref_runs)} runs)" if ref_runs else ")"))
        header = f"  {'metric':34} {label:>10} {'spread':>8}"
        if ref_runs:
            header += f" {'reference':>10} {'change':>8}"
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
    ab_rev = os.environ.get("TINYTOUCH_PERF_AB_REV")
    if not os.environ.get("TINYTOUCH_PERF_SUMMARY_ONLY"):
        for video in VIDEOS:
            if not os.path.exists(os.path.join(_ROOT, video)):
                sys.exit(f"{video} missing — run tests/perf/make_sample_videos.py")
        run_matrix(label, ab_rev)
    summarize(label, f"ab-{ab_rev}-vs-{label}" if ab_rev else COMPARE_WITH)


if __name__ == "__main__":
    main()
