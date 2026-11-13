"""Rebuild the content of a visible window without showing half-built frames.

``swap_content(widget, build)`` runs ``build`` (which destroys and recreates
widgets inside ``widget``'s window) behind a still picture of the window:

1. snapshot the window's client area (one BitBlt, a few ms);
2. show the snapshot in a borderless, click-through, non-activating layered
   window exactly over the client area (UpdateLayeredWindow: atomic, no paint).
   Windows 11's rounded bottom corners stay see-through;
3. run ``build`` and settle (``window_reveal.settle``); with a ``ready``
   predicate, keep running the event loop until it is true or times out;
4. GdiFlush, then destroy the cover: the compositor's next frame shows the
   finished window.

The window underneath keeps focus, grab and bindings; nothing in Tk knows
about the cover. If any other window of the thread is activated while the
cover is up (a dialog or message box opened from the build or from an event
handled while settling), the cover is hidden at once, so it never hides the
window behind a modal. There is no cover when the window is not on screen yet, is
still waiting for its reveal, or a swap is already running (a nested swap
only rebuilds). Off Windows, or if any Win32 call fails, the build simply runs
and settles. Windows whose size changes during the build are covered only
over their old area.
"""
import _tkinter
import ctypes
import logging
import sys
import time
from tkinter import TclError

import numpy as np

from gui import window_reveal

logger = logging.getLogger(__name__)

SWAP_COVER = True            # False: rebuild in place, without a cover
SWAP_SETTLE_BUDGET_MS = 1000  # never hold the cover longer than this while settling
SWAP_READY_TIMEOUT_MS = 2000  # default wait for a ``ready`` predicate
# Windows 11 rounds a window's bottom corners (8 px at 96 dpi); the cover leaves
# that much of each bottom corner see-through so the rounding stays visible.
CORNER_PX = 8

IS_WINDOWS = sys.platform == "win32"
_active = False              # a swap is running (a nested one only rebuilds)


def swap_content(widget, build, *, ready=None, timeout_ms=SWAP_READY_TIMEOUT_MS, from_screen=False):
    """Run ``build()`` so that ``widget``'s window shows only the old or the new content.

    ``ready``, if given, is a predicate for work that settling does not wait
    for (a frame painted from a timer, say): the cover stays until it returns
    True or ``timeout_ms`` has passed (without a cover there is nothing to
    hold, so it is not waited for), or until the cover was dropped because
    another window was activated. ``build`` and ``ready`` exceptions propagate
    after the cover is removed. Returns what ``build`` returns.

    ``from_screen`` copies the cover from the screen instead of the window's
    own surface: it then includes GPU-drawn content (the video, which the
    window surface lacks) and windows floating above (a drag preview that
    ``build`` closes). Anything else overlapping the window is frozen in too,
    so use it only for the main window during its own interaction.
    """
    global _active
    window = widget.winfo_toplevel()
    if _active or not window.winfo_viewable() or window_reveal.is_pending(window):
        return build()
    _active = True
    cover = _Cover.over(window, from_screen) if SWAP_COVER and IS_WINDOWS and _opaque(window) else None
    try:
        result = build()
        if window.winfo_exists():
            window_reveal.settle(window, SWAP_SETTLE_BUDGET_MS)
            if cover is not None and ready is not None:
                _wait_until(window, lambda: ready() or not cover.showing, timeout_ms)
        return result
    finally:
        _active = False
        if cover is not None:
            cover.close()


def _wait_until(window, ready, timeout_ms):
    """Run every kind of event (timers too) until ``ready()`` or the timeout, then settle."""
    deadline = time.perf_counter() + timeout_ms / 1000
    while not ready() and time.perf_counter() < deadline:
        if not window.tk.dooneevent(_tkinter.ALL_EVENTS | _tkinter.DONT_WAIT):
            time.sleep(0.001)
    if window.winfo_exists():
        window_reveal.settle(window, SWAP_SETTLE_BUDGET_MS)


def _opaque(window):
    """A transparent window (alpha < 1, e.g. hidden by a test) has nothing to cover."""
    try:
        return float(window.attributes("-alpha")) >= 1.0
    except (ValueError, TclError):
        return True


# --- Win32 cover ----------------------------------------------------------------
_WS_POPUP = 0x80000000
_WS_EX_LAYERED, _WS_EX_TRANSPARENT = 0x80000, 0x20
_WS_EX_TOOLWINDOW, _WS_EX_NOACTIVATE = 0x80, 0x08000000
_ULW_ALPHA = 0x2
_AC_SRC_ALPHA = 0x1
_SW_SHOWNOACTIVATE = 4
_SW_HIDE = 0
_WH_CBT = 5
_HCBT_ACTIVATE = 5
_SRCCOPY = 0x00CC0020
_GA_ROOT = 2
_CLASS_NAME = "TinyTouchSwapCover"
_api = None
_HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t) if IS_WINDOWS else None


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("style", ctypes.c_uint), ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", ctypes.c_void_p),
                ("hIcon", ctypes.c_void_p), ("hCursor", ctypes.c_void_p), ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", ctypes.c_wchar_p), ("lpszClassName", ctypes.c_wchar_p), ("hIconSm", ctypes.c_void_p)]


def _win32():
    """user32/gdi32/dwmapi with 64-bit-safe signatures, and the cover's window class."""
    global _api
    if _api is not None:
        return _api
    from ctypes import wintypes as w
    handle = ctypes.c_void_p
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32")
    dwm = ctypes.WinDLL("dwmapi")
    kernel32 = ctypes.WinDLL("kernel32")
    for fn, res, args in (
        (user32.GetAncestor, handle, [handle, w.UINT]),
        (user32.GetWindowRect, w.BOOL, [handle, ctypes.POINTER(_RECT)]),
        (user32.GetDC, handle, [handle]),
        (user32.ReleaseDC, ctypes.c_int, [handle, handle]),
        (user32.RegisterClassExW, w.ATOM, [ctypes.POINTER(_WNDCLASSEXW)]),
        (user32.CreateWindowExW, handle, [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_int, handle, handle, handle, handle]),
        (user32.UpdateLayeredWindow, w.BOOL, [handle, handle, ctypes.POINTER(_POINT), ctypes.POINTER(_SIZE),
                                              handle, ctypes.POINTER(_POINT), w.DWORD,
                                              ctypes.POINTER(_BLENDFUNCTION), w.DWORD]),
        (user32.GetDpiForWindow, w.UINT, [handle]),
        (user32.ShowWindow, w.BOOL, [handle, ctypes.c_int]),
        (user32.DestroyWindow, w.BOOL, [handle]),
        (gdi32.CreateCompatibleDC, handle, [handle]),
        (gdi32.CreateDIBSection, handle, [handle, ctypes.POINTER(_BITMAPINFOHEADER), w.UINT,
                                          ctypes.POINTER(ctypes.c_void_p), handle, w.DWORD]),
        (gdi32.SelectObject, handle, [handle, handle]),
        (gdi32.BitBlt, w.BOOL, [handle, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                handle, ctypes.c_int, ctypes.c_int, w.DWORD]),
        (gdi32.DeleteObject, w.BOOL, [handle]),
        (gdi32.DeleteDC, w.BOOL, [handle]),
        (gdi32.GdiFlush, w.BOOL, []),
        (dwm.DwmFlush, ctypes.c_long, []),
        (kernel32.GetModuleHandleW, handle, [w.LPCWSTR]),
        (user32.SetWindowsHookExW, handle, [ctypes.c_int, _HOOKPROC, handle, w.DWORD]),
        (user32.UnhookWindowsHookEx, w.BOOL, [handle]),
        (user32.CallNextHookEx, ctypes.c_ssize_t, [handle, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t]),
    ):
        fn.restype, fn.argtypes = res, args
    instance = kernel32.GetModuleHandleW(None)
    wndclass = _WNDCLASSEXW(ctypes.sizeof(_WNDCLASSEXW), 0,
                            ctypes.cast(user32.DefWindowProcW, ctypes.c_void_p).value, 0, 0, instance,
                            None, None, None, None, _CLASS_NAME, None)
    user32.RegisterClassExW(ctypes.byref(wndclass))   # fails harmlessly if already registered
    _api = (user32, gdi32, dwm, instance)
    return _api


class _Cover:
    """A still copy of a window's client area, shown over it until ``close``."""

    def __init__(self, window, from_screen=False):
        user32, gdi32, dwm, instance = _win32()
        client = window.winfo_id()   # Tk's client child: exactly the toplevel's area
        rect = _RECT()
        user32.GetWindowRect(client, ctypes.byref(rect))
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width <= 0 or height <= 0:
            raise OSError("window has no area")
        self.hwnd = self.memdc = self.bitmap = self.old = self.hook = None
        self.showing = False
        if from_screen:
            dwm.DwmFlush()   # the latest change (a preview just moved) has been composed
        source_window = None if from_screen else client   # None: the screen
        source = user32.GetDC(source_window)
        x, y = (rect.left, rect.top) if from_screen else (0, 0)
        try:
            self.memdc = gdi32.CreateCompatibleDC(source)
            header = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
            bits = ctypes.c_void_p()
            self.bitmap = gdi32.CreateDIBSection(self.memdc, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
            if not self.bitmap:
                raise OSError("CreateDIBSection failed")
            self.old = gdi32.SelectObject(self.memdc, self.bitmap)
            if not gdi32.BitBlt(self.memdc, 0, 0, width, height, source, x, y, _SRCCOPY):
                raise OSError("BitBlt failed")
        finally:
            user32.ReleaseDC(source_window, source)
        gdi32.GdiFlush()
        # Opaque everywhere (GDI leaves alpha 0) except the bottom corners.
        pixels = np.ctypeslib.as_array(ctypes.cast(bits, ctypes.POINTER(ctypes.c_ubyte)), (height, width, 4))
        pixels[..., 3] = 255
        corner = min(width, height, -(-CORNER_PX * user32.GetDpiForWindow(client) // 96))
        pixels[height - corner:, :corner] = 0       # premultiplied: transparent
        pixels[height - corner:, width - corner:] = 0
        owner = self.owner = user32.GetAncestor(client, _GA_ROOT)   # owned: stays just above the window
        self.hwnd = user32.CreateWindowExW(
            _WS_EX_LAYERED | _WS_EX_TRANSPARENT | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE,
            _CLASS_NAME, None, _WS_POPUP, rect.left, rect.top, width, height, owner, None, instance, None)
        if not self.hwnd:
            self.close()
            raise OSError(f"CreateWindowEx failed ({ctypes.get_last_error()})")
        position, size, origin = _POINT(rect.left, rect.top), _SIZE(width, height), _POINT(0, 0)
        if not user32.UpdateLayeredWindow(self.hwnd, None, ctypes.byref(position), ctypes.byref(size),
                                          self.memdc, ctypes.byref(origin), 0,
                                          ctypes.byref(_BLENDFUNCTION(0, 0, 255, _AC_SRC_ALPHA)), _ULW_ALPHA):
            self.close()
            raise OSError(f"UpdateLayeredWindow failed ({ctypes.get_last_error()})")
        user32.ShowWindow(self.hwnd, _SW_SHOWNOACTIVATE)
        self.showing = True
        # Thread-local CBT hook: drop the cover when another window activates.
        self._hook_proc = _HOOKPROC(self._on_cbt)
        thread_id = ctypes.WinDLL("kernel32").GetCurrentThreadId()
        self.hook = user32.SetWindowsHookExW(_WH_CBT, self._hook_proc, None, thread_id)
        if not self.hook:
            logger.debug("swap cover: no activation hook (%s)", ctypes.get_last_error())
        dwm.DwmFlush()   # the cover is on screen before the first change is drawn

    def _on_cbt(self, code, wparam, lparam):
        try:
            if code == _HCBT_ACTIVATE and self.showing and wparam not in (self.owner, self.hwnd):
                self.hide()
        except Exception:   # never let an error escape into a Win32 callback
            logger.debug("swap cover: activation hook failed", exc_info=True)
        return _win32()[0].CallNextHookEx(None, code, wparam, lparam)

    def hide(self):
        """Take the cover off the screen now (the window underneath shows as it is)."""
        self.showing = False
        if self.hwnd:
            _win32()[0].ShowWindow(self.hwnd, _SW_HIDE)

    @classmethod
    def over(cls, window, from_screen=False):
        try:
            return cls(window, from_screen)
        except (OSError, AttributeError, ValueError):
            logger.debug("swap cover unavailable; rebuilding in place", exc_info=True)
            return None

    def close(self):
        user32, gdi32, _, _ = _win32()
        gdi32.GdiFlush()   # Tk's drawing has reached the window before the cover goes
        self.showing = False
        if self.hook:
            user32.UnhookWindowsHookEx(self.hook)
            self.hook = None
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None
        if self.memdc:
            if self.old:
                gdi32.SelectObject(self.memdc, self.old)
            gdi32.DeleteDC(self.memdc)
            self.memdc = None
        if self.bitmap:
            gdi32.DeleteObject(self.bitmap)
            self.bitmap = None
