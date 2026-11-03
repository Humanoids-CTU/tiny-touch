"""Time real controller refresh methods against an experimental setter policy.

Run with uv run demos/benchmark_gui_refresh.py. Only a withdrawn minimal Tk root
is constructed; no project, full app, input video, or annotation file is opened.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import time
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from labeling_app import LabelingApp
from gui import theme
from gui_refresh_policy import ConfiguredWidget, replace_note_if_changed

FRAMES = 600
REPEATS = 5
WARMUP_FRAMES = 60
OUTPUT_ROOT = ROOT / "demos" / "runtime" / "gui_refresh"


class CountedText(tk.Text):
    writes = 0

    def delete(self, *args):
        self.writes += 1
        return super().delete(*args)

    def insert(self, *args):
        self.writes += 1
        return super().insert(*args)


class Panel:
    # Execute the production implementations, including their formatting/style
    # logic, without constructing LabelingApp or registering app callbacks.
    update_note_entry = LabelingApp.update_note_entry
    update_frame_counter = LabelingApp.update_frame_counter
    update_limb_parameter_buttons = LabelingApp.update_limb_parameter_buttons
    update_button_colors = LabelingApp.update_button_colors
    _get_note_entry_text = LabelingApp._get_note_entry_text
    _clear_note_entry = LabelingApp._clear_note_entry
    _param_key_for_index = LabelingApp._param_key_for_index
    _limb_param_key_for_index = LabelingApp._limb_param_key_for_index

    def __init__(self, root, candidate):
        self.candidate = candidate
        self.video = SimpleNamespace(current_frame=0, total_frames=FRAMES - 1,
                                     frame_rate=25, frames={}, number_frames_in_zone=100)
        self.option_var_1 = tk.StringVar(root, "LH")
        self.frame = ttk.Frame(root)
        self.note_entry = CountedText(self.frame, height=2, width=36)
        self.note_entry.pack()
        self.controls = []
        for name in ("select_frame_button", "frame_counter_label", "time_counter_label",
                     "par1_btn", "par2_btn", "par3_btn", "limb_par1_btn",
                     "limb_par2_btn", "limb_par3_btn"):
            cls = ttk.Label if name.endswith("label") else ttk.Button
            widget = cls(self.frame)
            widget.pack()
            # Counters change on navigation; do not add a redundant read there.
            adapter = ConfiguredWidget(widget, candidate and not name.endswith("label"))
            self.controls.append(adapter)
            setattr(self, name, adapter)
        self.frame.pack()

    def _set_note_entry_text(self, text):
        if self.candidate:
            replace_note_if_changed(self.note_entry, text)
        else:
            LabelingApp._set_note_entry_text(self, text)

    def refresh(self):
        self.update_note_entry()
        self.update_frame_counter()
        self.update_limb_parameter_buttons()
        self.update_button_colors()

    def snapshot(self):
        return [self.note_entry.get("1.0", "end-1c"),
                *[str(c.widget.cget("text" if i in (1, 2) else
                                     "state" if i == 0 else "style"))
                  for i, c in enumerate(self.controls)]]

    @property
    def writes(self):
        return self.note_entry.writes + sum(c.writes for c in self.controls)


def select_frame(panel, index, scenario):
    panel.video.current_frame = index
    if scenario == "mostly_unchanged":
        block = index // 100
    else:
        block = index
    # Realistic sparse transitions versus deliberately busy worst case.
    states = (None, "ON", "OFF")
    state = states[block % 3]
    opposite = states[(block + 1) % 3]
    panel.video.frames[index] = {
        "Note": "" if block % 2 == 0 else f"note {block}",
        "Params": {"Par1": state, "Par2": opposite},
        "LH": {"LimbParams": {"Par1": state}},
        "RH": {"LimbParams": {"Par1": opposite}},
    }
    panel.option_var_1.set("LH" if index % 60 < 30 else "RH")


def validate(root):
    baseline, candidate = Panel(root, False), Panel(root, True)
    checks = 0
    try:
        for scenario in ("mostly_unchanged", "busy"):
            for index in range(FRAMES):
                for panel in (baseline, candidate):
                    select_frame(panel, index, scenario)
                    panel.refresh()
                assert baseline.snapshot() == candidate.snapshot(), (scenario, index)
                assert candidate.frame_counter_label.widget.cget("text") == f"{index} / {FRAMES - 1}"
                checks += 1
        # Edits at a stationary frame and channel switches must refresh instantly.
        for panel in (baseline, candidate):
            panel.video.frames[FRAMES - 1]["Params"]["Par3"] = "ON"
            panel.video.frames[FRAMES - 1]["RH"]["LimbParams"]["Par2"] = "OFF"
            panel.video.frames[FRAMES - 1]["Note"] = "changed at same frame"
            panel.option_var_1.set("RH")
            panel.refresh()
        assert baseline.snapshot() == candidate.snapshot()
        assert candidate.snapshot()[0] == "changed at same frame"
        checks += 1
        # Existing helper normalizes all unset spellings to the neutral style.
        for state in (None, "None", "", "ON", "OFF"):
            for panel in (baseline, candidate):
                panel.video.frames[FRAMES - 1]["Params"]["Par1"] = state
                panel.refresh()
            assert baseline.snapshot() == candidate.snapshot()
            expected = {"ON": "StateOn.TButton", "OFF": "StateOff.TButton"}.get(state, "StateNeutral.TButton")
            assert str(candidate.par1_btn.widget.cget("style")) == expected
            checks += 1
        # Another callback changing a widget cannot leave the diff policy stale.
        candidate.par1_btn.widget.configure(style="StateOn.TButton")
        for panel in (baseline, candidate):
            panel.refresh()
        assert baseline.snapshot() == candidate.snapshot()
        checks += 1
        for panel in (baseline, candidate):
            # Match the current app's replacement of an unsaved draft on refresh.
            panel.note_entry.insert("end", " unsaved draft")
            panel.refresh()
        assert baseline.snapshot() == candidate.snapshot()
        assert candidate.snapshot()[0] == "changed at same frame"
        checks += 1
        return checks
    finally:
        baseline.frame.destroy()
        candidate.frame.destroy()


def run_trial(root, candidate, scenario):
    panel = Panel(root, candidate)
    try:
        for index in range(WARMUP_FRAMES):
            select_frame(panel, index, scenario)
            panel.refresh()
        root.update_idletasks()
        for control in panel.controls:
            control.writes = 0
        panel.note_entry.writes = 0
        samples = []
        for index in range(FRAMES):
            select_frame(panel, index, scenario)
            start = time.perf_counter_ns()
            panel.refresh()
            # Include queued idle work, but a withdrawn root does not measure
            # visible widget redisplay or video image transfer.
            root.update_idletasks()
            samples.append((time.perf_counter_ns() - start) / 1_000_000)
        return {"mean_ms": statistics.mean(samples),
                "median_ms": statistics.median(samples),
                "p95_ms": sorted(samples)[int(len(samples) * .95)],
                "widget_write_commands": panel.writes,
                "frames": FRAMES}
    finally:
        panel.frame.destroy()


def main():
    root = tk.Tk()
    root.withdraw()
    try:
        checks = validate(root)
        trials = []
        for repeat in range(REPEATS):
            for scenario in ("mostly_unchanged", "busy"):
                for candidate in ((False, True) if repeat % 2 == 0 else (True, False)):
                    result = run_trial(root, candidate, scenario)
                    trials.append({"repeat": repeat, "scenario": scenario,
                                   "policy": "changed_only" if candidate else "current", **result})
        summary = {}
        for scenario in ("mostly_unchanged", "busy"):
            summary[scenario] = {}
            for policy in ("current", "changed_only"):
                rows = [r for r in trials if r["scenario"] == scenario and r["policy"] == policy]
                summary[scenario][policy] = {
                    key: statistics.median(r[key] for r in rows)
                    for key in ("mean_ms", "median_ms", "p95_ms", "widget_write_commands")}
        folder = OUTPUT_ROOT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        folder.mkdir(parents=True)
        result = {"platform": platform.platform(), "python": platform.python_version(),
                  "tk": root.tk.call("info", "patchlevel"), "validation_checks": checks,
                  "summary": summary, "trials": trials,
                  "scope": "withdrawn widget refresh and idle work; excludes video paint, visible redraw and decoding",
                  "source_sha256": {
                      str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in (Path(__file__), ROOT / "demos" / "gui_refresh_policy.py",
                                   ROOT / "src" / "labeling_app.py", ROOT / "src" / "gui" / "theme.py")}}
        (folder / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({"output": str(folder), "validation_checks": checks, "summary": summary}, indent=2))
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
