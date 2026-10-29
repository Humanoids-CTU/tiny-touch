"""Apply app colors to Windows-owned title bars; a no-op on other platforms."""

import ctypes
from functools import cache
import logging
import sys
from tkinter import TclError


logger = logging.getLogger(__name__)

GA_ROOT = 2
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36


@cache
def _windows_api():
    # Load lazily: importing the GUI must remain safe on Linux and headlessly.
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    ancestor = user32.GetAncestor
    ancestor.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ancestor.restype = ctypes.c_void_p
    set_attribute = dwmapi.DwmSetWindowAttribute
    set_attribute.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                             ctypes.c_void_p, ctypes.c_uint32]
    set_attribute.restype = ctypes.c_int32  # signed HRESULT, also on 64-bit Windows
    return ancestor, set_attribute


def apply_title_bar(window, *, dark, background, foreground):
    """Style a Tk window's native wrapper without mapping or focusing it.

    Explicit caption/text colors follow the app's choice independently of the
    Windows system theme. Unsupported attributes retain the OS defaults.
    """
    if sys.platform != "win32":
        return False
    try:
        ancestor, set_attribute = _windows_api()
        # winfo_id identifies Tk's client window; DWM needs its outer frame.
        hwnd = ancestor(window.winfo_id(), GA_ROOT)
        if not hwnd:
            logger.debug("Native title bar has no window handle yet")
            return False

        attributes = (
            (DWMWA_USE_IMMERSIVE_DARK_MODE, int(dark)),
            (DWMWA_CAPTION_COLOR, int.from_bytes(bytes.fromhex(background[1:]), "little")),
            (DWMWA_TEXT_COLOR, int.from_bytes(bytes.fromhex(foreground[1:]), "little")),
        )
        applied = True
        for attribute, value in attributes:
            native_value = ctypes.c_uint32(value)  # BOOL and COLORREF are 4 bytes
            result = set_attribute(hwnd, attribute, ctypes.byref(native_value),
                                   ctypes.sizeof(native_value))
            if result < 0:
                logger.debug("Native title bar attribute %s unavailable: HRESULT %#x",
                             attribute, result & 0xffffffff)
                applied = False
        return applied
    except (OSError, TclError) as exc:
        logger.debug("Native title bar styling unavailable: %s", exc)
        return False
