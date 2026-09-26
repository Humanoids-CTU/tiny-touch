# Frame buffer & decode performance — experiment record

Investigation from 2026-08-23, commit `129f028` (branch `refactor/architecture-cleanup`),
Windows 11, Python 3.12.3, 16 logical cores. All numbers reproducible with the
harnesses in this folder. Raw scenario JSONs land in `tests/perf/results/`
(gitignored); the key numbers are inlined below.

## Question that started it

Could a stdlib queue (Fluent Python ch. on queues) speed up the frame buffer?

**Answer: no.** The buffer is a random-access cache keyed by frame index with
distance-from-playhead eviction — queues/deques are FIFO pipes and structurally
cannot express keyed random access; a dict's keyed ops are already O(1).
Container cost is ~14 µs per buffering tick vs ~37-173 ms to decode ONE frame:
5-6 orders of magnitude apart. The real wins are in the decode pipeline.

## Experiment 1 — container strategies (`benchmark_frame_buffer.py`)

Simulates the exact background_update tick against alternative containers.

| implementation | µs/tick seq | µs/tick jumps | UI read p99 (threaded) |
|---|---|---|---|
| dict + RLock (current) | 14.1 | 33.7 | 0.4 µs |
| dict + Lock | 14.3 | 31.4 | 0.5 µs |
| dict, no lock | 12.6 | 33.9 | 0.5 µs |
| OrderedDict LRU | 15.5 | 30.5 | 114 µs |
| deque of (idx, img) | 778 | 710 | reader CRASHED (mutated during iteration) |
| queue.Queue + aux dict | 14.1 | 61.5 | 0.4 µs |

Notes: LRU is also the wrong eviction policy (recency ≠ distance). The RLock is
load-bearing (`_evict_to_budget` → `_remove_frame` re-entrancy). PIL releases
the GIL during decode/resize (Pillow PR #1224), so the 3-worker pool is real
parallelism. Unlocked `dict.get` reads by the UI thread are safe under the GIL
(and under 3.13+ free-threading).

## Experiment 2 — decode pipeline (`benchmark_decode_pipeline.py`, `benchmark_real_videos.py`)

Real extracted frames (app's exact `-q:v 2` extraction), display 1280x720:

| video | kB/frame | current (full+LANCZOS) | draft+LANCZOS | draft+BILINEAR |
|---|---|---|---|---|
| 480p | 107 | 3.8 ms | 2.9 ms | 3.3 ms |
| 1080p | 455 | 44.7 ms | 44.2 ms | 31.2 ms |
| 4K synthetic (grain) | 1672 | 118.8 ms | 54.0 ms | 41.5 ms |
| 4K real (BBB) | 161 | 106.1 ms | 40.3 ms | **28.8 ms (3.7x)** |

- Decode cost tracks PIXEL COUNT, not file size (4K real: 10x smaller files,
  same decode time as grainy synthetic).
- `Image.draft()` decodes at 1/2..1/8 DCT scale; only helps when a reduced
  scale still ≥ target (why 1080p→720p sees no draft win — BILINEAR carries it).
- Quality drift of all fast variants: RMS 0.0-0.9 / 255 (JPEG re-save alone is
  ~2-4). Invisible.
- Extraction-resolution lever: a 4K video extracted at 720p costs 3.8 ms/frame
  forever instead of 106 ms — the single biggest lever for 4K sources
  (planned as a separate Settings feature, not yet implemented).

## Experiment 3 — upscale for big monitors (`benchmark_upscale_display.py`)

480p source shown on large canvases (today the app never upscales → tiny image):

| stored size | upscale BILINEAR | PhotoImage/repaint (UI thread) | RAM/frame | frames in 1 GB |
|---|---|---|---|---|
| native 480p | — | 3.5 ms | 1.2 MB | 813 |
| 1080p | 31.9 ms | 14.4 ms | 6.2 MB | 160 |
| 1440p | 52.1 ms | 28.2 ms | 11.0 MB | 90 |
| 4K | 94.8 ms | 60.1 ms | 24.9 MB | 40 |

Verdict: upscale must run in the decode workers (strategy A). Paint-time
upscaling on the UI thread costs 44-143 ms per repaint — over the 40 ms
playback budget from 1080p up. Full-4K canvas is a hard Tk ceiling
(PhotoImage alone 60 ms). Byte budget must cap the prefetch window or
eviction churns against submission at big frame sizes.

## Experiment 4 — decode pool scaling (`benchmark_worker_scaling.py`)

Filling a 50-frame window of real 4K frames (16 logical cores):

| workers | current pipeline | draft+BILINEAR |
|---|---|---|
| 3 (today) | 20.0 fr/s | 86 fr/s |
| 6 | 28.6 fr/s | 118 fr/s |
| 8 | 29.2 fr/s | 127 fr/s |

3 → 6-8 workers ≈ 1.4-1.5x. Flattens at physical-core saturation.
Also: raising the 1 GB budget does NOT speed anything up at today's frame
sizes (trim's ±200-frame keep-range binds first); it only matters once
upscaled frames shrink the budget to <100 frames.

## Baseline — real-app scenario (`tests/e2e/test_perf_scenario.py`)

Robot-user run against commit `129f028`, hidden real Tk window, panel 955x814,
fixed seeded workload. Rerun with:

```powershell
$env:TINYTOUCH_PERF="1"; $env:TINYTOUCH_PERF_LABEL="<label>"
uv run pytest tests/e2e/test_perf_scenario.py -m gui -s
# optional: $env:TINYTOUCH_PERF_VIDEO="videos\sample_real4k_bbb.mp4"
```

| metric | 1080p sample | real 4K sample |
|---|---|---|
| load → first frame | 8.1 s | 29.5 s |
| single step median / p95 | 25 / 45 ms | 44 / 93 ms |
| jump (125/300 fr) median / p95 | 39 / **1151 ms** | 507 / **1294 ms** |
| playback achieved / target fps | **12.4 / 25** | **0.0 / 60** |
| playback stalled | 40% | 100% |
| per-frame `load_frame_total` avg | 49 ms | 173 ms |
| `load_frame_resize` share | 32 ms | 125 ms |

The jump p95 of ~1.1-1.3 s is the stale-FIFO-decode problem (pool queue full
of old-window jobs after a jump; generation only bumps on reset()).

## Sample videos (`videos/`, gitignored)

| file | content |
|---|---|
| `sample_480p.mp4` | cat3 downscaled, 30 s, grain |
| `sample_1080p.mp4` | cat3 upscaled + grain (soft-looking; decode-realistic) |
| `sample_2160p.mp4` | cat3 upscaled + grain (decode worst case) |
| `sample_real4k_bbb.mp4` | genuine 4K Big Buck Bunny (4000x2250@60), 30 s — use for eye tests |

Regenerate: loop cat3.mp4 through ffmpeg `scale=WxH:flags=lanczos,noise=alls=8:allf=t`,
libx264 crf 20. The real-4K one: first 30 s of the Wikimedia Commons
`Big_Buck_Bunny_4K.webm` master transcoded to h264.

## After optimization — same scenario, changes applied (2026-08-23, uncommitted on `129f028`)

Changes 1-6 below implemented in `src/adapters/frame_buffer.py`
(draft decode, BILINEAR, worker-side upscale, jump cancellation,
adaptive 3-8 worker pool, 0.15 s pause, byte-aware window):

| metric | 1080p before → after | real 4K before → after |
|---|---|---|
| playback achieved fps | 12.4 → **24.2** (target 25) | 0.0 → **43.5** (target 60) |
| playback stalled | 40% → **0%** | 100% → **1.1%** |
| jump p95 | 1151 → **155 ms** | 1294 → 1201 ms (tail remains, see note) |
| jump median | 39 → 68 ms | 507 → **107 ms** |
| single step median | 25 → 29 ms | 44 → **22 ms** |
| per-frame `load_frame_total` | 49 → **29 ms** | 173 → **40 ms** |

Notes: the 4K jump tail (~1.2 s at p95, i.e. the worst 1-2 of 30 jumps)
persists — the buffering-loop tick can be mid-window-submission when a jump
arrives, so the priority load waits one long tick; candidate refinement, and
the extraction-resolution setting remains the real fix for 4K sources.
4K playback is now UI-thread-bound (PhotoImage + repaint at 60 fps target),
not decode-bound. Raw JSONs: `results/perf_optimized_*.json`,
`results/perf_optimized-4k_*.json`.

## Decisions taken from the data

1. Draft-mode JPEG decode + BILINEAR resize in the worker path (1.5-3.7x/frame).
2. Upscale to canvas fit in the workers (fixes small-video-on-big-monitor).
3. Cancel stale prefetch futures on jumps (kills the ~1.2 s jump p95 tail).
4. Adaptive pool size `max(3, min(8, cpu//2))` (~1.4x window fill).
5. `PLAYBACK_BUFFER_PAUSE_S` 1.0 → 0.15 (snappier stall recovery).
6. Byte-aware prefetch window (prevents evict/submit churn with big frames).
7. NOT changed: the dict+RLock container, sorted() eviction, unlocked UI reads,
   ThreadPoolExecutor itself, the 1 GB budget constant.
8. Later, separate task: extraction-resolution setting ("extract 4K at HD").

---

# Smoothness plan — re-baseline (2026-09-26)

See [SMOOTHNESS_PLAN.md](SMOOTHNESS_PLAN.md). Step 0 rebuilt the robot-user scenario;
all later steps compare against the `baseline` label below.

## Correction to the section above

The "4K jump tail (~1.2 s at p95)" measured on 2026-08-23 was a **harness artifact**.
The old scenario drove Tk with `update()` loops instead of `mainloop()`. From such a loop a
worker thread's `Tk.after()` waits ~1 s inside tkinter and then raises "main thread is
not in main loop" (measured: 1074 ms), so every priority repaint stalled the buffer
thread for a second and was then dropped. The scenario now runs inside a real
`mainloop()`; the jump p95 under production conditions is 110-180 ms (below).

## Baseline — commit `d56de5a` + step 0 instrumentation

Median of 3 runs per variant; `spread` = max − min over the 3 runs (the noise band).
Sample videos: `make_sample_videos.py` (cat3 looped to 30 s, 25 fps, grain).
Panels: default = 1200×1000 window (914×814 video panel); fullscreen = screen-sized
window (Windows clamps to ~1711×1048 here).

| metric | 1080p default | 1080p full | 4K default | 4K full |
|---|---|---|---|---|
| load s | 10.0 | 10.5 | 35.0 | 34.2 |
| step median / p95 ms | 13.9 / 21.4 | 26.0 / 47.2 | 17.9 / 25.2 | 33.2 / 46.4 |
| jump median / p95 ms | 26.1 / 108.7 | 40.7 / 151.4 | 26.5 / 128.3 | 37.2 / 178.5 |
| playback fps (target 25) | 24.5 | 23.7 | 24.5 | 23.3 |
| playback jitter ms (stdev of paint intervals) | 4.6 | 7.9 | 4.7 | 10.3 |
| playback interval p95 ms (ideal 40) | 48.2 | 59.0 | 48.2 | 59.1 |
| resize → sharp frame ms | 90 | 140 | 178 | 192 |
| decodes during one resize burst | 926 | 466 | 480 | 276 |
| UI lag max during load ms | 1333 | 1333 | 1577 | 1453 |
| UI lag p95 steps / jumps / playback ms | 25 / 69 / 15 | 46 / 88 / 25 | 27 / 64 / 18 | 47 / 60 / 27 |
| `display_frame_photo` avg ms | 3.9 | 8.0 | 4.4 | 7.8 |
| worker blocked on Tk, total ms (`ui_marshal` + `_play` + `ui_status`) | 2480 | 2272 | 2649 | 1972 |
| duplicate decodes | 11 | 12 | 12 | 11 |

Noise notes: step/jump medians spread 2-25 ms; `resize_to_sharp_ms` and the
worker-blocked totals are very noisy (spread up to 100 %+), so only large changes
there count. Idle event-loop lag floor is ~0.1 ms (p95).

What the baseline says, mapped to plan steps:
- step 1 — ~11 wasted duplicate decodes per run.
- step 2 — worker threads spend 2-2.6 s per run blocked waiting for the Tk thread.
- step 3 — playback interval p95 48-59 ms vs the ideal 40 ms (jitter 5-10 ms).
- step 4 — `display_frame_photo` doubles on the full-screen panel (4 → 8 ms).
- step 5 — one resize burst costs 276-926 decodes.
- step 6 — loading freezes the UI for 1.3-1.6 s at a time.

## Step 1 — priority loads reuse in-flight decodes (A/B vs `53daf86`)

Change: `FrameBuffer._load_priority` cancels a queued pool decode of the same frame (and
decodes it on the buffering thread) or waits for a running one, instead of decoding the
frame a second time; the priority hint is taken-and-cleared under the lock.
Correctness: `tests/unit/test_frame_buffer_priority.py` (red on `53daf86`: frame decoded
2× in both the queued and the running case; green after).

**Method change.** The first step-1 matrix (run ~40 min after the baseline) showed code
paths step 1 cannot touch — `display_frame_photo` (UI-thread `PhotoImage`) and `load_s`
(ffmpeg) — 20-70 % slower: the laptop's speed drifted between the two sessions by more
than the effects measured. `run_perf_matrix.py` got an A/B mode
(`TINYTOUCH_PERF_AB_REV`): the reference commit runs from a temporary git worktree,
interleaved A B / B A / A B with the new code. All numbers below are from that mode.

| metric (median of 3) | 1080p default | 1080p full | 4K default | 4K full |
|---|---|---|---|---|
| duplicate decodes, before → after | 11 → **0** | 12 → **0** | 12 → **0** | 12 → **0** |
| step median ms | 17.5 → 17.6 | 38.9 → 26.9 | 21.0 → 17.6 | 35.6 → 35.1 |
| jump p95 ms | 126 → 131 | 251 → 169 | 171 → 141 | 173 → 169 |
| playback fps | 23.6 → 23.8 | 15.5 → 22.1 | 19.6 → 24.2 | 21.9 → 22.4 |
| control: `display_frame_photo` ms | 5.4 → 5.8 | **14.3 → 9.7** | **6.3 → 4.9** | 8.7 → 8.6 |

Verdict: the target metric is met exactly (no frame is decoded twice any more), and no
metric regressed beyond the noise band. The large latency/fps "gains" in the 1080p-full
and 4K-default columns are NOT attributable to step 1: the control metric, which step 1
cannot affect, moved by a similar amount in the same runs, so those reference runs simply
landed on slower moments. Run-to-run spread is 30-100 % for several metrics even when
interleaved; only deterministic counts (decodes) and large effects are trustworthy on
this machine. Always read the control row before believing a latency change.
