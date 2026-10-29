# mpv playback demo

Run from the TinyTouch repository in PowerShell:

```powershell
uv pip install --python .venv/Scripts/python.exe -r demos/requirements.txt
uv run demos/mpv_demo.py
```

This is a standalone experiment. It reads the selected source video directly;
it does not load, edit, or save TinyTouch annotation projects or extract JPEGs.
Its optional Python dependency is pinned separately from the application.

## Native mpv library

The Python package also needs **libmpv**, not just the mpv executable.

On Windows, download an x86_64 **mpv-dev** archive from one of the build providers
linked by [mpv's installation page](https://mpv.io/installation/). Extract
`libmpv-2.dll` (or `mpv-2.dll`, depending on the build), and any accompanying
runtime DLLs, into `demos/runtime/`. Use an architecture matching Python. This
directory is ignored by Git. The demo also searches the existing system PATH.

The local development runtime used for this demo is shinchiro's
`mpv-dev-x86_64-20261021-git-e471496c56.7z`, linked from that installation page.
Its downloaded archive SHA-256 is
`efc719eff3dc5954b4a5efc800632808bcec01cc9034940dd14e5eb7fe9ea633`.
Native binaries are not committed or included in TinyTouch releases.

On Linux, install libmpv through your distribution's package manager and use
an X11 desktop or XWayland. The embedded window path uses Windows HWND or X11
window IDs; native Wayland embedding is not implemented. Run with the project's
local `.venv`, installing `demos/requirements.txt` into it with `uv pip`.

## Controls

- **Open video** selects an original video file and opens it paused.
- **Play / Pause** or **Space** toggles playback.
- **Previous frame / Next frame** or **Left / Right** steps and pauses.
- **-5 s / +5 s** or **Shift+Left / Shift+Right** seeks and pauses.
- **Current frame** is shown prominently at the top right, calculated as
  `round(playback_time * nominal_fps)` under the constant-FPS assumption. The
  first frame is **0**; a player that numbers its first frame **1** will show
  one more for the same image. The counter refreshes every 100 ms.
- **Jump to frame (0-based)** accepts an integer; **Jump** or **Enter** seeks
  to `frame / nominal_fps` using mpv's exact time-seek mode.
- **Hardware decoding** requests automatic hardware decoding or software decoding.
  Check **Active hardware decoder** to see what is actually in use: `no` means
  software decoding, even if automatic hardware decoding was requested.
- Sound starts muted; clear **Mute** to enable it.

Keyboard navigation leaves the frame entry's normal text-editing keys alone.
Click the video or use a transport button to move focus out of the entry.

## What this can establish

Try the same videos, window size, and navigation patterns as TinyTouch. Compare
opening delay, smoothness, seeking, resizing, and CPU/memory in Task Manager.
Toggle hardware decoding and check the active decoder and dropped-frame count.
The displayed load/seek timing includes the 100 ms UI polling interval; it is an
mpv readiness-event measurement, **not** measured input-to-visible-frame latency
or an automated benchmark against TinyTouch.

**Frame identity is not guaranteed.** mpv reports estimated frame numbers/counts,
and converting a frame number to time assumes constant frame rate. Variable
frame rates, timestamp offsets, and different decoder/extraction behavior can
disagree with TinyTouch's JPEG sequence. Exact time seeking does not establish
exact annotation-frame identity. Backward steps may also be slower than cached
JPEG navigation. Do not use this demo to create research annotations.

Before integration, compare displayed frames against TinyTouch's sequence and
verify pause/seek completion, rapid direction changes, first/last frames, and
Windows/Linux packaged builds. See the [mpv manual](https://mpv.io/manual/stable/)
and the [Python binding documentation](https://github.com/jaseg/python-mpv).

## Automated control check

With libmpv installed and a display available:

```powershell
uv run pytest tests/e2e/test_mpv_demo.py -m gui
```

This uses a disposable, numbered video to check playback, pause, both frame-step
directions, frame jumps, validation, decoder switching, and recovery from a failed
file load. It skips when the optional runtime is missing. The scenario runs in
a separate process so its native player and Tk state cannot affect TinyTouch's
GUI tests.
