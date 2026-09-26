# Smoothness plan — frame display pipeline

Written 2026-09-26 after the review of `adapters/frame_buffer.py` and its GUI wiring.
Results of every step go into [RESULTS.md](RESULTS.md) (new section per step).

## What we learned before planning

Measured on real `data/cat3` frames (720p, ~105 kB/frame), this machine:

| stage | thread | 955×537 panel | 1600×900 | 2400×1350 |
|---|---|---|---|---|
| disk read | worker | 0.3 ms | 0.3 ms | 0.3 ms |
| JPEG decode | worker | 4.3 ms | 4.5 ms | 4.3 ms |
| resize (upscale) | worker | 7.1 ms | 13 ms | 24 ms |
| `PhotoImage` + repaint | **Tk** | **11 ms** | **32 ms** | **47 ms** |

- Decode pool: 1 → 3 → 8 workers = 67 → 155 → 290 frames/s. The GIL is released; threads
  are the right tool (Fluent Python ch. 19 p. 729-730, ch. 20 p. 783). No asyncio, no processes.
- Worker calling `root.after()` **blocks until the Tk thread is free** (measured: 650 ms
  stall while Tk was busy for 800 ms). The buffering and playback threads both do this.
- Reusing one `PhotoImage` via `paste()` instead of a new one per frame: 8.6 → 5.8 ms,
  21 → 14.6 ms, 48 → 35 ms (~30 % off the UI-thread cost).

So "smoother" means mostly: **keep the Tk thread free and never make a worker wait for it.**

## Rules for every step

1. **One step = one change = one commit.** Never mix two steps; otherwise we can't say
   which one helped.
2. **Two kinds of test per step:**
   - a **correctness test** (red/green, behavior-scoped) that lives in the normal suite
     forever. It proves the change does what it claims and guards against regression.
   - a **perf measurement** with the opt-in robot-user scenario
     (`tests/e2e/test_perf_scenario.py`). Timing numbers are NOT asserted in the normal
     suite — they are noisy on a shared desktop and would make the suite flaky. The one
     exception is a bound with a huge margin (step 6: ~1000 ms vs a 250 ms limit).
3. **A step "helped" only if** its target metric beats the baseline by more than the
   run-to-run noise measured in step 0, **and** no other metric got worse by more than
   the noise. Otherwise revert it or explain why it's still worth keeping.
4. Run each scenario **3×** and compare the median of the 3 runs.
5. After each step: `uv run pytest`, `uv run pytest -m gui`, then the perf matrix in
   A/B mode against the previous step's commit (~20 min):
   `$env:TINYTOUCH_PERF_LABEL = "step2"; $env:TINYTOUCH_PERF_AB_REV = "<prev commit>"; uv run python tests/perf/run_perf_matrix.py`
6. Check the control metrics (ones the step cannot affect) before believing a change.

## The metrics ("the ruler")

| id | metric | exists? | what it tells us |
|---|---|---|---|
| M1 | step latency median / p95 | yes (needs fix, see 0a) | `>` press → frame on screen |
| M2 | jump latency median / p95 | yes (needs fix, see 0a) | `>>` press → frame on screen |
| M3 | playback fps achieved / target, stall % | yes | can we keep up with the video |
| M4 | **UI event-loop lag** p95 / max, per phase | **new** | the "jank" the user feels: how late a 5 ms `after()` heartbeat fires |
| M5 | **playback frame-interval jitter** (stdev of time between painted frames) | **new** | smooth vs stuttery playback at the same average fps |
| M6 | **worker time blocked on Tk** (`ui_marshal` perf timer) | **new** | direct evidence for step 2 |
| M7 | UI paint cost (`display_frame_photo`, `display_first_frame` avg) | yes (PerfLogger) | step 4 |
| M8 | decode count (`load_frame_total` n) + duplicate decodes | partly | wasted work (steps 1, 5) |
| M9 | **resize phase**: decodes wasted + time to a sharp frame after the last resize | **new** | step 5 |

Scenario variants: **1080p** and **4K-syn** video × **default panel** (1200×1000 window,
955×814 panel) and **full-screen panel** (window = screen size; Windows clamps larger
geometry to the screen, ~1711×1048 here).

---

## Step 0 — Fix the ruler (no behavior change)

We can't prove an improvement with a broken ruler. Today `_painted()` in the perf test
means "current frame is in the buffer", not "the frame is on screen" — step 2 changes
exactly that gap, so the metric must measure the real paint.

- **0a** `LabelingApp.displayed_frame`: public attribute set in `display_first_frame`
  only when an image was actually shown. The perf harness waits on it instead of the buffer.
- **0b** Heartbeat lag (M4): a helper in the perf test schedules `after(5)` repeatedly and
  records `actual - expected` delay; reported per phase (load, steps, jumps, playback, resize).
- **0c** Paint timestamps during playback → jitter (M5).
- **0d** `perf.time("ui_marshal")` around the `schedule_on_ui` calls in `FrameBuffer` (M6).
- **0e** Resize phase (M9): 20 geometry changes over 1 s, then wait for a sharp frame.
- **0f** `TINYTOUCH_PERF_PANEL=fullscreen` variant.
- **0g** `tests/perf/make_sample_videos.py` — regenerates `sample_1080p.mp4` /
  `sample_2160p.mp4` from `cat3.mp4` (they are gone from `videos/`). No CLI — constants on top.
- **0h** Run the baseline **3×** per variant → noise band + baseline table in RESULTS.md.

**Correctness test:** unit test for `displayed_frame` — set when a buffered frame is shown,
unchanged when the frame is missing. All existing tests still pass (no behavior change).

**Done 2026-09-26 — what it uncovered.** The old harness drove Tk with `update()` loops
(`gui_driver.pump`). From such a loop, a worker's `Tk.after()` waits ~1 s inside tkinter
and then raises "main thread is not in main loop" (measured: 1074 ms). So in the harness
the buffer thread's repaints never arrived and each attempt stalled it for a second — the
"~1.2 s 4K jump tail" in RESULTS.md was this harness artifact, not the app. The scenario
now runs entirely inside a real `mainloop()` (a generator driven by `after()`), like
production. Also added: `duplicate_decode` counter (M8), `tests/perf/run_perf_matrix.py`
(runs the matrix 3× and prints medians vs. the `baseline` label).

**Files:** `src/labeling_app.py` (one attribute), `src/adapters/frame_buffer.py` (one perf
timer), `tests/e2e/test_perf_scenario.py`, `tests/perf/make_sample_videos.py`, RESULTS.md.

---

## Step 1 — Priority loads respect in-flight decodes (bug) + lost priority hint

**Problem.** `background_update` steps 1-2 check only `_buffer`, not `_inflight`. A frame
already queued or running in the pool gets decoded a second time on the coordinator
thread, and the finishing sync decode pops the pool job's `Future` from `_inflight`, so
that job can no longer be cancelled. Separately, `priority = self._priority_frame;
self._priority_frame = None` is not atomic, so a hint arriving between the two lines is lost.

**Change.** If the target has a queued `Future` → cancel it, decode synchronously. If it is
running → wait for that `Future` (short timeout) instead of decoding again. Take-and-clear
the priority hint under the lock.

**Correctness test (red → green)**, `tests/unit/test_frame_buffer_priority.py`:
block the pool with gated jobs, queue frame N, run one tick with `current_frame = N` →
assert N was decoded **exactly once** (count `Image.open` calls for `frameN.jpg`) and ends
up buffered. Second test: a running decode of N is awaited, not duplicated.
The hint race can't be reproduced deterministically; its fix is covered by code review
and a test that `request_priority` followed by one tick loads the hinted frame.

**Measure:** M8 duplicate decodes → 0. M1/M2 should not get worse. Expected effect on
latency: small — this is mainly a correctness fix and a warm-up for the harness.

**Done 2026-09-26.** Duplicate decodes 11-12 → 0 in every variant; no regression beyond
noise (A/B vs `53daf86`, see RESULTS.md). Lesson: sessions drift, so from now on every
step is measured in A/B mode against the previous step's commit, e.g.
`$env:TINYTOUCH_PERF_AB_REV = "<step-1 commit>"; $env:TINYTOUCH_PERF_LABEL = "step2"`,
and `display_frame_photo` / `load_s` serve as control metrics where a step doesn't touch them.

---

## Step 2 — Workers never call Tk (the big one)

**Problem.** `schedule_on_ui = lambda fn: self.after(0, fn)` is called from the buffering
thread (priority repaint, status pill) and the playback thread. Each call waits for the
Tk thread, so a slow repaint stalls buffering (step 0 trial run: `ui_marshal` avg 72 ms,
max 183 ms per call under a real mainloop). It is also the source of the three
"main thread is not in main loop" shutdown guards, and outside `mainloop()` (nested
`update()` pumps) each call blocks ~1 s and then fails. (The old "~1.2 s jump tail"
hypothesis is withdrawn — see step 0.)

**Change (design).** Invert the direction of communication — *share data, not calls*
(Fluent Python ch. 19 p. 770, the actor-model idea):
- `FrameBuffer` only writes into its buffer and exposes plain state
  (`get()`, `__contains__`, `is_current_window_loaded`). It loses `schedule_on_ui`,
  `on_status_change` and `on_priority_frame_loaded`.
- The Tk thread runs one small **display pump** (`after()` loop, ~10 ms): if
  `displayed_frame != current_frame` and the frame is buffered → paint; update the status
  pill when it changes. `_set_loading_label_async` becomes a plain Tk-thread call.
- The pump is the ONLY path from buffer to screen; `next_frame` still paints immediately
  when the frame is already buffered (no added latency on the common path).

**Correctness test (red → green)**, gui-marked, `tests/e2e/test_buffer_independent_of_ui.py`:
real Tk root, current frame NOT buffered, block the Tk thread for 600 ms inside a
callback, sample the buffer at 300 ms. Today: only the current frame is there (the
coordinator is stuck in `after()`). After: the prefetch window is filling.
Plus a unit test: the pump paints a frame that arrives in the buffer after the step.
Existing close/reload/extraction e2e tests must still pass with the guards removed.

**Measure:** M6 → 0 (the code path is gone). M2 median/p95 (a jump target decoded by the
coordinator no longer waits ~72 ms for its repaint to be accepted). M4 no worse.
M1 no worse (the pump adds ≤ 10 ms only when the frame was NOT buffered).

**Docs:** ARCHITECTURE.md "Background processes", the `frame_buffer.py` module docstring
(invariant (c)), `test_h1_thread_boundary.py` docstring.

**Done 2026-09-26.** Buffering thread blocked on Tk: 1.1-3.2 s/run → 0. Jump latency
−18-36 % on 1080p and 4K-default, step median −36 % on 1080p-default; 4K full-screen
unchanged (paint-bound); control metric flat (A/B vs `127223d`, see RESULTS.md).
`schedule_on_ui` stays for the playback thread only; the H1 docstring still describes
that thread correctly, so it waits for step 3. Two harness fixes on the way: the resize
wait is state-based now, and A/B runs copy the current scenario into the worktree.

---

## Step 3 — Playback on the Tk thread (delete the playback thread)

**Problem.** The playback thread sleeps, then asks the Tk thread to advance (a blocking
round-trip, see step 2), guarded by `_advance_pending` and the single-writer rule. The
thread adds complexity but no parallelism — all real work (paint) happens on Tk anyway.

**Change.** `_wheel_tick` already is a deadline-paced, buffer-gated stepper on the Tk
thread. Generalize it into one **paced stepper** used by both: wheel = finite backlog,
Play / arrow-hold = unlimited until Stop or boundary. `compute_play_step` stays (pure, H1
tests pin it). Delete `background_update_play`, `_request_advance`, `_advance_pending`,
`apply_play_advance`, `on_playback_schedule_error`, `play_thread_on`,
`background_thread_play`.

**Correctness tests**, in the style of `test_mouse_wheel_pacing.py` (fake clock, no Tk):
play advances one frame per frame interval; waits without advancing when the next frame
isn't buffered; stops at the boundary in both directions; Stop cancels the pending tick;
the Select Frame dialog pauses it; wheel input during playback behaves as defined
(decide: wheel stops playback — matches today's single-writer intent).

**Measure:** M3 fps must stay ≥ baseline (1080p ≥ 24/25). **M5 jitter should drop**
(advance + paint now happen in one deadline-paced callback instead of thread sleep +
queued `after(0)`). M4 no worse.

**Done 2026-09-26.** Implemented as a separate `_play_tick` sharing only the deadline
helper with the wheel (one stepper with mode flags would have been harder to read than
two small ones). The first version made jitter worse; the cause was two Windows timing
properties (coarse `time.monotonic()`, 15.6 ms `after()` granularity) — fixed with
`perf_counter` and `adapters.timer_resolution.PreciseTimers`. Final: jitter −20..−57 %
and interval p95 −6..−33 % in all four variants; UI-lag metric rose, at least partly a
heartbeat artifact of the timer-resolution change (see RESULTS.md).

---

## Step 4 — Reuse one `PhotoImage` (paste instead of recreate)

**Problem.** `display_first_frame` creates a new `ImageTk.PhotoImage` and reconfigures the
label for every frame — the dominant UI-thread cost on big panels.

**Change.** Keep one `PhotoImage`; if the new frame has the same size, `paste()` into it,
otherwise create a new one (after a resize). Check the pinned Pillow 11.3 `ImageTk.paste`
semantics via docs before implementing.

**Correctness test**, gui-marked: two consecutive same-size frames keep the same Tk image
name on the label and the label shows the second frame's pixels (sample a pixel via Tk
`PhotoImage.get`); a size change creates a new image.

**Measure:** M7 `display_frame_photo` avg down ~30 % (benchmark: 8.6 → 5.8 ms at the
default panel). M3 fps up on 4K / full-screen (UI-bound there). M4 p95 during playback down.

**Done 2026-09-26.** `display_frame_photo` turned out not to be comparable (it excluded the
label reconfigure on the old side); on the whole paint call `display_first_frame`: −12..−22 %,
step/jump latency −17..−31 % in every variant, 4K full-screen playback 22.9 → 24.0 fps
(A/B vs `ec82208`; 1080p-default re-measured with 5 pairs — see RESULTS.md).

---

## Step 5 — Resize: only reset on a real size change, debounced

**Problem.** `on_resize` clears the whole buffer on every `<Configure>`, even with an
unchanged size; a drag-resize throws away all decoded frames many times per second.

**Change.** Ignore events with the same size as the cached one. Debounce (~150 ms after
the last event) before resetting the buffer; keep showing the old frame meanwhile.

**Correctness tests** (unit, fake `after`): same-size event → buffer generation unchanged;
burst of 20 size changes → exactly one reset, with the final size.

**Measure:** M9 wasted decodes during the resize phase → near 0; time to sharp frame
after the last resize ≈ debounce + one decode.

---

## Step 6 — Frame extraction off the Tk thread

**Problem.** Extraction runs on the Tk thread; the progress callback pumps events with
`win.update()` once per `progress_interval_s` (1 s) and the thread sleeps in between →
the window freezes ~1 s at a time, and `update()` is a nested event loop (re-entrancy).
The export already uses the right pattern (worker thread + `after()` poll + `wait_window`).

**Change.** Run `project_service.extract_frames` in a worker thread; progress goes through
a thread-safe value the Tk side polls every 100 ms. Cancellation keeps using the existing
`Event`. (The state-DB `load_frames` progress window must stay on Tk — the repository is
pinned to the Tk thread by design.)

**Correctness test (red → green)**, gui-marked: extract a ~10 s generated video while a
heartbeat runs; assert max event-loop gap < 250 ms (today ~1000 ms — large margin, not
flaky). `test_close_during_extraction.py` must still pass.

**Measure:** M4 max lag during the load phase: ~1000 ms → < 100 ms. Load wall time
unchanged (ffmpeg does the work either way).

---

## Later / out of scope for this plan

- **Extraction resolution setting** (RESULTS.md decision 8): extract 4K at display height.
  Biggest lever for 4K sources (106 → ~4 ms decode per frame).
- **Very long videos** (`videoplayback_3h.mp4`: 344,034 frames): one JPEG per frame means
  a long extraction and many GB on disk. Worth measuring separately before designing.
- If after step 4 full-screen playback is still UI-bound, that is the Tk `PhotoImage`
  ceiling; the remaining knobs are `video_downscale` / `max_display_*`.

## Order and why

0 → 1 → 2 → 3 → 4 → 5 → 6. The ruler comes first. Step 1 is small and exercises the new
harness. Step 2 must come before 3 (the stepper relies on "no worker talks to Tk").
Steps 4-6 are independent and could be reordered or done in parallel branches.
