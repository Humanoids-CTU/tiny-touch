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
The integrated build has not been performance-benchmarked, so earlier component
speedup percentages should not be treated as a combined whole-app speedup.
Windows is exercised here; Linux GPU embedding and a frozen executable still
need platform/build acceptance. Unsupported acceleration retains CPU rendering.
