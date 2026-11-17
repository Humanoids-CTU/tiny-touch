"""Allow one running TinyTouch per app folder.

A second launch (e.g. a double double-click) brings the running window to the
front and exits. The lock is per app folder, because config.json, data/ and
videos/ live there: two copies in different folders may still run together.

Windows uses a named mutex; Linux an advisory ``flock`` on a file in the temp
folder. Both are released by the OS when the process ends, even on a crash.
"""

import hashlib
import os
import sys
import tempfile

SINGLE_INSTANCE = True
MAIN_WINDOW_TITLE = "TinyTouch"   # gui/ui_components sets this on the root
SW_RESTORE = 9
ERROR_ALREADY_EXISTS = 183

_handle = None   # kept for the life of the process; the OS frees it on exit


def _lock_name(app_dir: str) -> str:
    key = os.path.normcase(os.path.abspath(app_dir)).encode("utf-8")
    return "TinyTouch-" + hashlib.sha1(key).hexdigest()[:16]


def acquire(app_dir: str) -> bool:
    """True if this is the only instance for ``app_dir`` (or the check is off/unavailable)."""
    global _handle
    if not SINGLE_INSTANCE:
        return True
    name = _lock_name(app_dir)
    try:
        if sys.platform == "win32":
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.restype = ctypes.c_void_p
            _handle = kernel32.CreateMutexW(None, False, "Local\\" + name)
            return ctypes.get_last_error() != ERROR_ALREADY_EXISTS
        import fcntl

        _handle = open(os.path.join(tempfile.gettempdir(), name + ".lock"), "w")
        try:
            fcntl.flock(_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True
    except Exception:
        return True   # never block startup because the check itself failed


def focus_running_instance() -> None:
    """Bring the already-running TinyTouch window to the front (Windows only)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        own_pid = os.getpid()
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(hwnd, _):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != own_pid and user32.IsWindowVisible(hwnd):
                title = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, title, 256)
                if title.value == MAIN_WINDOW_TITLE:
                    found.append(hwnd)
                    return False
            return True

        user32.EnumWindows(visit, 0)
        if found:
            if user32.IsIconic(found[0]):
                user32.ShowWindow(found[0], SW_RESTORE)
            user32.SetForegroundWindow(found[0])
    except Exception:
        pass   # Cosmetic: the second launch still exits.
