# Per-frame GUI refresh experiment

This is a standalone experiment; no production code or annotation data changes.

## Result

**The candidate avoids many redundant writes, but the measured savings are
small: about 0.34 ms per refresh for mostly unchanged annotation controls and
0.057 ms when annotations change every frame.** This is a useful cleanup, not
evidence of a major playback speedup.

Measured on Windows 11, Python 3.12.3 and Tcl/Tk 8.6.13 on 2026-11-03. Values
are medians across five trials; each trial's mean covers all 600 refreshes.

| Workload | Current mean per refresh | Candidate mean | Saved | Widget write commands / 600 frames |
| --- | ---: | ---: | ---: | ---: |
| Mostly unchanged | 0.439 ms | 0.0968 ms | 0.342 ms (78%) | 6,600 → 1,243 (81% fewer) |
| Busy, changing each frame | 0.377 ms | 0.320 ms | 0.0571 ms (15%) | 6,600 → 4,190 (37% fewer) |

The median per-refresh p95 was 0.808 → 0.179 ms for mostly unchanged controls,
but 0.598 → 0.646 ms for busy controls. The experiment does not establish a
worst-case latency improvement for rapidly changing annotations.

At 25 displayed frames/second, the mostly-unchanged saving corresponds to about
8.5 ms of this GUI-thread work per second. That is a time-budget calculation,
not a measured whole-process CPU percentage. JPEG decoding and video rendering
remain separate, much larger candidates for optimization.

All **1,208 live-widget equivalence/counter checks** passed. Three permanent
non-GUI setter tests also passed (`uv run pytest tests/unit/test_gui_refresh_policy.py -q`).
The complete non-GUI suite passed (**497 tests**), and the dedicated GUI
regression passed (**1 test**) with
`uv run pytest tests/e2e/test_gui_refresh_experiment.py -m gui -q`. That test
repeats the widget comparisons in an isolated process using a withdrawn root;
it does not launch the annotation application.

Raw evidence: [results.json](runtime/gui_refresh/20261103T123807253077Z/results.json).
The runtime directory is local and ignored by Git; the table and reproducible
benchmark remain available in the repository. No other benchmarks ran during
this measurement window. Background desktop/OS load was not controlled.

## Question and existing optimizations

Can avoiding repeated widget writes make the existing JPEG player cheaper?
`LabelingApp.display_first_frame` refreshes the note, counter/time, selected-limb
parameters and three global parameter buttons on every invocation. The current
implementation clears/inserts the note, configures six button styles and writes
the select-frame button's enabled state even when those values are unchanged.

Other relevant work is already optimized: the video image reuses its PhotoImage,
the buffer status updates only on a transition, and timelines cache their static
drawing while moving a playhead. This experiment does not redo those mechanisms.

## Method

Run `uv run demos/benchmark_gui_refresh.py`. It calls the actual four production
refresh methods against minimal real Tk widgets. It constructs a withdrawn root,
not LabelingApp, and never opens a project or reads/writes annotation files.

The candidate compares live button options before configuring them and compares
the actual note contents before replacing text. It always writes the frame and
time counters immediately. There is no throttle, cached annotation state or timer.
Live comparisons see changes from other callbacks, avoiding cache invalidation
requirements. The wrapper exists only to compare policies in this demo; a future
integration should put the small checks in the existing setters.

Five alternating baseline/candidate trials run 600 frames each after 60 warmup
frames. The mostly-unchanged scenario changes notes/global state every 100 frames
and selected limb every 30 frames. The busy scenario changes notes/global state
every frame. Setup/fixture mutation is outside the measured interval; each timed
refresh includes `update_idletasks()` to drain queued idle work. Each policy uses
the same adapter/counting overhead. Counts describe widget write commands, not
CPU instructions or all Tcl calls: candidate reads are additional Tcl calls.

Tk widgets normally draw through their event loop; draining idle tasks alone is
not a visible-display latency measurement. See the official [Tkinter
documentation](https://docs.python.org/3/library/tkinter.html).

## Correctness boundaries

The benchmark compares complete note/counter/time/state/style snapshots between
policies for both workloads. It also checks same-frame note/parameter edits,
selected-limb changes, `None` / `"None"` / empty unset states, external style changes
and every exact frame counter. The candidate intentionally matches the current
app's replacement of an unsaved draft on refresh; it does not introduce a new
note-saving policy. No note persistence or data schema is involved.

## Limits

The root is withdrawn, so results measure Python/Tcl widget refresh and queued
idle work, not visible repaint, video PhotoImage transfer, JPEG decoding,
timeline/diagram drawing, full-app CPU, playback FPS, battery or power draw.
Small savings here must not be presented as a similar percentage improvement in
the whole player. Source hashes, all trials and environment are saved beside the
results under ignored `demos/runtime/gui_refresh/`.
