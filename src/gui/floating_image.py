"""A picture floating over a Tk window, drawn outside Tk (Windows only).

``FloatingImage(window)`` is a borderless, click-through, non-activating
layered window owned by ``window``'s toplevel. ``show(image, x, y)`` puts an
opaque PIL image at screen position ``x, y`` in one UpdateLayeredWindow call:
position, size and pixels change together, without a paint and without any Tk
layout. Used for drag previews that would be too slow to do with real widgets
(the diagram resize grip). ``grab(widget)`` copies what a widget shows on
screen as a PIL image.

``available()`` is False off Windows or when a Win32 call fails; callers then
fall back to updating the widgets directly.
"""
import ctypes
import logging
import sys

import numpy as np
from PIL import Image

from gui import content_swap
from gui.content_swap import _BITMAPINFOHEADER, _BLENDFUNCTION, _POINT, _RECT, _SIZE

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
_SRCCOPY = 0x00CC0020
_GA_ROOT = 2
_SW_SHOWNOACTIVATE = 4
_ULW_ALPHA = 0x2
_AC_SRC_ALPHA = 0x1
_WS_POPUP = 0x80000000
_WS_EX_LAYERED, _WS_EX_TRANSPARENT = 0x80000, 0x20
_WS_EX_TOOLWINDOW, _WS_EX_NOACTIVATE = 0x80, 0x08000000


def available():
    if not IS_WINDOWS:
        return False
    try:
        content_swap._win32()
        return True
    except (OSError, AttributeError):
        return False


def _dib(gdi32, memdc, width, height):
    """A top-down 32-bit DIB section selected into ``memdc``: (bitmap, BGRA array)."""
    header = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(memdc, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
    if not bitmap:
        raise OSError("CreateDIBSection failed")
    pixels = np.ctypeslib.as_array(ctypes.cast(bits, ctypes.POINTER(ctypes.c_ubyte)), (height, width, 4))
    return bitmap, pixels


def grab(widget):
    """What ``widget`` currently shows, as an RGB PIL image (from its toplevel's surface)."""
    user32, gdi32, _, _ = content_swap._win32()
    window = widget.winfo_toplevel()
    client = window.winfo_id()
    rect = _RECT()
    user32.GetWindowRect(client, ctypes.byref(rect))
    x, y = widget.winfo_rootx() - rect.left, widget.winfo_rooty() - rect.top
    width, height = widget.winfo_width(), widget.winfo_height()
    source = user32.GetDC(client)
    memdc = gdi32.CreateCompatibleDC(source)
    bitmap = old = None
    try:
        bitmap, pixels = _dib(gdi32, memdc, width, height)
        old = gdi32.SelectObject(memdc, bitmap)
        if not gdi32.BitBlt(memdc, 0, 0, width, height, source, x, y, _SRCCOPY):
            raise OSError("BitBlt failed")
        gdi32.GdiFlush()
        return Image.fromarray(pixels[..., 2::-1].copy(), "RGB")   # BGRA -> RGB
    finally:
        if old:
            gdi32.SelectObject(memdc, old)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memdc)
        user32.ReleaseDC(client, source)


class FloatingImage:
    """A click-through picture over ``window``; ``show`` moves/resizes/repaints it atomically."""

    def __init__(self, window):
        user32, gdi32, _, instance = content_swap._win32()
        self._owner = user32.GetAncestor(window.winfo_toplevel().winfo_id(), _GA_ROOT)
        self._memdc = gdi32.CreateCompatibleDC(None)
        self.hwnd = user32.CreateWindowExW(
            _WS_EX_LAYERED | _WS_EX_TRANSPARENT | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE,
            content_swap._CLASS_NAME, None, _WS_POPUP, 0, 0, 1, 1, self._owner, None, instance, None)
        if not self.hwnd:
            gdi32.DeleteDC(self._memdc)
            raise OSError(f"CreateWindowEx failed ({ctypes.get_last_error()})")
        self.showing = False

    def show(self, image, x, y, opacity=1.0):
        """Show the PIL ``image`` (alpha respected) with its top-left at screen ``x, y``.

        ``opacity`` (0..1) fades the whole picture on top of its own alpha.
        """
        user32, gdi32, _, _ = content_swap._win32()
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint16)
        height, width = rgba.shape[:2]
        bitmap, pixels = _dib(gdi32, self._memdc, width, height)
        old = gdi32.SelectObject(self._memdc, bitmap)
        try:
            alpha = rgba[..., 3]
            for channel in range(3):   # UpdateLayeredWindow wants premultiplied BGRA
                pixels[..., 2 - channel] = rgba[..., channel] * alpha // 255
            pixels[..., 3] = alpha
            constant = max(0, min(255, round(255 * opacity)))
            position, size, origin = _POINT(int(x), int(y)), _SIZE(width, height), _POINT(0, 0)
            if not user32.UpdateLayeredWindow(self.hwnd, None, ctypes.byref(position), ctypes.byref(size),
                                              self._memdc, ctypes.byref(origin), 0,
                                              ctypes.byref(_BLENDFUNCTION(0, 0, constant, _AC_SRC_ALPHA)),
                                              _ULW_ALPHA):
                raise OSError(f"UpdateLayeredWindow failed ({ctypes.get_last_error()})")
        finally:
            gdi32.SelectObject(self._memdc, old)
            gdi32.DeleteObject(bitmap)
        if not self.showing:
            user32.ShowWindow(self.hwnd, _SW_SHOWNOACTIVATE)
            self.showing = True

    def close(self):
        user32, gdi32, _, _ = content_swap._win32()
        self.showing = False
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None
        if self._memdc:
            gdi32.DeleteDC(self._memdc)
            self._memdc = None
