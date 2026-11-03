"""GPU drawing in a Tk-owned native child window; all calls stay on Tk's thread.

SDL wraps the child handle without owning it. JPEG decoding stays in FrameBuffer;
the controller retains the existing PhotoImage path when this surface is absent.
"""

import ctypes
import importlib
import tkinter as tk

from PIL import Image


class VideoRendererError(RuntimeError):
    """Acceleration is unavailable or a native drawing operation failed."""


class GpuVideoSurface:
    def __init__(self, parent, on_failure):
        self.widget = tk.Frame(parent, bg="black", borderwidth=0, takefocus=0)
        self.sdl = None
        self.window = None
        self.renderer = None
        self.texture = None
        self.texture_size = None
        self._initialized = False
        self._closed = False
        self._redraw_id = None
        self._last_image = None
        self._downscale = 1.0
        self.on_failure = on_failure
        self.name = "GPU"
        try:
            self.sdl = importlib.import_module("sdl2")
            sdl = self.sdl
            self.widget.pack(fill="both", expand=True)
            parent.update_idletasks()  # Realize Tk's native child before wrapping it.
            self._check(sdl.SDL_InitSubSystem(sdl.SDL_INIT_VIDEO))
            self._initialized = True
            self.window = sdl.SDL_CreateWindowFrom(ctypes.c_void_p(self.widget.winfo_id()))
            if not self.window:
                raise VideoRendererError(self._error())
            drivers = []
            for index in range(sdl.SDL_GetNumRenderDrivers()):
                info = sdl.SDL_RendererInfo()
                if sdl.SDL_GetRenderDriverInfo(index, ctypes.byref(info)) == 0:
                    if info.flags & sdl.SDL_RENDERER_ACCELERATED:
                        drivers.append((index, info.name.decode("utf-8", errors="replace")))
            drivers.sort(key=lambda entry: entry[1] != "direct3d11")
            for index, _ in drivers:
                self.renderer = sdl.SDL_CreateRenderer(
                    self.window, index, sdl.SDL_RENDERER_ACCELERATED)
                if self.renderer:
                    break
            if not self.renderer:
                raise VideoRendererError(self._error())
            info = sdl.SDL_RendererInfo()
            self._check(sdl.SDL_GetRendererInfo(self.renderer, ctypes.byref(info)))
            if not info.flags & sdl.SDL_RENDERER_ACCELERATED:
                raise VideoRendererError("SDL selected a software renderer")
            self.name = info.name.decode("utf-8", errors="replace")
            self._check(sdl.SDL_SetRenderDrawColor(self.renderer, 0, 0, 0, 255))
            self.widget.bind("<Expose>", self._schedule_redraw)
            self.widget.bind("<Configure>", self._schedule_redraw)
        except (ImportError, OSError, RuntimeError, tk.TclError):
            self.close()
            raise

    def _error(self):
        return self.sdl.SDL_GetError().decode("utf-8", errors="replace") or "GPU unavailable"

    def _check(self, code):
        if code < 0:
            raise VideoRendererError(self._error())

    def _draw(self):
        sdl = self.sdl
        width, height = ctypes.c_int(), ctypes.c_int()
        self._check(sdl.SDL_GetRendererOutputSize(
            self.renderer, ctypes.byref(width), ctypes.byref(height)))
        scale = min(width.value / self.texture_size[0], height.value / self.texture_size[1])
        scale /= self._downscale
        draw_w = max(1, int(self.texture_size[0] * scale))
        draw_h = max(1, int(self.texture_size[1] * scale))
        self.draw_rect = sdl.SDL_Rect((width.value - draw_w) // 2,
                                     (height.value - draw_h) // 2, draw_w, draw_h)
        self._check(sdl.SDL_RenderSetViewport(self.renderer, None))
        self._check(sdl.SDL_RenderClear(self.renderer))
        self._check(sdl.SDL_RenderCopy(self.renderer, self.texture, None,
                                       ctypes.byref(self.draw_rect)))

    def show(self, image, downscale=1.0):
        if self._closed:
            raise VideoRendererError("GPU surface is closed")
        sdl = self.sdl
        if image.mode != "RGB":
            image = image.convert("RGB")
        if self.texture_size != image.size:
            if self.texture:
                sdl.SDL_DestroyTexture(self.texture)
            self.texture = sdl.SDL_CreateTexture(self.renderer, sdl.SDL_PIXELFORMAT_RGB24,
                                                 sdl.SDL_TEXTUREACCESS_STREAMING, *image.size)
            if not self.texture:
                raise VideoRendererError(self._error())
            self.texture_size = image.size
            self._check(sdl.SDL_SetTextureScaleMode(self.texture, sdl.SDL_ScaleModeLinear))
        pixels = image.tobytes()
        pointer = ctypes.cast(ctypes.c_char_p(pixels), ctypes.c_void_p)
        self._check(sdl.SDL_UpdateTexture(self.texture, None, pointer, image.width * 3))
        self._downscale = downscale
        self._draw()
        sdl.SDL_RenderPresent(self.renderer)
        # Tk owns navigation and window events. Discard SDL's duplicate event
        # queue so it cannot accumulate while this app runs for many hours.
        sdl.SDL_PumpEvents()
        if sdl.SDL_HasEvent(sdl.SDL_RENDER_DEVICE_RESET) or sdl.SDL_HasEvent(sdl.SDL_RENDER_TARGETS_RESET):
            raise VideoRendererError("Graphics device was reset")
        sdl.SDL_FlushEvents(sdl.SDL_FIRSTEVENT, sdl.SDL_LASTEVENT)
        self._last_image = image

    def _schedule_redraw(self, event):
        if not self._closed and self._last_image is not None and self._redraw_id is None:
            self._redraw_id = self.widget.after_idle(self._redraw)

    def _redraw(self):
        self._redraw_id = None
        if self._closed or self._last_image is None:
            return
        try:
            self._draw()
            self.sdl.SDL_RenderPresent(self.renderer)
        except VideoRendererError as error:
            self.on_failure(error)

    def capture_frame(self):
        """Read rendered frame pixels for acceptance tests, excluding letterboxing."""
        self._draw()
        rect = self.draw_rect
        pixels = ctypes.create_string_buffer(rect.w * rect.h * 3)
        self._check(self.sdl.SDL_RenderReadPixels(
            self.renderer, ctypes.byref(rect), self.sdl.SDL_PIXELFORMAT_RGB24,
            pixels, rect.w * 3))
        self.sdl.SDL_RenderPresent(self.renderer)
        return Image.frombytes("RGB", (rect.w, rect.h), pixels.raw)

    def clear(self):
        self._last_image = None
        self._check(self.sdl.SDL_RenderClear(self.renderer))
        self.sdl.SDL_RenderPresent(self.renderer)

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._redraw_id is not None:
            self.widget.after_cancel(self._redraw_id)
            self._redraw_id = None
        if self.texture:
            self.sdl.SDL_DestroyTexture(self.texture)
            self.texture = None
        if self.renderer:
            self.sdl.SDL_DestroyRenderer(self.renderer)
            self.renderer = None
        if self.window:
            self.sdl.SDL_DestroyWindow(self.window)
            self.window = None
        if self._initialized:
            self.sdl.SDL_QuitSubSystem(self.sdl.SDL_INIT_VIDEO)
            self._initialized = False
        self._last_image = None
        self.widget.destroy()
