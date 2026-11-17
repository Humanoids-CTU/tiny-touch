"""Startup splash screen shown while the packaged app starts.

The splash itself is PyInstaller's bootloader splash (``Splash`` in
TinyTouch.spec): it appears as soon as the .exe is launched, before Python
runs, and covers the onefile unpacking. This module animates its status line
and closes it once the main window is shown. Outside a PyInstaller build with
a splash (``pyi_splash`` missing) every function is a no-op.
"""

import threading

# Status line animation: "Loading", "Loading.", "Loading..", "Loading..."
DOT_INTERVAL_S = 0.35
MAX_DOTS = 3

try:
    import pyi_splash  # Only importable inside a PyInstaller build with a splash.
except ImportError:
    pyi_splash = None

_lock = threading.Lock()
_status = "Starting"
_stop = threading.Event()
_thread = None


def _send(text: str) -> None:
    try:
        pyi_splash.update_text(text)
    except Exception:
        # The splash is cosmetic; a failed update must never block startup.
        pass


def _animate() -> None:
    dots = 0
    while not _stop.is_set():
        with _lock:
            if _stop.is_set():
                return
            _send(_status + "." * dots)
        dots = (dots + 1) % (MAX_DOTS + 1)
        _stop.wait(DOT_INTERVAL_S)


def start() -> None:
    """Begin animating the splash status line (no-op without a splash)."""
    global _thread
    if pyi_splash is None or _thread is not None:
        return
    _thread = threading.Thread(target=_animate, name="startup-splash", daemon=True)
    _thread.start()


def set_status(text: str) -> None:
    """Change the status shown under the splash image, e.g. "Loading video tools"."""
    global _status
    with _lock:
        _status = text


def close() -> None:
    """Stop the animation and close the splash. Safe to call more than once."""
    if pyi_splash is None:
        return
    with _lock:
        _stop.set()
        try:
            if pyi_splash.is_alive():
                pyi_splash.close()
        except Exception:
            pass
