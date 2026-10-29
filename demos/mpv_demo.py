"""Standalone mpv experiment. Run from the repository: uv run demos/mpv_demo.py."""

import importlib
import math
import os
from pathlib import Path
import queue
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


RUNTIME_DIR = Path(__file__).resolve().parent / "runtime"
POLL_MS = 100
WINDOW_SIZE = "1100x780"
SEEK_SECONDS = 5
MPV_ERRORS = (AttributeError, OSError, RuntimeError, ValueError)


def load_mpv():
    """Keep the optional dependency and native runtime outside TinyTouch."""
    if os.name == "nt":
        os.environ["PATH"] = str(RUNTIME_DIR) + os.pathsep + os.environ.get("PATH", "")
    return importlib.import_module("mpv")


def frame_time(text, fps, duration=None):
    """Convert a zero-based frame request using nominal FPS, never claim identity."""
    try:
        frame = int(text)
    except (ValueError, TypeError):
        raise ValueError("Enter a whole frame number starting at 0.") from None
    if frame < 0:
        raise ValueError("Frame numbers start at 0.")
    if fps is None or not math.isfinite(fps) or fps <= 0:
        raise ValueError("This video has no usable frame rate; frame jumps are unavailable.")
    seconds = frame / fps
    if duration is not None and seconds >= duration:
        raise ValueError("That frame is beyond the estimated video range.")
    return seconds


class MpvDemo(tk.Tk):
    def __init__(self, mpv_module):
        super().__init__()
        self.title("TinyTouch — mpv playback demo")
        self.geometry(WINDOW_SIZE)
        self.minsize(760, 500)
        self.player = None
        self.loaded = False
        self.events = queue.SimpleQueue()
        self.pending_since = None
        self.poll_id = None
        self.hardware = tk.BooleanVar(value=True)
        self.muted = tk.BooleanVar(value=True)
        self.frame_input = tk.StringVar(value="0")
        self.current_frame = tk.StringVar(value="Current frame: —")
        self.position = tk.StringVar(value="Open a video to begin.")
        self.diagnostics = tk.StringVar(value="")
        self.message = tk.StringVar(value="Space: play/pause   Left/Right: one frame   Shift+Left/Right: 5 seconds")
        self._build_ui()
        self.update_idletasks()  # Create the native window before passing its handle.
        try:
            self.player = mpv_module.MPV(
                wid=str(self.surface.winfo_id()),
                config=False,
                vo="gpu",
                hwdec="auto",
                keep_open="yes",
                idle="yes",
                pause=True,
                mute=True,
                osc=False,
                input_default_bindings=False,
                input_vo_keyboard=False,
                hr_seek_framedrop=False,
                log_handler=self._log,
                loglevel="error",
            )
        except Exception:
            self.destroy()
            raise

        # mpv callbacks run on its event thread. Only the Tk poller touches widgets.
        self.player.event_callback("file-loaded")(
            lambda event: self.events.put(("loaded", None)))
        self.player.event_callback("playback-restart")(
            lambda event: self.events.put(("ready", None)))
        self.player.event_callback("end-file")(self._end_file)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<space>", lambda event: self._shortcut(self.toggle_play))
        self.bind("<Left>", lambda event: self._shortcut(lambda: self.step(-1)))
        self.bind("<Right>", lambda event: self._shortcut(lambda: self.step(1)))
        self.bind("<Shift-Left>", lambda event: self._shortcut(lambda: self.seek(-SEEK_SECONDS)))
        self.bind("<Shift-Right>", lambda event: self._shortcut(lambda: self.seek(SEEK_SECONDS)))
        self.poll_id = self.after(POLL_MS, self._poll)

    def _build_ui(self):
        toolbar = ttk.Frame(self, padding=8)
        toolbar.pack(fill="x")
        self.open_button = ttk.Button(toolbar, text="Open video…", command=self.open_video)
        self.open_button.pack(side="left")
        ttk.Checkbutton(toolbar, text="Hardware decoding", variable=self.hardware,
                        command=self.change_hardware).pack(side="left", padx=12)
        ttk.Checkbutton(toolbar, text="Mute", variable=self.muted,
                        command=self.change_mute).pack(side="left")
        ttk.Label(toolbar, textvariable=self.current_frame,
                  font=("TkDefaultFont", 16, "bold")).pack(side="right", padx=8)
        self.surface = tk.Frame(self, bg="black", takefocus=True)
        self.surface.pack(fill="both", expand=True, padx=8)
        self.surface.bind("<Button-1>", lambda event: self.surface.focus_set())
        controls = ttk.Frame(self, padding=8)
        controls.pack(fill="x")
        self.transport_buttons = []
        for text, command in (
            ("−5 s", lambda: self.seek(-SEEK_SECONDS)),
            ("Previous frame", lambda: self.step(-1)),
            ("Play / Pause", self.toggle_play),
            ("Next frame", lambda: self.step(1)),
            ("+5 s", lambda: self.seek(SEEK_SECONDS)),
        ):
            button = ttk.Button(controls, text=text, command=command, state="disabled")
            button.pack(side="left", padx=(0, 5))
            self.transport_buttons.append(button)
        jump_controls = ttk.Frame(self, padding=(8, 0, 8, 8))
        jump_controls.pack(fill="x")
        ttk.Label(jump_controls, text="Jump to frame (0-based):").pack(side="left", padx=(0, 4))
        self.frame_entry = ttk.Entry(jump_controls, textvariable=self.frame_input, width=10)
        self.frame_entry.pack(side="left")
        self.frame_entry.bind("<Return>", lambda event: self.jump_to_frame())
        self.jump_button = ttk.Button(jump_controls, text="Jump", command=self.jump_to_frame,
                                      state="disabled")
        self.jump_button.pack(side="left", padx=5)
        self.transport_buttons.append(self.jump_button)
        for variable in (self.position, self.diagnostics, self.message):
            ttk.Label(self, textvariable=variable, padding=(10, 2)).pack(anchor="w")
        ttk.Label(self, text="Constant FPS assumed. First frame = 0. Current frame = round(playback time × FPS).",
                  padding=(10, 6)).pack(anchor="w")

    def _log(self, level, component, text):
        self.events.put(("error", f"{component}: {text.strip()}"))

    def _end_file(self, event):
        if event.data.error < 0:
            self.events.put(("load-error", f"Cannot play this file (mpv error {event.data.error})."))

    def _property(self, name):
        try:
            return getattr(self.player, name)
        except AttributeError:  # A property can be unavailable before the first frame.
            return None

    def _enable_transport(self, enabled):
        self.loaded = enabled
        for button in self.transport_buttons:
            button.configure(state="normal" if enabled else "disabled")

    def open_video(self, path=None):
        if path is None:
            path = filedialog.askopenfilename(parent=self, title="Open video", filetypes=[
                ("Video", "*.mp4 *.mkv *.avi *.mov *.webm *.m4v"), ("All files", "*")])
        if not path:
            return
        self._enable_transport(False)
        self.open_button.configure(state="disabled")
        self.title(f"TinyTouch — mpv demo — {Path(path).name}")
        self.position.set("Opening video…")
        self.current_frame.set("Current frame: —")
        self.message.set("Loading original video; no JPEG extraction.")
        try:
            self.player.pause = True
            self.pending_since = time.perf_counter()
            self.player.play(str(Path(path).resolve()))
        except MPV_ERRORS as error:
            self.pending_since = None
            self.open_button.configure(state="normal")
            self.message.set(f"Could not open video: {error}")

    def _action(self, operation):
        if not self.loaded:
            return
        try:
            operation()
        except MPV_ERRORS as error:
            self.message.set(f"Player action failed: {error}")

    def toggle_play(self):
        self._action(lambda: setattr(self.player, "pause", not self.player.pause))

    def step(self, direction):
        def operation():
            self.player.pause = True
            self.pending_since = time.perf_counter()
            if direction < 0:
                self.player.frame_back_step()
            else:
                self.player.frame_step()
        self._action(operation)

    def seek(self, seconds):
        def operation():
            self.player.pause = True
            self.pending_since = time.perf_counter()
            self.player.seek(seconds, "relative", "exact")
        self._action(operation)

    def jump_to_frame(self):
        def operation():
            seconds = frame_time(self.frame_input.get(), self._property("container_fps"),
                                 self._property("duration"))
            self.player.pause = True
            self.pending_since = time.perf_counter()
            self.player.seek(seconds, "absolute", "exact")
            self.surface.focus_set()
        self._action(operation)

    def change_hardware(self):
        try:
            self.player.hwdec = "auto" if self.hardware.get() else "no"
        except MPV_ERRORS as error:
            self.hardware.set(not self.hardware.get())
            self.message.set(f"Could not change decoder: {error}")

    def change_mute(self):
        try:
            self.player.mute = self.muted.get()
        except MPV_ERRORS as error:
            self.muted.set(not self.muted.get())
            self.message.set(f"Could not change mute: {error}")

    def _shortcut(self, action):
        if self.focus_get() is self.frame_entry:
            return None
        action()
        return "break"

    def _poll(self):
        while not self.events.empty():
            kind, detail = self.events.get_nowait()
            if kind == "loaded":
                self._enable_transport(True)
                self.open_button.configure(state="normal")
                if self.pending_since is not None:
                    elapsed_ms = (time.perf_counter() - self.pending_since) * 1000
                    self.pending_since = None
                    self.message.set(f"File loaded: {elapsed_ms:.0f} ms (mpv event + UI polling; not display latency)")
            elif kind == "ready" and self.pending_since is not None:
                elapsed_ms = (time.perf_counter() - self.pending_since) * 1000
                self.pending_since = None
                self.message.set(f"Load/seek ready: {elapsed_ms:.0f} ms (mpv event + UI polling; not display latency)")
            elif kind in ("error", "load-error"):
                self.message.set(detail)
                if kind == "load-error":
                    self._enable_transport(False)
                    self.open_button.configure(state="normal")
        if self.loaded:
            position = self._property("time_pos")
            duration = self._property("duration")
            fps = self._property("container_fps")
            frame = None
            if position is not None and fps is not None and math.isfinite(fps) and fps > 0:
                frame = max(0, round(position * fps))
            count = self._property("estimated_frame_count")
            state = "Paused" if self.player.pause else "Playing"
            timestamp = "—" if position is None else f"{position:.3f} s"
            length = "—" if duration is None else f"{duration:.3f} s"
            frame_label = "—" if frame is None else str(int(frame))
            self.current_frame.set(f"Current frame: {frame_label}")
            count_label = "—" if count is None else str(int(count))
            self.position.set(f"{state}  |  {timestamp} / {length}  |  Frame: {frame_label} (0-based)  |  Estimated count: {count_label}")
            decoder = self._property("hwdec_current") or "no"
            dropped = self._property("frame_drop_count")
            rate = "unknown" if fps is None else f"{fps:.3f}"
            self.diagnostics.set(f"Nominal FPS: {rate}  |  Active hardware decoder: {decoder}  |  Dropped frames: {dropped or 0}")
        self.poll_id = self.after(POLL_MS, self._poll)

    def close(self):
        if self.poll_id is not None:
            self.after_cancel(self.poll_id)
        # Stop native rendering while its parent window is still valid.
        try:
            if self.player is not None:
                self.player.terminate()
        finally:
            self.destroy()


def main():
    try:
        mpv_module = load_mpv()
        app = MpvDemo(mpv_module)
    except (ImportError, *MPV_ERRORS) as error:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("mpv demo setup", f"{error}\n\nSee demos/README.md for Python and libmpv setup.", parent=root)
        root.destroy()
        return
    app.mainloop()


if __name__ == "__main__":
    main()
