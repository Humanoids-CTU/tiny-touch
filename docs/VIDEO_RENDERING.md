# GPU + 1080p JPEG integration: manual acceptance

Run from the repository using the local environment:

```powershell
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
uv run src/main.py
```

The dependencies are already installed in this workspace. No mpv runtime is
needed by the main app. The source video and annotation format are unchanged.

## What to try

1. Load a video and open **Settings**. **Video renderer** defaults to
   **Automatic (GPU preferred)**. **Active renderer** should say **GPU** on a
   supported machine, or **CPU (GPU unavailable)** if acceleration cannot start.
2. Play/pause, use both arrow directions, jump to a frame, and resize the window.
   Also minimize/restore or cover/uncover a paused video. Check that the frame
   remains visible and the counter follows navigation.
3. Add a few annotations, parameters and notes. Save, close and reopen the
   project to confirm the normal workflow. Annotation actions are blocked while
   a requested frame has not been painted yet; wait for the existing Buffer
   chip to indicate that loading has finished before adding a mark.
4. Enter a note draft, then switch **Video renderer** to **CPU** and click
   **Apply**. Playback pauses. Confirm the image, frame number, saved annotations
   and unsaved note survive. Repeat with **Automatic (GPU preferred)**. Compare
   responsiveness between the two modes.
5. To check extraction, load a 4K video that has not already had frames prepared.
   Its new `data/<video>/frames/frame0.jpg` should be 1920x1080 for a 16:9 source.
   Other aspect ratios fit inside that box; a portrait source can be narrower
   than 1080 pixels. Inputs below the limit retain their dimensions.

Existing caches are deliberately reused. Opening an already-prepared 4K project
does not rewrite its JPEGs. To try fresh extraction with an existing source, use
a copy with a new filename rather than deleting any project data.

## Implementation and verification boundary

Validation on Windows, 3 November 2026:

- Complete non-GUI suite: **525 passed**, 41 GUI tests deselected.
- Production GUI suite: **35 passed, 1 skipped** (the opt-in performance scenario).
  Standalone mpv/GPU/refresh demos were excluded from this production run.
- The three new native GPU integration checks passed, including an annotation
  exported at the independently read GPU frame ID and the actual Settings
  selector's CPU/Automatic switches.
- PyInstaller's SDL binary collection finds the runtime libraries; a frozen
  executable was not built or exercised.

The app retains JPEG frame access. GPU mode moves final scaling/drawing into SDL;
JPEG decoding remains in the background workers. CPU mode retains the original
Pillow resize/PhotoImage implementation. Initialization or drawing failure
automatically selects CPU and rebuilds the buffer for that path.

Tests use temporary projects and invisible windows. They check capped extraction
through FFmpeg and OpenCV, burned frame identity through the actual embedded GPU
renderer, forward/backward jumps, paused resize/expose redraw, automatic fallback,
renderer switching, exact counters and unsaved notes. The established CPU GUI
tests remain explicitly on CPU so their PhotoImage assertions still apply.

The native GPU readback verifies rendered buffers; final visible-window behavior
and normal physical keyboard/mouse use are the purpose of this manual acceptance.
Whole-app playback measurements are recorded below; earlier component speedup
percentages should not be treated as a combined whole-app speedup.
Windows is exercised here; Linux GPU embedding and a frozen executable still
need platform/build acceptance. Unsupported acceleration retains CPU rendering.

## Realtime playback validation (7 November 2026)

Playback now avoids redundant button style writes, refreshes frame controls and
both timeline cursors at up to 25 Hz, and keeps video pacing on source-FPS
deadlines. Every source frame is still painted; frames are not skipped to hide
slow rendering. Stop, arrow release, navigation and annotation synchronize the
controls immediately. Arrow taps retain a 150 ms grace period before continuous
playback. Focusing the note editor pauses playback before editing.

Visible-window Windows/GPU tests used generated 1920x1080, 100 FPS clips and
temporary projects with touch markers, changing parameters and notes:

| Clip | Play | Hold Right | Hold Left |
| --- | ---: | ---: | ---: |
| 5 seconds / 500 frames | 4.99 s | 5.14 s | 5.13 s |
| 15 seconds / 1500 frames | 15.73 s | 15.14 s | 15.92 s |

All 499 / 1499 advances were painted in exact order, with zero buffer stalls.
The initial frame is already visible; the first advance is immediate. Holds
include the 150 ms grace period. These results show approximately 95-100 FPS,
not a hard realtime guarantee: longer runs still show scheduling/rendering
variation. Physical monitor refresh, Linux, packaged builds and CPU-only
100 FPS throughput have not been certified.

To repeat the opt-in benchmark against a local constant-frame-rate video:

```powershell
$env:TINYTOUCH_REALTIME_VIDEO = 'C:/path/to/test_100fps_5s.mp4'
uv run pytest -m gui tests/e2e/test_realtime_throughput.py -s -q
Remove-Item Env:TINYTOUCH_REALTIME_VIDEO
```

The benchmark exercises the production Play button and arrow-hold handlers,
checks every painted frame and endpoint controls, and enforces a timing ceiling
of expected duration plus 5% and 50 ms. It is opt-in because speed depends on
the host. Ordinary GUI tests cover pause/annotation synchronization, note drafts,
renderer changes and precise taps without imposing a hardware speed threshold.

Regression results: 562 non-GUI tests passed. The complete GUI run had 46 passes,
2 skips and one template/reliability failure; that module passed in isolation.
After correcting GUI helper paint-readiness waits and giving reverse-hold tests
room before the video boundary, all 7 affected arrow/template tests passed.
The 8 focused playback/renderer/refresh tests also passed. The full GUI suite
was not rerun to completion after these test-only corrections.
