"""JPEG frames with GPU scaling/drawing, independent of mpv and annotation code.

Run with uv run demos/gpu_render_demo.py and select an extracted frames folder.
The optional SDL renderer falls back to the existing Pillow/Tk technique.
"""

from collections import OrderedDict, deque
import os
from pathlib import Path
import re
import time

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DISPLAY_SIZE = (1280, 720)
FPS = 25
DECODE_CACHE_FRAMES = 8
GPU_PREFERENCE = "auto"  # "auto" or "tk"; no application settings are changed.
CONTROLS = "Space play/pause | arrows step | digits + Enter jump | Esc close"


def enable_dpi_awareness():
    if os.name == "nt":
        import ctypes
        # Must run before either GUI toolkit creates a window.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))


def frame_paths(folder):
    indexed = []
    for path in Path(folder).glob("frame*.jpg"):
        match = re.fullmatch(r"frame(\d+)\.jpg", path.name)
        if match:
            indexed.append((int(match[1]), path))
    indexed.sort()
    if not indexed or [i for i, _ in indexed] != list(range(len(indexed))):
        raise ValueError("Choose a complete frame0.jpg, frame1.jpg, ... sequence.")
    return [path for _, path in indexed]


def fit_rect(source, target):
    scale = min(target[0] / source[0], target[1] / source[1])
    width, height = max(1, int(source[0] * scale)), max(1, int(source[1] * scale))
    return ((target[0] - width) // 2, (target[1] - height) // 2, width, height)


def decode(path, display_size=DISPLAY_SIZE):
    with Image.open(path) as image:
        # Keep the app's existing JPEG draft optimization in both paths. The
        # GPU receives the draft-sized image and does the remaining scaling.
        _, _, width, height = fit_rect(image.size, display_size)
        image.draft("RGB", (width, height))
        return image.copy() if image.mode == "RGB" else image.convert("RGB")


class TkRenderer:
    """CPU resize + reused PhotoImage, matching the app's display technique."""

    name = "CPU / Pillow + Tk"

    def __init__(self, size=DISPLAY_SIZE):
        import tkinter as tk
        from PIL import ImageTk

        self.ImageTk = ImageTk
        self.size = size
        self.root = tk.Tk()
        self.root.title(self.name)
        self.root.geometry(f"{size[0]}x{size[1]}+40+40")
        self.root.resizable(False, False)
        self.label = tk.Label(self.root, bg="black", borderwidth=0, highlightthickness=0)
        self.label.pack(fill="both", expand=True)
        self.photo = None
        self.keys = deque()
        self.root.bind("<KeyPress>", lambda event: self.keys.append(event.keysym))
        self.root.protocol("WM_DELETE_WINDOW", lambda: self.keys.append("Escape"))
        self.root.update()

    def render(self, image, frame, capture=False):
        x, y, width, height = fit_rect(image.size, self.size)
        resized = image.resize((width, height), Image.Resampling.BILINEAR)
        if (width, height) != self.size:
            canvas = Image.new("RGB", self.size, "black")
            canvas.paste(resized, (x, y))
            resized = canvas
        if self.photo is None:
            self.photo = self.ImageTk.PhotoImage(resized, master=self.root)
            self.label.configure(image=self.photo)
        else:
            self.photo.paste(resized)
        self.root.title(f"{self.name} | frame {frame} | {CONTROLS}")
        self.root.update()
        if capture:
            # Read back Tk's actual image buffer. No desktop capture is needed,
            # so checks also work in sessions that restrict screen capture.
            return self.ImageTk.getimage(self.photo).convert("RGB")

    def events(self):
        self.root.update()
        events = list(self.keys)
        self.keys.clear()
        return events

    def close(self):
        self.photo = None
        self.root.destroy()


class SdlRenderer:
    """Upload CPU-decoded RGB to one reusable texture, scale/draw via SDL."""

    def __init__(self, size=DISPLAY_SIZE):
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import pygame
        from pygame._sdl2.video import Renderer, Texture, Window, get_drivers

        self.pg, self.Texture, self.size = pygame, Texture, size
        self.window = None
        self.texture = None
        try:
            pygame.display.init()
            drivers = list(get_drivers())
            # SDL_RENDERER_ACCELERATED = 2. Explicit request avoids silent CPU mode.
            candidates = [(i, d) for i, d in enumerate(drivers) if d.flags & 2]
            candidates.sort(key=lambda entry: entry[1].name != "direct3d11")
            errors = []
            for index, driver in candidates:
                self.window = Window("TinyTouch GPU JPEG experiment", size=size,
                                     position=(40, 40))
                try:
                    self.renderer = Renderer(self.window, index=index, accelerated=1,
                                             vsync=False)
                except pygame.error as error:
                    errors.append(f"{driver.name}: {error}")
                    self.window.destroy()
                    self.window = None
                    continue
                self.name = f"GPU / SDL {driver.name}"
                self.renderer.draw_color = (0, 0, 0, 255)
                return
            raise RuntimeError("No accelerated SDL renderer: " + "; ".join(errors))
        except (pygame.error, RuntimeError) as error:
            if self.window is not None:
                self.window.destroy()
            pygame.display.quit()
            raise RuntimeError(f"Cannot initialize GPU renderer: {error}") from error

    def render(self, image, frame, capture=False):
        try:
            # The image stays alive until the synchronous texture upload completes.
            pixels = image.tobytes()
            surface = self.pg.image.frombuffer(pixels, image.size, "RGB")
            if self.texture is None or (self.texture.width, self.texture.height) != image.size:
                self.texture = self.Texture(self.renderer, image.size, streaming=True,
                                            scale_quality=1)
            self.texture.update(surface)
            self.renderer.clear()
            self.texture.draw(dstrect=fit_rect(image.size, self.size))
            result = None
            if capture:
                # Readback is for correctness only, never included in timings.
                output = self.renderer.to_surface()
                result = Image.frombytes("RGB", output.get_size(),
                                         self.pg.image.tobytes(output, "RGB"))
            self.renderer.present()
            self.window.title = f"{self.name} | frame {frame} | {CONTROLS}"
            self.pg.event.pump()
            return result
        except self.pg.error as error:
            raise RuntimeError(f"GPU rendering failed: {error}") from error

    def events(self):
        keys = []
        names = {self.pg.K_ESCAPE: "Escape", self.pg.K_SPACE: "space",
                 self.pg.K_LEFT: "Left", self.pg.K_RIGHT: "Right",
                 self.pg.K_RETURN: "Return", self.pg.K_BACKSPACE: "BackSpace"}
        for event in self.pg.event.get():
            if event.type in (self.pg.QUIT, self.pg.WINDOWCLOSE):
                keys.append("Escape")
            elif event.type == self.pg.KEYDOWN:
                keys.append(names.get(event.key, event.unicode))
        return keys

    def close(self):
        self.texture = None
        self.renderer = None
        self.window.destroy()
        self.pg.display.quit()


def create_renderer(preference="auto", size=DISPLAY_SIZE):
    if preference not in ("auto", "gpu", "tk"):
        raise ValueError(f"Unknown renderer preference: {preference}")
    if preference != "tk":
        try:
            return SdlRenderer(size)
        except (ImportError, OSError, RuntimeError) as error:
            if preference == "gpu":
                raise
            print(f"GPU unavailable; using CPU display. Reason: {error}", flush=True)
    return TkRenderer(size)


def main():
    import tkinter as tk
    from tkinter import filedialog

    enable_dpi_awareness()
    chooser = tk.Tk()
    chooser.withdraw()
    folder = filedialog.askdirectory(title="Select extracted JPEG frames", parent=chooser)
    chooser.destroy()
    if not folder:
        return
    paths = frame_paths(folder)
    renderer = create_renderer(GPU_PREFERENCE)
    cache = OrderedDict()
    frame, playing, entry = 0, False, ""
    next_tick = time.perf_counter()

    def show():
        nonlocal renderer
        if frame not in cache:
            cache[frame] = decode(paths[frame])
        cache.move_to_end(frame)
        while len(cache) > DECODE_CACHE_FRAMES:
            cache.popitem(last=False)
        try:
            renderer.render(cache[frame], frame)
        except RuntimeError as error:
            if isinstance(renderer, TkRenderer):
                raise
            print(f"{error}; switching to CPU display.", flush=True)
            renderer.close()
            renderer = TkRenderer()
            renderer.render(cache[frame], frame)

    try:
        show()
        while True:
            for key in renderer.events():
                if key == "Escape":
                    return
                if key == "space":
                    playing = not playing
                    next_tick = time.perf_counter() + 1 / FPS
                elif key in ("Left", "Right"):
                    playing = False
                    frame = max(0, min(len(paths) - 1, frame + (1 if key == "Right" else -1)))
                    show()
                elif key.isascii() and key.isdigit() and len(entry) < 10:
                    entry += key
                    print(f"Jump to frame: {entry}", flush=True)
                elif key == "BackSpace":
                    entry = entry[:-1]
                elif key == "Return" and entry:
                    playing = False
                    frame = max(0, min(len(paths) - 1, int(entry)))
                    entry = ""
                    show()
            now = time.perf_counter()
            if playing and now >= next_tick:
                if frame == len(paths) - 1:
                    playing = False
                else:
                    frame += 1
                    show()
                # Preserve every frame; stall rather than skip when overloaded.
                next_tick = max(next_tick + 1 / FPS, time.perf_counter())
            time.sleep(0.002)
    finally:
        renderer.close()


if __name__ == "__main__":
    main()
