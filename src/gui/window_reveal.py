"""Show every window once: finished, laid out and in place.

Every ``tk.Toplevel`` is created *pending*: invisible (alpha 0) although Tk
maps it as usual, so grabs, focus and geometry behave as for a visible window.
On its ``<Map>``, one idle callback settles it (window events and idle
callbacks until neither has work left: cards fit their content, images and
canvases draw), runs its placement callbacks on the settled size, settles
again, and only then shows it, in one step. A dialog does not
withdraw/centre/deiconify itself; it registers where it goes::

    window_reveal.place_on_reveal(win, lambda: center_over_parent(win, parent))
    window_reveal.modal_grab(win)    # grab_set, deferred if not yet viewable
    win.wait_window()

Unmapping a shown window (withdraw, iconify) arms it again, so a later
deiconify is covered too. Borderless popups (overrideredirect: dropdown lists)
are shown as soon as they map. Native dialogs (messagebox, file dialogs) and
Tcl-created windows (combobox lists) are not ``tk.Toplevel`` objects and are
untouched.

The main window uses the same reveal through ``hide_root_until_settled``. On
Windows it is hidden with a DWM cloak instead of alpha (it never becomes a
layered window) and built withdrawn, so the caller can map it zoomed directly,
without the maximize animation.

Where alpha cannot hide a window (X11 without a compositing manager), a
Toplevel maps far off-screen instead and its placement moves it into view once
settled. Withdrawing does not work: a withdrawn window lays nothing out.
"""

import _tkinter
import logging
import sys
import time
import tkinter as tk
from tkinter import TclError

from gui.native_title_bar import set_cloaked

logger = logging.getLogger(__name__)

REVEAL_WHEN_SETTLED = True   # False: windows show as Tk maps them (tests that hide windows themselves)
REVEAL_MAX_PASSES = 40       # settle passes (window events + idle) before showing anyway
REVEAL_BUDGET_MS = 1500      # wall-clock cap of one settle, so a busy window cannot hang the UI
REVEAL_WATCHDOG_MS = 3000    # show anyway if a nested event loop stalls a reveal
REVEAL_OFFSCREEN_XY = 20000  # px: where a window waits when alpha cannot hide it ("offscreen" mode)
REVEAL_ACTIVATES = True      # a revealed window takes the foreground and keyboard focus, as deiconify did

IS_WINDOWS = sys.platform == "win32"
_reveal_mode_cache = []


def settle(widget, budget_ms=None):
    """Run window events and idle callbacks until neither has work left.

    ``update_idletasks`` is not enough: it does not deliver the Map and
    Configure events that cards need to size themselves. Timers and file
    events do not run, so no animation or poll advances. Capped by
    REVEAL_MAX_PASSES and ``budget_ms`` (REVEAL_BUDGET_MS by default).
    """
    tkapp = widget.tk
    budget_ms = REVEAL_BUDGET_MS if budget_ms is None else budget_ms
    deadline = time.perf_counter() + budget_ms / 1000
    for _ in range(REVEAL_MAX_PASSES):
        busy = 0
        for flags in (_tkinter.WINDOW_EVENTS, _tkinter.IDLE_EVENTS):
            while time.perf_counter() < deadline and tkapp.dooneevent(flags | _tkinter.DONT_WAIT):
                busy += 1
        if not busy or time.perf_counter() >= deadline:
            return


# --- Public API ---------------------------------------------------------------------
def install(root):
    """Arm every future tk.Toplevel (and subclasses such as simpledialog.Dialog)."""
    if not getattr(tk.Toplevel, "_tinytouch_reveal", False):
        original_init = tk.Toplevel.__init__

        def init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            mode = _reveal_mode(self) if REVEAL_WHEN_SETTLED else None
            if mode is not None:
                _arm(self, mode)

        tk.Toplevel.__init__ = init
        tk.Toplevel._tinytouch_reveal = True
    root.bind_all("<Map>", _on_map, add="+")
    root.bind_all("<Unmap>", _on_unmap, add="+")


def hide_root_until_settled(root):
    """Keep the main window hidden while it is built; show it once, settled.

    Call right after ``init_style``, before building the content. On Windows
    the root is withdrawn and cloaked; it maps on the next event-loop turn, or
    earlier when the caller sets its state (``state("zoomed")`` then maps it
    maximized, with no restore step and no animation).
    """
    if not REVEAL_WHEN_SETTLED:
        return
    mode = _reveal_mode(root)
    if mode == "offscreen":
        return   # a maximized window cannot wait off-screen: shown as Tk maps it
    if IS_WINDOWS and _cloak_withdrawn(root):
        mode = "cloak"
    if mode is not None:
        _arm(root, mode)


def is_pending(window):
    """True while ``window`` waits to be revealed (built, but not shown yet)."""
    state = getattr(window, "_reveal", None)
    return state is not None and state["pending"]


def place_on_reveal(window, place):
    """Run ``place()`` once ``window`` has its final size, before it is shown.

    ``place`` positions or fits the window (centring, the diagram fit). It runs
    on the settled size, so a content-sized dialog is centred on the size it
    is shown at. Without a pending reveal (the hook is off, or the window is
    already visible) it runs at once.
    """
    if is_pending(window):
        window._reveal["place"].append(place)
    else:
        place()


def on_reveal(window, callback):
    """Run ``callback()`` right after ``window`` becomes visible (or now)."""
    if is_pending(window):
        window._reveal["callbacks"].append(callback)
    else:
        callback()


def modal_grab(window):
    """``grab_set`` now; if the window is not viewable yet, once it is shown.

    A local grab normally works on a window that is not mapped yet, but on X11
    it fails while a mouse button is held ("window not viewable").
    """
    try:
        window.grab_set()
    except TclError:
        if not is_pending(window):
            raise
        on_reveal(window, window.grab_set)


# --- Hiding and showing ---------------------------------------------------------------
def _reveal_mode(window):
    """"alpha", "offscreen" or None (leave windows alone)."""
    if not _reveal_mode_cache:
        try:
            system = window.tk.call("tk", "windowingsystem")
        except TclError:
            system = ""
        if system in ("win32", "aqua"):
            mode = "alpha"
        elif system == "x11":
            mode = "alpha" if _x11_compositing(window) else "offscreen"
        else:
            mode = None
        _reveal_mode_cache.append(mode)
    return _reveal_mode_cache[0]


def _x11_compositing(window):
    """True when an X11 compositing manager runs (it honours window opacity)."""
    try:
        import ctypes
        import ctypes.util
        xlib = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        xlib.XOpenDisplay.restype = ctypes.c_void_p
        xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        xlib.XDefaultScreen.argtypes = [ctypes.c_void_p]
        xlib.XInternAtom.restype = ctypes.c_ulong
        xlib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        xlib.XGetSelectionOwner.restype = ctypes.c_ulong
        xlib.XGetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        display = xlib.XOpenDisplay(str(window.winfo_screen()).encode())
        if not display:
            return False
        try:
            name = f"_NET_WM_CM_S{xlib.XDefaultScreen(display)}".encode()
            atom = xlib.XInternAtom(display, name, 1)   # only if it exists
            return bool(atom) and bool(xlib.XGetSelectionOwner(display, atom))
        finally:
            xlib.XCloseDisplay(display)
    except Exception:   # no libX11 / unexpected platform: the safe fallback
        logger.debug("compositor detection failed", exc_info=True)
        return False


def _cloak_withdrawn(root):
    """Withdraw the root, let Tk create its native frame hidden, and cloak that frame.

    Tk creates the frame at the first map and would show it at once; an idle
    pass while withdrawn creates it without showing it.
    """
    try:
        root.withdraw()
        root.update_idletasks()
        root.after(0, _map_if_withdrawn, root)
        return set_cloaked(root, True)
    except TclError:
        return False


def _map_if_withdrawn(window):
    try:
        if window.state() == "withdrawn":
            window.deiconify()
    except TclError:   # destroyed meanwhile
        pass


def _set_alpha(window, value):
    try:
        window.attributes("-alpha", value)
    except TclError:
        pass


def _arm(window, mode):
    window._reveal = {"mode": mode, "pending": True, "queued": False, "busy": False,
                      "place": [], "callbacks": []}
    if mode == "alpha":
        _set_alpha(window, 0.0)
    elif mode == "offscreen":
        window.geometry(f"+{REVEAL_OFFSCREEN_XY}+{REVEAL_OFFSCREEN_XY}")
    # "cloak": already cloaked by _cloak_withdrawn


def _on_map(event):
    window = event.widget
    if not is_pending(window):   # also skips child widgets and Tcl-only windows (str)
        return
    try:
        borderless = window.overrideredirect()
    except TclError:
        return
    if borderless:
        _show(window)   # dropdown lists appear at once
        return
    state = window._reveal
    if not state["queued"]:
        state["queued"] = True
        window._root().after_idle(_reveal, window)


def _on_unmap(event):
    # Withdrawn or iconified: hide it again, so the next map settles first.
    window = event.widget
    state = getattr(window, "_reveal", None)
    if state is None or state["mode"] != "alpha" or state["pending"] or state["busy"]:
        return
    try:
        if window.overrideredirect():
            return
    except TclError:
        return
    _set_alpha(window, 0.0)
    state["pending"] = True


def _reveal(window):
    state = window._reveal
    state["queued"] = False
    if not state["pending"] or state["busy"]:
        return
    try:
        if not window.winfo_exists() or not window.winfo_ismapped():
            return   # destroyed, or withdrawn again; the next <Map> queues it again
    except TclError:
        return
    state["busy"] = True
    root = window._root()
    # A settle runs only window events and idle callbacks, so this timer fires
    # only if one of them enters a nested event loop (a modal opened by a key
    # press, say) that would otherwise keep this window hidden meanwhile.
    watchdog = root.after(REVEAL_WATCHDOG_MS, _show, window)
    try:
        settle(window)
        places, state["place"] = state["place"], []
        if not places and state["mode"] == "offscreen":
            places = [lambda: _center_on_master(window)]   # it must leave the off-screen spot
        if places and window.winfo_exists():
            for place in places:
                place()
            settle(window)
    except TclError:
        pass
    except Exception:
        logger.exception("window reveal failed for %s", window)
    finally:
        state["busy"] = False
        try:
            root.after_cancel(watchdog)
        except TclError:
            pass
        _show(window)


def _show(window):
    """Make a pending window visible and run its on_reveal callbacks."""
    state = window._reveal
    if not state["pending"]:
        return
    state["pending"] = False
    callbacks, state["callbacks"] = state["callbacks"], []
    try:
        if not window.winfo_exists():
            return
    except TclError:
        return
    if state["mode"] == "alpha":
        _set_alpha(window, 1.0)
    elif state["mode"] == "cloak":
        set_cloaked(window, False)
    _activate(window)
    for callback in callbacks:
        try:
            callback()
        except TclError:
            pass
        except Exception:
            logger.exception("on_reveal callback failed for %s", window)


def _activate(window):
    """Give a revealed window the foreground and keyboard focus.

    `wm deiconify` used to do this as a side effect (Windows raises and
    focuses a deiconified window); a window revealed by alpha or cloak is
    never deiconified, so modals would leave Escape and typing on the parent.
    Focus returns to the widget that last had it inside the window, so a
    dialog's own `focus_set` on an entry is kept. on_reveal callbacks run
    afterwards and can still move it.
    """
    if not REVEAL_ACTIVATES:
        return
    try:
        if window.overrideredirect():
            return
        target = window.focus_lastfor() or window
        target.focus_force()
    except TclError:
        pass


def _center_on_master(window):
    master = window.master if window.master is not None else window._root()
    x = master.winfo_rootx() + (master.winfo_width() - window.winfo_width()) // 2
    y = master.winfo_rooty() + (master.winfo_height() - window.winfo_height()) // 2
    window.geometry(f"+{max(0, x)}+{max(0, y)}")
