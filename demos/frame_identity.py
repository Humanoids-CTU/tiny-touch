"""Burn frame IDs into a video and compare actual paused JPEG/mpv pixels.

Run: uv run demos/frame_identity.py. Outputs stay in demos/runtime/frame_identity/.
The experiment opens only its own generated video; no annotation projects.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import threading
import time
import tkinter as tk

from PIL import Image, ImageDraw, ImageFont, ImageGrab, ImageStat, ImageTk


ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT = 640, 360
FPS = 25
FRAME_COUNT = 160
KEYFRAME_INTERVAL = 50
MARKER_X, MARKER_Y = 32, 286
CELL_WIDTH, CELL_HEIGHT = 24, 40
MAGIC = 0x5A
REFERENCE_WIDTH, REFERENCE_HEIGHT = 400, 225
SETTLE_TIMEOUT_S = 3
OUTPUT_ROOT = ROOT / "demos" / "runtime" / "frame_identity"


def numbered_frame(index):
    if not 0 <= index < 256:
        raise ValueError("This marker supports frame IDs 0 through 255.")
    image = Image.new("RGB", (WIDTH, HEIGHT), (20, 40, 70))
    draw = ImageDraw.Draw(image)
    draw.text((32, 18), "TinyTouch frame identity • first frame = 0",
              font=ImageFont.load_default(size=23), fill="white")
    draw.text((32, 80), f"FRAME {index:04d}", font=ImageFont.load_default(size=77), fill="white")
    draw.text((32, 190), f"25 FPS   |   time = {index / FPS:.3f} s",
              font=ImageFont.load_default(size=25), fill="white")
    draw.rectangle((32 + index * 3 % 540, 240, 70 + index * 3 % 540, 267), fill="orange")
    payload = (MAGIC << 16) | (index << 8) | (index ^ 0xFF)
    for bit in range(24):
        left = MARKER_X + bit * CELL_WIDTH
        color = "white" if payload & (1 << (23 - bit)) else "black"
        draw.rectangle((left, MARKER_Y, left + CELL_WIDTH - 1,
                        MARKER_Y + CELL_HEIGHT - 1), fill=color)
    return image


def read_marker(image):
    """Read image pixels, rejecting invalid magic, ambiguous cells and checksum."""
    normalized = image.convert("L").resize((WIDTH, HEIGHT), Image.Resampling.BILINEAR)
    payload = 0
    for bit in range(24):
        x = MARKER_X + bit * CELL_WIDTH + CELL_WIDTH // 2
        y = MARKER_Y + CELL_HEIGHT // 2
        value = ImageStat.Stat(normalized.crop((x - 2, y - 2, x + 3, y + 3))).mean[0]
        if 70 < value < 185:
            raise ValueError("Ambiguous marker cell; screenshot cannot establish frame identity.")
        payload = (payload << 1) | int(value >= 185)
    magic, frame, checksum = payload >> 16, (payload >> 8) & 0xFF, payload & 0xFF
    if magic != MAGIC or checksum != (frame ^ 0xFF):
        raise ValueError("Invalid marker magic/checksum; video may be obscured or not rendered.")
    return frame


def prepare(folder):
    import imageio_ffmpeg

    sys.path.insert(0, str(ROOT / "src"))
    from adapters.frame_extractor import _extract_frames_ffmpeg

    video = folder / "numbered_25fps.mp4"
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-f", "rawvideo",
               "-pixel_format", "rgb24", "-video_size", f"{WIDTH}x{HEIGHT}",
               "-framerate", str(FPS), "-i", "-", "-an", "-c:v", "libx264",
               "-crf", "18", "-pix_fmt", "yuv420p", "-g", str(KEYFRAME_INTERVAL),
               "-keyint_min", str(KEYFRAME_INTERVAL), "-sc_threshold", "0", "-bf", "3",
               "-x264-params", "open-gop=0", str(video)]
    with (folder / "encode.log").open("w") as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        try:
            for index in range(FRAME_COUNT):
                frame = numbered_frame(index)
                assert read_marker(frame) == index
                process.stdin.write(frame.tobytes())
            process.stdin.close()
            if process.wait(timeout=30) != 0:
                raise RuntimeError("Video encoding failed; see encode.log")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    frames = folder / "frames"
    frames.mkdir()
    if not _extract_frames_ffmpeg(str(video), str(frames), None, 0.1):
        raise RuntimeError("Production ffmpeg extractor was unavailable")
    files = list(frames.glob("frame*.jpg"))
    assert len(files) == FRAME_COUNT, f"Expected {FRAME_COUNT} JPEGs, got {len(files)}"
    for index in range(FRAME_COUNT):
        with Image.open(frames / f"frame{index}.jpg") as image:
            assert read_marker(image) == index, f"Extraction shifted frame {index}"
    # Independent negative control: the oracle must reject a one-frame mismatch.
    assert read_marker(numbered_frame(43)) != 42
    return video, frames


def sleep_for(seconds):
    deadline = time.perf_counter() + seconds
    return lambda: time.perf_counter() >= deadline


class Experiment:
    def __init__(self, folder, video, frames):
        from mpv_demo import MpvDemo, load_mpv
        from adapters.frame_buffer import BufferContext, FrameBuffer

        self.folder, self.video, self.frames = folder, video, frames
        self.app = MpvDemo(load_mpv())
        self.app.geometry("760x650+20+40")
        self.app.title("mpv — frame identity experiment")
        self.reference = tk.Toplevel(self.app)
        self.reference.title("Existing JPEG player — frame reference")
        self.reference.geometry("400x270+800+40")
        self.reference.resizable(False, False)
        self.caption = tk.StringVar(value="JPEG reference")
        tk.Label(self.reference, textvariable=self.caption).pack()
        self.reference_surface = tk.Frame(self.reference, width=REFERENCE_WIDTH,
                                          height=REFERENCE_HEIGHT, bg="black")
        self.reference_surface.pack()
        self.reference_surface.pack_propagate(False)
        self.reference_label = tk.Label(self.reference_surface, bg="black", bd=0, padx=0, pady=0)
        self.reference_label.pack(expand=True)
        self.target = 0
        self.direction = 1
        self.shown = None
        self.photo = None
        self.painted = None
        self.buffer = FrameBuffer(get_buffer_context=lambda: BufferContext(
            str(frames), self.target, FRAME_COUNT - 1, REFERENCE_WIDTH,
            REFERENCE_HEIGHT, 1.0, 5 * FPS, self.direction))
        self.thread = threading.Thread(target=self.buffer.background_update, daemon=True)
        self.thread.start()
        self.result = {"video": str(video), "fps": FPS, "frames": FRAME_COUNT,
                       "encoding": "H.264, fixed keyframe interval 50, three B-frames, closed GOP",
                       "extracted_jpegs_checked": FRAME_COUNT, "negative_control_detected": True,
                       "checks": [], "failures": [], "error": None}
        self.generator = self.run()
        self.wait = None
        self.wait_since = None
        self.app.report_callback_exception = self.callback_error
        self.app.protocol("WM_DELETE_WINDOW", lambda: self.finish("Experiment interrupted"))

    def callback_error(self, kind, value, traceback):
        self.finish(f"Tk callback: {kind.__name__}: {value}")

    def paint_reference(self):
        image = self.buffer.get(self.target)
        if image is None or image is self.shown:
            return
        if self.photo is None:
            self.photo = ImageTk.PhotoImage(image, master=self.reference)
            self.reference_label.configure(image=self.photo)
        else:
            self.photo.paste(image)
        self.shown = image
        self.painted = self.target
        self.caption.set(f"JPEG frame {self.target}")

    def set_reference(self, target):
        self.direction = -1 if target < self.target else 1
        self.target = target
        self.buffer.request_priority(target)
        self.paint_reference()

    @staticmethod
    def grab_video(widget):
        # main() makes this experiment DPI-aware before creating any windows,
        # so Tk coordinates and desktop-capture coordinates are physical pixels.
        # PrintWindow/HWND capture cannot capture this D3D video surface.
        width, height = widget.winfo_width(), widget.winfo_height()
        scale = min(width / WIDTH, height / HEIGHT)
        video_width, video_height = round(WIDTH * scale), round(HEIGHT * scale)
        x = widget.winfo_rootx() + (width - video_width) // 2
        y = widget.winfo_rooty() + (height - video_height) // 2
        return ImageGrab.grab(bbox=(x, y, x + video_width, y + video_height), all_screens=sys.platform == "win32")

    def observe(self):
        captures = {"jpeg": self.grab_video(self.reference_surface),
                    "mpv": self.grab_video(self.app.surface)}
        observed = {}
        for name, image in captures.items():
            try:
                observed[name] = read_marker(image)
            except ValueError as error:
                observed[name] = str(error)
        observed["counter"] = self.app.current_frame.get()
        observed["native_frame"] = round((self.app.player.time_pos or 0) * FPS)
        return observed, captures

    def logical_ready(self, target):
        position = self.app.player.time_pos
        return (self.painted == target and position is not None
                and round(position * FPS) == target and not self.app.player.seeking)

    def check(self, name, target, since):
        yield lambda: self.logical_ready(target)
        first, _ = self.observe()
        record = {"action": name, "expected": target, "first_ready_pixels": first,
                  "first_ready_ms": (time.perf_counter() - since) * 1000}
        # Counter polling is independent of seek completion. Wait for stable
        # paused output, but retain the first-ready observation to expose races.
        yield sleep_for(0.15)
        observed, images = self.observe()
        record["settled_pixels"] = observed
        record["passed"] = (observed["jpeg"] == target and observed["mpv"] == target
                            and observed["counter"] == f"Current frame: {target}")
        if record["passed"]:
            yield sleep_for(0.10)
            stable, _ = self.observe()
            record["stable_pixels"] = stable
            record["passed"] = stable["mpv"] == target and stable["jpeg"] == target
        self.result["checks"].append(record)
        if not record["passed"]:
            self.result["failures"].append(name)
        if target in (0, 49, 50, 100, FRAME_COUNT - 1) or not record["passed"]:
            for player, image in images.items():
                image.save(self.folder / f"{len(self.result['checks']):02d}_{name}_{player}.png")
        print(f"{name}: expected {target}, pixels JPEG={observed['jpeg']}, mpv={observed['mpv']}, counter={observed['counter']}", flush=True)

    def jump(self, target):
        self.set_reference(target)
        self.app.frame_input.set(str(target))
        self.app.jump_button.invoke()

    def run(self):
        self.app.open_video(self.video)
        self.app.lift()
        self.reference.lift()
        yield lambda: self.app.loaded and self.logical_ready(0)
        yield sleep_for(0.3)
        yield from self.check("open", 0, time.perf_counter())
        for target in (1, 49, 50, 51, 99, 100, 101, 159, 0):
            since = time.perf_counter()
            self.jump(target)
            yield from self.check(f"jump_{target}", target, since)
        self.jump(49)
        yield lambda: self.logical_ready(49)
        for direction in (1, 1, -1, -1):
            target = round(self.app.player.time_pos * FPS) + direction
            self.set_reference(target)
            since = time.perf_counter()
            self.app.step(direction)
            yield from self.check(f"step_{direction}_{target}", target, since)
        rng = random.Random(7)
        for index in range(6):
            target = rng.randrange(FRAME_COUNT)
            since = time.perf_counter()
            self.jump(target)
            yield from self.check(f"random_{index}_{target}", target, since)
        since = time.perf_counter()
        for target in (150, 2, 75):
            self.jump(target)
            yield sleep_for(0.01)
        yield from self.check("rapid_jumps_last_wins", 75, since)
        self.jump(0)
        yield lambda: self.logical_ready(0)
        self.app.step(-1)
        yield from self.check("previous_at_first", 0, time.perf_counter())
        self.jump(FRAME_COUNT - 1)
        yield lambda: self.logical_ready(FRAME_COUNT - 1)
        self.app.step(1)
        yield from self.check("next_at_last", FRAME_COUNT - 1, time.perf_counter())
        for index in range(3):
            self.jump(10 + index * 20)
            yield lambda: self.logical_ready(10 + index * 20)
            self.app.toggle_play()
            yield sleep_for(0.35)
            self.app.toggle_play()
            yield sleep_for(0.1)
            target = round(self.app.player.time_pos * FPS)
            self.set_reference(target)
            yield from self.check(f"pause_{index}", target, time.perf_counter())

    def tick(self):
        try:
            self.paint_reference()
            if self.wait is None or self.wait():
                self.wait = next(self.generator)
                self.wait_since = time.perf_counter()
            elif time.perf_counter() - self.wait_since > SETTLE_TIMEOUT_S:
                raise TimeoutError(f"Frame did not become ready; target={self.target}, position={self.app.player.time_pos}")
        except StopIteration:
            self.finish()
            return
        except Exception as error:
            self.finish(repr(error))
            return
        self.app.after(10, self.tick)

    def finish(self, error=None):
        self.result["error"] = error
        self.result["decoder"] = self.app.player.hwdec_current
        self.result["mpv_version"] = self.app.player.mpv_version
        self.result["passed"] = error is None and not self.result["failures"] and bool(self.result["checks"])
        self.result["video_sha256"] = hashlib.sha256(self.video.read_bytes()).hexdigest()
        (self.folder / "results.json").write_text(json.dumps(self.result, indent=2), encoding="utf-8")
        self.buffer.shutdown(wait=True)
        self.thread.join(timeout=3)
        self.reference.destroy()
        self.app.close()


def main():
    if sys.platform == "win32":
        import ctypes
        if not ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            raise RuntimeError("Cannot enable per-monitor DPI awareness for reliable pixel capture")
    folder = OUTPUT_ROOT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder.mkdir(parents=True)
    video, frames = prepare(folder)
    print(f"Validated all {FRAME_COUNT} extracted frame IDs. Starting visible pixel comparison.", flush=True)
    experiment = Experiment(folder, video, frames)
    experiment.app.after(10, experiment.tick)
    experiment.app.mainloop()
    print(f"RESULTS: {folder}\nPASSED: {experiment.result['passed']}", flush=True)
    raise SystemExit(0 if experiment.result["passed"] else 1)


if __name__ == "__main__":
    main()
