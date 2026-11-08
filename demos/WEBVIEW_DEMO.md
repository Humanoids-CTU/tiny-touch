# HTML desktop proof of concept

From the repository root in PowerShell:

```powershell
uv run --with-requirements demos/webview-requirements.txt demos/webview_demo.py
```

This opens a separate native desktop window containing a local HTML/CSS/JavaScript
page. The existing TinyTouch launcher, dependencies, annotation code and research
projects are untouched. The demo reads videos only; it never creates a project.
Open a video, play/pause with Space, step with the left/right arrows, or seek using
the slider. Double-arrow buttons jump ten frames; Stop pauses at the displayed
frame. The UI counts frames from 1; Python decoder indices start at 0.

The light layout follows the current Tkinter workspace: application tools and
navigation above the video, two timeline tracks below it, and the actual TinyTouch
body diagram, channel selector, parameters and notes in the right column. Settings,
annotation, analysis and saving controls are disabled visual placeholders. The
timeline tracks are empty placeholders; the separate seek slider works.

Python/OpenCV decodes individual indexed frames and sends reduced-width JPEG
previews through pywebview's Python bridge. Sequential playback avoids seeking;
backwards navigation and slider jumps use OpenCV frame seeking. This is not
browser video time seeking. Codec-dependent OpenCV seeking still needs verification
against real annotation footage before claiming production frame identity.

This intentionally simple experiment has no audio, annotation, persistence,
prefetch buffer or GPU video rendering. Slow decoding/bridge transfer slows
playback rather than skipping frames. Preview width is capped at 1280 pixels.
It evaluates a web UI inside a desktop shell, not final playback performance.

Windows needs the Microsoft Edge WebView2 Runtime. Linux additionally needs a
pywebview GUI backend (Qt or GTK with the matching system libraries); that setup
and platform behavior have not been verified. See the
[official pywebview installation guide](https://pywebview.flowrl.com/guide/installation.html).
The HTML has no external assets or network dependencies.
