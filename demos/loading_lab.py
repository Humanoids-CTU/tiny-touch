"""Loading lab: measure half-built frames when windows open or swap content.

Standalone measurement harness (it changes nothing in the app). Every case
runs in its own process: a backdrop window (or the real main window), then a
scenario that opens a real TinyTouch dialog or rebuilds its content, with one
"reveal" approach installed. Meanwhile this process records every frame the
desktop compositor presents (DXGI Desktop Duplication, Windows only), and the
case process records every Tk geometry change.

Each presented frame after an action is compared with the frame before it
(B) and the final, settled frame (F): a frame that is B, F, or an alpha blend
of the two (a fade) is clean; anything else (a card still growing, an image
missing, the window at the wrong place) is a dirty frame. A pass shows zero
dirty frames and zero Tk geometry changes after the reveal.

Run from the repository root (a few minutes; windows appear on top):

    uv run demos/loading_lab.py

Choose cases with the constants below. Output: a table on stdout, results.json
and one frame-strip PNG per case in OUTPUT_DIR.
"""

import ctypes
import json
import multiprocessing as mp
import os
import queue
import sys
import tempfile
import threading
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw

# --- Tunables ---------------------------------------------------------------
# Approaches when a window opens:
#   none          the windows as HEAD shows them (no fade)
#   app           the app's own reveal (gui.window_reveal): alpha 0 until mapped and settled
#   settle_alpha  alpha 0 until the window is mapped, settle, then alpha 1.0
#   settle_cloak  alpha 0 until mapped, then DWM-cloak, alpha 1.0, settle, uncloak
OPEN_APPROACHES = ("none", "app", "settle_alpha", "settle_cloak")
# Approaches when content is rebuilt inside a visible window:
#   none          rebuild and return to the event loop (as the app does)
#   settle        rebuild, then settle synchronously (no freeze)
#   freeze        WM_SETREDRAW off, rebuild, settle, redraw on + RedrawWindow
#   cover         a PrintWindow snapshot label covers the window during the rebuild
#   build_under   build the new content below the old one, settle, then drop the old
#   cloak         DWM-cloak the window during the rebuild
#   freeze_client same, but on Tk's client window instead of the frame window
SWAP_APPROACHES = ("none", "settle", "freeze", "freeze_client", "cover", "build_under", "cloak")
# The main window (LabelingApp + state zoomed):
#   none                 as the app starts today
#   settle_cloak         root hidden until mapped + settled
#   settle_cloak_fitfix  same, plus the diagram re-fit runs at once, not after 150 ms
MAIN_APPROACHES = ("none", "settle_cloak", "settle_cloak_fitfix")
CASES = (
    [("synthetic_open", a) for a in OPEN_APPROACHES]
    + [("wizard_open", a) for a in OPEN_APPROACHES]
    + [("library_open", a) for a in OPEN_APPROACHES]
    + [("synthetic_swap", a) for a in SWAP_APPROACHES]
    + [("wizard_steps", a) for a in SWAP_APPROACHES]
    + [("library_search", a) for a in SWAP_APPROACHES if a != "build_under"]
    + [("main_window", a) for a in MAIN_APPROACHES]
)
REPEATS = 3
# Swap scenarios open their window with this approach first (not measured).
SWAP_OPEN_APPROACH = "settle_cloak"

BACKDROP_GEOMETRY = (1800, 1220, 380, 30)   # device px: w, h, x, y (fits a 150 % wizard; clear of taskbar previews)
BACKDROP_SETTLE_MS = 900                     # backdrop drawn before measuring
CAPTURE_LEAD_MS = 300                        # frames recorded before the first action
ACTION_GAP_MS = 1500                         # between actions (and after the last one)
MAIN_HOLD_MS = 3000                          # main window: watch this long after construction
MAIN_DOWNSAMPLE = 2                          # full-screen capture is analysed at 1/2 size
SETTLE_MAX_PASSES = 40
SETTLE_BUDGET_S = 2.0
LIBRARY_ENTRIES = 8
SEARCH_TEXT = "e"

# Frame classification. A pixel is "off" when it differs by more than
# RESIDUAL_TOL (0-255, any channel) from the best blend of B and F; a frame is
# dirty when more than DIRTY_MIN_PX pixels are off.
RESIDUAL_TOL = 24
DIRTY_MIN_PX = 64
STRIP_THUMB_W = 300
STRIP_MAX_FRAMES = 24

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
OUTPUT_DIR = Path(tempfile.gettempdir()) / "tinytouch_loading_lab"
CASE_TIMEOUT_S = 40

APP_CONFIG = {
    "video_renderer": "cpu", "diagram_scale": 1.0, "dot_size": 10.0, "minimal_touch_length": 280,
    "parameter1": "P1", "parameter2": "P2", "parameter3": "P3",
    "limb_parameter1": "LP1", "limb_parameter2": "LP2", "limb_parameter3": "LP3",
    "video_downscale": 1.0, "jump_seconds": 0.28, "realtime_arrow_hold": False,
    "perf_enabled": False, "perf_log_every_s": 2.0, "perf_log_top_n": 10, "last_labeling_mode": "Normal",
}

IS_WINDOWS = sys.platform == "win32"


# =============================================================================
# Windows helpers (all no-ops elsewhere)
# =============================================================================
WM_SETREDRAW = 0x000B
RDW_INVALIDATE, RDW_ERASE, RDW_ALLCHILDREN, RDW_FRAME = 0x1, 0x4, 0x80, 0x400
DWMWA_CLOAK = 13
GA_ROOT = 2


def _win():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetAncestor.restype = ctypes.c_void_p
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    user32.RedrawWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    user32.GetDC.restype = ctypes.c_void_p
    user32.GetDC.argtypes = [ctypes.c_void_p]
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    dwm = ctypes.WinDLL("dwmapi")
    dwm.DwmSetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
    gdi = ctypes.WinDLL("gdi32")
    gdi.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi.CreateDIBSection.restype = ctypes.c_void_p
    gdi.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                                     ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint]
    gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi.DeleteDC.argtypes = [ctypes.c_void_p]
    return user32, dwm, gdi


def hwnd_of(window):
    user32, _, _ = _win()
    return user32.GetAncestor(window.winfo_id(), GA_ROOT)


def cloak(window, on):
    if not IS_WINDOWS:
        return False
    _, dwm, _ = _win()
    value = ctypes.c_int(1 if on else 0)
    return dwm.DwmSetWindowAttribute(hwnd_of(window), DWMWA_CLOAK, ctypes.byref(value), 4) == 0


def set_redraw(window, on, client=False):
    user32, _, _ = _win()
    hwnd = window.winfo_id() if client else hwnd_of(window)
    user32.SendMessageW(hwnd, WM_SETREDRAW, 1 if on else 0, None)
    if on:
        flags = RDW_INVALIDATE | RDW_ALLCHILDREN | (0 if client else RDW_ERASE | RDW_FRAME)
        user32.RedrawWindow(hwnd, None, None, flags)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]


def print_window(window):
    """The Tk toplevel's client area as a PIL image (PrintWindow, full content)."""
    user32, _, gdi = _win()
    hwnd = window.winfo_id()   # Tk's client window: exactly the toplevel's area
    w, h = window.winfo_width(), window.winfo_height()
    screen = user32.GetDC(None)
    mdc = gdi.CreateCompatibleDC(screen)
    header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    bitmap = gdi.CreateDIBSection(mdc, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
    old = gdi.SelectObject(mdc, bitmap)
    user32.PrintWindow(hwnd, mdc, 2)   # PW_RENDERFULLCONTENT
    data = ctypes.string_at(bits, w * h * 4)
    image = Image.frombuffer("RGB", (w, h), data, "raw", "BGRX", 0, 1).copy()
    gdi.SelectObject(mdc, old)
    gdi.DeleteObject(bitmap)
    gdi.DeleteDC(mdc)
    user32.ReleaseDC(None, screen)
    return image


# =============================================================================
# DXGI Desktop Duplication: every frame the compositor presents, QPC-stamped
# =============================================================================
class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16), ("d3", ctypes.c_uint16), ("d4", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, text):
        import uuid
        u = uuid.UUID(text)
        return cls(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))


def _com(obj, index, restype, *args):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *[ctypes.c_void_p] * len(args))
    return proto(vtbl[index])(obj, *args)


def _check(result, what):
    if result is not None and result < 0:
        raise OSError(f"{what} failed: 0x{result & 0xffffffff:08x}")


def _qi(obj, iid):
    guid, out = _GUID.of(iid), ctypes.c_void_p()
    _check(_com(obj, 0, ctypes.c_long, ctypes.addressof(guid), ctypes.addressof(out)), "QueryInterface")
    return out


class _TexDesc(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint) for n in ("Width", "Height", "MipLevels", "ArraySize", "Format", "Count",
                                             "Quality", "Usage", "BindFlags", "CPUAccessFlags", "MiscFlags")]


class _FrameInfo(ctypes.Structure):
    _fields_ = [("LastPresentTime", ctypes.c_longlong), ("LastMouseUpdateTime", ctypes.c_longlong),
                ("AccumulatedFrames", ctypes.c_uint), ("RectsCoalesced", ctypes.c_int),
                ("ProtectedContentMaskedOut", ctypes.c_int), ("px", ctypes.c_long), ("py", ctypes.c_long),
                ("pv", ctypes.c_int), ("TotalMetadataBufferSize", ctypes.c_uint), ("PointerShapeBufferSize", ctypes.c_uint)]


class _Mapped(ctypes.Structure):
    _fields_ = [("pData", ctypes.c_void_p), ("RowPitch", ctypes.c_uint), ("DepthPitch", ctypes.c_uint)]


class _Box(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint) for n in ("left", "top", "front", "right", "bottom", "back")]


class DesktopCapture:
    """Record the frames presented inside a screen region, deduplicated."""

    WAIT_TIMEOUT = 0x887A0027
    ACCESS_LOST = 0x887A0026

    def __init__(self):
        d3d = ctypes.WinDLL("d3d11")
        self.device, self.context, level = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_uint()
        _check(d3d.D3D11CreateDevice(None, 1, None, 0, None, 0, 7, ctypes.byref(self.device),
                                     ctypes.byref(level), ctypes.byref(self.context)), "D3D11CreateDevice")
        dxgi_device = _qi(self.device, "54ec77fa-1377-44e6-8c32-88fd5f44c84c")
        adapter, output = ctypes.c_void_p(), ctypes.c_void_p()
        _check(_com(dxgi_device, 7, ctypes.c_long, ctypes.addressof(adapter)), "GetAdapter")
        _check(_com(adapter, 7, ctypes.c_long, 0, ctypes.addressof(output)), "EnumOutputs")
        self.output1 = _qi(output, "00cddea8-939b-4b83-a340-a685226666cc")
        self.freq = ctypes.c_longlong()
        ctypes.windll.kernel32.QueryPerformanceFrequency(ctypes.byref(self.freq))
        self.dup = None
        self._open()

    def _open(self):
        self.dup = ctypes.c_void_p()
        _check(_com(self.output1, 22, ctypes.c_long, self.device.value, ctypes.addressof(self.dup)), "DuplicateOutput")

    def record(self, region, stop, downsample=1):
        """Frames as [(present_time_s, rgb array)] until ``stop`` is set."""
        x, y, w, h = region
        desc = _TexDesc(w, h, 1, 1, 87, 1, 0, 3, 0, 0x20000, 0)   # BGRA staging, CPU read
        staging = ctypes.c_void_p()
        _check(_com(self.device, 5, ctypes.c_long, ctypes.addressof(desc), 0, ctypes.addressof(staging)),
               "CreateTexture2D")
        info, resource = _FrameInfo(), ctypes.c_void_p()
        frames, last, missed = [], None, 0
        self.busy_ms = []
        try:
            while not stop.is_set():
                result = _com(self.dup, 8, ctypes.c_long, 50, ctypes.addressof(info), ctypes.addressof(resource))
                if result & 0xffffffff == self.WAIT_TIMEOUT:
                    continue
                if result & 0xffffffff == self.ACCESS_LOST:
                    self._open()
                    continue
                _check(result, "AcquireNextFrame")
                try:
                    if info.LastPresentTime:
                        busy_start = time.perf_counter()
                        missed += max(0, info.AccumulatedFrames - 1)
                        texture = _qi(resource, "6f15aaf2-d208-4e89-9ab4-489535d34f9c")
                        box = _Box(x, y, 0, x + w, y + h, 1)
                        _com(self.context, 46, None, staging.value, 0, 0, 0, 0, texture.value, 0, ctypes.addressof(box))
                        mapped = _Mapped()
                        _check(_com(self.context, 14, ctypes.c_long, staging.value, 0, 1, 0, ctypes.addressof(mapped)), "Map")
                        raw = (ctypes.c_ubyte * (mapped.RowPitch * h)).from_address(mapped.pData)
                        pixels = np.frombuffer(raw, dtype=np.uint8).reshape(h, mapped.RowPitch // 4, 4)
                        bgra = pixels[::downsample].copy() if downsample > 1 else pixels.copy()
                        _com(self.context, 15, None, staging.value, 0)
                        _com(texture, 2, ctypes.c_ulong)
                        if last is None or not np.array_equal(bgra, last):
                            frames.append((info.LastPresentTime / self.freq.value, bgra))
                            last = bgra
                        self.busy_ms.append((time.perf_counter() - busy_start) * 1000)
                finally:
                    _com(resource, 2, ctypes.c_ulong)
                    _com(self.dup, 14, ctypes.c_long)
        finally:
            _com(staging, 2, ctypes.c_ulong)
        # Raw BGRA rows (pitch-padded) -> RGB, after recording so the loop stays fast.
        frames = [(t, bgra[:, :w:downsample, 2::-1].copy()) for t, bgra in frames]
        return frames, missed


# =============================================================================
# Case process: the reveal mechanisms under test
# =============================================================================
def settle(widget, stats=None):
    """Run window events and idle callbacks until neither has work left.

    Timers and file events are not run, so no animation or poll advances; only
    the layout/paint chain (idle -> Configure -> idle ...) is drained.
    """
    import _tkinter
    tkapp = widget.tk
    started = time.perf_counter()
    passes = 0
    while passes < SETTLE_MAX_PASSES and time.perf_counter() - started < SETTLE_BUDGET_S:
        busy = 0
        while tkapp.dooneevent(_tkinter.WINDOW_EVENTS | _tkinter.DONT_WAIT):
            busy += 1
        while tkapp.dooneevent(_tkinter.IDLE_EVENTS | _tkinter.DONT_WAIT):
            busy += 1
        if not busy:
            break
        passes += 1
    if stats is not None:
        stats.append({"passes": passes, "ms": round((time.perf_counter() - started) * 1000, 1)})
    return passes


class Recorder:
    """Tk-side log: geometry changes, maps, reveal moments, action marks."""

    def __init__(self, out_q):
        self.out_q = out_q
        self.geometry = {}
        self.changes = []          # (t, toplevel, widget, class)
        self.maps = []             # (t, toplevel, widget)
        self.reveals = []          # (t, toplevel, how)
        self.marks = []            # (t, label)
        self.settles = []
        self.profile = {}
        self.root_path = None
        self.top_rects = []        # (t, toplevel, rootx, rooty, w, h)

    def install(self, root):
        self.root_path = str(root)
        root.bind_all("<Configure>", self._on_configure, add="+")
        root.bind_all("<Map>", self._on_map, add="+")

    @staticmethod
    def _top(widget):
        try:
            return str(widget.winfo_toplevel())
        except Exception:
            return "?"

    def _on_configure(self, event):
        widget = event.widget
        if isinstance(widget, str):
            return
        key = str(widget)
        geometry = (event.x, event.y, event.width, event.height)
        if self._top(widget) == key and key != self.root_path:
            try:
                self.top_rects.append((time.perf_counter(), key, widget.winfo_rootx(), widget.winfo_rooty(),
                                       event.width, event.height))
            except Exception:
                pass
        if self.geometry.get(key) != geometry:
            if key in self.geometry:
                self.changes.append((time.perf_counter(), self._top(widget), key, widget.winfo_class()))
            else:
                self.changes.append((time.perf_counter(), self._top(widget), key, widget.winfo_class() + ":first"))
            self.geometry[key] = geometry

    def _on_map(self, event):
        widget = event.widget
        if isinstance(widget, str):
            return
        top = self._top(widget)
        self.maps.append((time.perf_counter(), top, str(widget)))
        if str(widget) == top:
            # Mapped at alpha 0 is not visible yet; the alpha/settle hooks log that.
            try:
                alpha = float(widget.tk.call("wm", "attributes", widget._w, "-alpha"))
            except Exception:
                alpha = 1.0
            if alpha > 0:
                self.reveal(top, "map")

    def reveal(self, top, how):
        self.reveals.append((time.perf_counter(), top, how))

    def mark(self, label):
        t = time.perf_counter()
        self.marks.append((t, label))
        self.out_q.put(("mark", label, t))
        return t

    def timed(self, owner, name, label=None):
        """Wrap ``owner.name`` to count calls and time spent."""
        original = getattr(owner, name)
        label = label or f"{getattr(owner, '__name__', owner)}.{name}"
        entry = self.profile.setdefault(label, [0, 0.0])

        def wrapper(*args, **kwargs):
            t = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                entry[0] += 1
                entry[1] += time.perf_counter() - t
        setattr(owner, name, wrapper)

    def result(self):
        return {"top_rects": self.top_rects, "changes": self.changes, "maps": self.maps, "reveals": self.reveals, "marks": self.marks,
                "settles": self.settles, "profile": {k: (n, round(s * 1000, 1)) for k, (n, s) in self.profile.items()}}


def install_open_approach(approach, rec, theme):
    """Patch Toplevel creation (and wm attributes logging) for ``approach``."""
    import tkinter as tk
    from gui import window_reveal

    window_reveal.REVEAL_WHEN_SETTLED = approach == "app"
    original_attributes = tk.Wm.wm_attributes

    def attributes(self, *args, **kwargs):
        if len(args) >= 2 and args[0] == "-alpha" and float(args[1]) > 0 and str(self) != rec.root_path:
            rec.reveal(str(self), f"alpha={args[1]}")
        return original_attributes(self, *args, **kwargs)
    tk.Wm.wm_attributes = tk.Wm.attributes = attributes
    if approach.startswith("settle"):
        original_init = tk.Toplevel.__init__

        def init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            arm(self, approach, rec)
        tk.Toplevel.__init__ = init


def arm(window, approach, rec):
    """Keep ``window`` invisible until it is mapped and its layout has settled."""
    use_cloak = "cloak" in approach and IS_WINDOWS
    try:
        window.tk.call("wm", "attributes", window._w, "-alpha", 0.0)
    except Exception:
        return
    state = {"pending": False}

    def reveal():
        state["pending"] = False
        if not window.winfo_exists() or not window.winfo_ismapped():
            return
        cloaked = use_cloak and cloak(window, True)
        if cloaked:
            window.tk.call("wm", "attributes", window._w, "-alpha", 1.0)
        settle(window, rec.settles)
        place = getattr(window, "_lab_place", None)
        if place is not None:
            # Centre on the settled size, not the size before cards grew.
            place()
            settle(window, rec.settles)
        if cloaked:
            cloak(window, False)
        else:
            window.tk.call("wm", "attributes", window._w, "-alpha", 1.0)
        rec.reveal(str(window), "settled")

    def on_map(event):
        if event.widget is window and not state["pending"]:
            state["pending"] = True
            window.after_idle(reveal)

    def on_unmap(event):
        if event.widget is window:
            window.tk.call("wm", "attributes", window._w, "-alpha", 0.0)
    window.bind("<Map>", on_map, add="+")
    window.bind("<Unmap>", on_unmap, add="+")


@contextmanager
def frozen(window, approach, rec):
    """Show the old frame until the rebuilt content has settled."""
    cover = None
    if approach in ("freeze", "freeze_client") and IS_WINDOWS:
        set_redraw(window, False, client=approach == "freeze_client")
    elif approach == "cloak":
        cloak(window, True)
    elif approach == "cover" and IS_WINDOWS:
        import tkinter as tk
        from PIL import ImageTk
        photo = ImageTk.PhotoImage(print_window(window), master=window)
        cover = tk.Label(window, image=photo, bd=0, highlightthickness=0)
        cover.image = photo
        cover.place(x=0, y=0)
        cover.lift()
        settle(window)
    try:
        yield
    finally:
        if approach != "none":
            settle(window, rec.settles)
        if approach in ("freeze", "freeze_client") and IS_WINDOWS:
            set_redraw(window, True, client=approach == "freeze_client")
            settle(window, rec.settles)
        elif approach == "cloak":
            cloak(window, False)
        elif cover is not None:
            cover.destroy()
            settle(window, rec.settles)
        rec.reveal(str(window), f"released:{approach}")


# --- scenarios ----------------------------------------------------------------
def _fake_image(path, size, seed):
    rng = np.random.default_rng(seed)
    base = rng.integers(40, 200, size=(size[1] // 8, size[0] // 8, 3), dtype=np.uint8)
    Image.fromarray(base).resize(size, Image.Resampling.BICUBIC).save(path, quality=85)
    return str(path)


def build_synthetic(parent, variant, workdir):
    """Nested RoundedCards, image labels and a busy canvas (a heavy dialog)."""
    import tkinter as tk
    from tkinter import ttk
    from PIL import ImageTk
    from gui import theme
    from gui.widgets import RoundedCard

    px = theme.px
    holder = ttk.Frame(parent)
    holder.photos = []
    for column in range(3):
        holder.columnconfigure(column, weight=1, uniform="cols")
    for index in range(6):
        outer = RoundedCard(holder, pad=px(10))
        outer.grid(row=index // 3, column=index % 3, sticky="nsew", padx=px(6), pady=px(6))
        ttk.Label(outer.inner, text=f"Card {index + 1} / variant {variant}", style="CardHead.TLabel").pack(anchor="w")
        inner = RoundedCard(outer.inner, fill="SEG", pad=px(8), shadow=False)
        inner.pack(fill="x", pady=px(6))
        for line in range(3 + (index + variant) % 3):
            ttk.Label(inner.inner, text=f"Row {line} " + "lorem ipsum " * (1 + (line + variant) % 3),
                      wraplength=px(200)).pack(anchor="w")
        thumb = Image.open(_fake_image(Path(workdir) / f"syn_{variant}_{index}.jpg", (480, 270), index + 10 * variant))
        thumb.thumbnail((px(150 + 20 * variant), px(90)))
        photo = ImageTk.PhotoImage(thumb, master=parent)
        holder.photos.append(photo)
        ttk.Label(outer.inner, image=photo, style="Card.TLabel").pack(anchor="w")
        canvas = tk.Canvas(outer.inner, width=px(180), height=px(40 + 10 * variant), highlightthickness=0)
        theme.bind_colors(canvas, bg="CARD")
        canvas.pack(anchor="w", pady=px(4))
        for k in range(120):
            canvas.create_line(k * 2, 0, k * 2, (k * 7 + variant) % 40, fill=theme.color("ACCENT"))
    return holder


def open_synthetic(root, workdir, center):
    import tkinter as tk
    from tkinter import ttk
    from gui import theme

    win = tk.Toplevel(root)
    win.withdraw()
    win.title("Synthetic heavy window")
    win.transient(root)
    theme.bind_colors(win, bg="WIN")
    body = ttk.Frame(win, padding=theme.px(16))
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="Synthetic heavy window", style="Title.TLabel").pack(anchor="w")
    footer = ttk.Frame(body)
    footer.pack(side="bottom", fill="x")
    ttk.Button(footer, text="Close", style="Primary.TButton", command=win.destroy).pack(side="right")
    win.holder = build_synthetic(body, 0, workdir)
    win.holder.pack(fill="both", expand=True)
    win.body, win.footer = body, footer
    center(win, root)
    win.deiconify()
    return win


def swap_synthetic(win, variant, workdir, approach, rec):
    if approach == "build_under":
        old = win.holder
        new = build_synthetic(win.body, variant, workdir)
        new.place(in_=old, x=0, y=0, relwidth=1, relheight=1)
        new.lower(old)
        settle(win, rec.settles)
        old.destroy()
        new.place_forget()
        new.pack(fill="both", expand=True)
        win.holder = new
        settle(win, rec.settles)
        rec.reveal(str(win), "released:build_under")
        return
    with frozen(win, approach, rec):
        win.holder.destroy()
        win.holder = build_synthetic(win.body, variant, workdir)
        win.holder.pack(fill="both", expand=True)


def placing_center(center):
    """``center`` that the settle hook re-runs once the window has its final size."""
    def wrapped(window, parent):
        window._lab_place = lambda: center(window, parent)
        center(window, parent)
    return wrapped


def library_entries(workdir):
    from domain.templates import TEMPLATE_LABELS
    templates = list(TEMPLATE_LABELS)
    names = ("Alpha session", "Bravo visit", "Charlie home", "Delta lab", "Echo clinic", "Foxtrot", "Golf", "Hotel")
    return [SimpleNamespace(title=f"{names[i % len(names)]} {i:02d}",
                            thumbnail=_fake_image(Path(workdir) / f"thumb_{i}.jpg", (640, 360), i),
                            template=templates[i % len(templates)],
                            preparation_state=("ready", "preparing", "draft", None)[i % 4],
                            setup_name=f"setup {i}" if i % 2 else "", source="x.mp4" if i != 3 else "")
            for i in range(LIBRARY_ENTRIES)]


def _find_toplevel(root, title):
    import tkinter as tk
    for child in root.winfo_children():
        if isinstance(child, tk.Toplevel) and child.title() == title:
            return child
    return None


def _find_entry(widget):
    from tkinter import ttk
    for child in widget.winfo_children():
        if isinstance(child, ttk.Entry):
            return child
        found = _find_entry(child)
        if found is not None:
            return found
    return None


def run_dialog_case(scenario, approach, out_q, workdir):
    import tkinter as tk
    from gui import theme
    from gui.app_dialogs import center_over_parent as plain_center
    from gui import widgets
    import adapters.zone_masks as zone_masks
    from PIL import ImageTk

    rec = Recorder(out_q)
    center_over_parent = placing_center(plain_center)
    swap = scenario in ("synthetic_swap", "wizard_steps", "library_search")
    open_approach = SWAP_OPEN_APPROACH if swap else approach
    if open_approach == "settle_cloak" and not IS_WINDOWS:
        open_approach = "settle_alpha"

    root = tk.Tk()
    w, h, x, y = BACKDROP_GEOMETRY
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.title("Loading lab backdrop")
    root.attributes("-topmost", True)
    theme.init_style(root, "light")
    root.configure(bg=theme.WIN)
    rec.install(root)
    install_open_approach(open_approach, rec, theme)
    rec.timed(widgets.RoundedCard, "repaint", "RoundedCard.repaint")
    rec.timed(widgets.RoundedCard, "_fit", "RoundedCard._fit")
    rec.timed(theme, "rounded_image", "theme.rounded_image")
    rec.timed(ImageTk.PhotoImage, "__init__", "ImageTk.PhotoImage")
    rec.timed(zone_masks, "load_zone_masks", "load_zone_masks")
    import gui.coding_setup_wizard as wizard_module
    wizard_module.load_zone_masks = zone_masks.load_zone_masks
    rec.timed(Image, "open", "PIL.Image.open")
    state = {}

    actions = []
    if scenario in ("synthetic_open", "synthetic_swap"):
        actions.append(("open", lambda: state.update(win=open_synthetic(root, workdir, center_over_parent))))
        if swap:
            actions.append(("swap1", lambda: swap_synthetic(state["win"], 1, workdir, approach, rec)))
            actions.append(("swap2", lambda: swap_synthetic(state["win"], 2, workdir, approach, rec)))
    elif scenario in ("wizard_open", "wizard_steps"):
        from gui.coding_setup_wizard import CodingSetupWizard

        class LabWizard(CodingSetupWizard):
            def render(self):
                if approach != "build_under" or not hasattr(self, "variables"):
                    return super().render()
                from tkinter import ttk
                old = self.content
                new = ttk.Frame(self.body)
                new.place(in_=old, x=0, y=0, relwidth=1, relheight=1)
                new.lower(old)
                self.content = new
                super().render()
                settle(self.win, rec.settles)
                old.destroy()
                new.place_forget()
                new.pack(fill="both", expand=True, before=self.error)
                settle(self.win, rec.settles)
                rec.reveal(str(self.win), "released:build_under")

        def step(wizard):
            if approach == "build_under":
                wizard.next()
            else:
                with frozen(wizard.win, approach, rec):
                    wizard.next()
        actions.append(("open", lambda: state.update(wizard=LabWizard(root, center=center_over_parent))))
        if swap:
            actions.append(("step1", lambda: step(state["wizard"])))
            actions.append(("step2", lambda: step(state["wizard"])))
            actions.append(("step3", lambda: step(state["wizard"])))
    else:
        from gui.video_library import choose_video
        entries = library_entries(workdir)

        def open_library():
            # choose_video blocks in wait_window; later actions run inside it.
            root.after(0, lambda: choose_video(root, entries, center=center_over_parent))

        def search():
            win = _find_toplevel(root, "Video library")
            entry = _find_entry(win)
            with frozen(win, approach, rec):
                entry.insert("end", SEARCH_TEXT)
        actions.append(("open", open_library))
        if swap:
            actions.append(("search", search))

    def run_actions(index=0):
        if index == len(actions):
            rec.mark("finish")
            out_q.put(("result", rec.result()))
            root.after(200, root.destroy)
            return
        label, action = actions[index]
        rec.mark(label)
        if swap and index == 0:
            rec.mark("unmeasured")   # the window open is only the swap's starting point
        t = time.perf_counter()
        action()
        rec.marks.append((time.perf_counter(), f"{label}:returned:{(time.perf_counter() - t) * 1000:.0f}ms"))
        root.after(ACTION_GAP_MS, run_actions, index + 1)

    def start():
        root.update_idletasks()
        out_q.put(("region", (root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height(), 1)))
        root.after(CAPTURE_LEAD_MS, run_actions)
    root.after(BACKDROP_SETTLE_MS, start)
    root.mainloop()


def run_main_case(approach, out_q, workdir):
    import tkinter as tk
    from gui import theme
    from gui import ui_components

    rec = Recorder(out_q)
    original_init_style = theme.init_style

    def init_style(root, *args, **kwargs):
        style = original_init_style(root, *args, **kwargs)
        rec.install(root)
        rec.root_path = "<none>"   # the root is the measured window here
        if approach.startswith("settle"):
            arm(root, approach if IS_WINDOWS else "settle_alpha", rec)
        root.attributes("-topmost", True)
        return style
    theme.init_style = init_style
    from gui import window_reveal
    window_reveal.REVEAL_WHEN_SETTLED = False   # the approaches below arm the root themselves
    if approach.endswith("fitfix"):
        def watch(app):
            # The re-fit as an idle callback (coalesced), not a 150 ms timer, so
            # the settle before the reveal includes it.
            state = {"height": None, "idle": None}

            def settle_fit():
                state["idle"] = None
                ui_components.fit_diagram_to_column(app)

            def on_configure(event):
                if event.widget is app and event.height != state["height"]:
                    state["height"] = event.height
                    if state["idle"] is None:
                        state["idle"] = app.after_idle(settle_fit)
            app.bind("<Configure>", on_configure, add="+")
        ui_components._watch_window_height = watch
    rec.timed(ui_components, "fit_diagram_to_column", "fit_diagram_to_column")

    from labeling_app import LabelingApp
    rec.mark("open")
    app = LabelingApp()
    if app.tk.call("tk", "windowingsystem") == "x11":
        app.attributes("-zoomed", True)
    else:
        app.state("zoomed")
    rec.marks.append((time.perf_counter(), "constructed"))

    def finish():
        rec.mark("finish")
        out_q.put(("result", rec.result()))
        out_q.put(("done",))
        out_q.close()
        out_q.join_thread()   # flush the queue before the hard exit
        os._exit(0)   # daemon threads and the frame buffer die with the process
    app.after(MAIN_HOLD_MS, finish)
    app.mainloop()


def case_main(scenario, approach, out_q, workdir):
    try:
        if IS_WINDOWS:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        sys.path.insert(0, str(SRC))
        os.chdir(workdir)
        config_path = Path(workdir) / "config.json"
        config_path.write_text(json.dumps(APP_CONFIG), encoding="utf-8")
        from adapters import config
        config.get_app_dir = lambda: str(workdir)
        config.get_config_path = lambda: str(config_path)
        if scenario == "main_window":
            screen = (0, 0, ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)) \
                if IS_WINDOWS else (0, 0, 1, 1)
            out_q.put(("region", (*screen, MAIN_DOWNSAMPLE)))
            time.sleep(CAPTURE_LEAD_MS / 1000)
            run_main_case(approach, out_q, workdir)
        else:
            run_dialog_case(scenario, approach, out_q, workdir)
    except Exception:
        out_q.put(("error", traceback.format_exc()))
    out_q.put(("done",))


# =============================================================================
# Orchestrator: capture, analysis, report
# =============================================================================
def classify(frame, before, final, mask=None):
    """('old'|'final'|'blend'|'dirty', alpha, off_px) for one frame, inside ``mask``."""
    if mask is not None:
        frame, before, final = (np.where(mask[..., None], a, 0) for a in (frame, before, final))
    f = frame.astype(np.int16)
    b = before.astype(np.int16)
    d_total = final.astype(np.int16) - b
    d = f - b
    denominator = float((d_total.astype(np.float64) ** 2).sum())
    alpha = float((d.astype(np.float64) * d_total).sum() / denominator) if denominator else 1.0
    alpha = min(1.0, max(0.0, alpha))
    residual = np.abs(d - alpha * d_total).max(axis=2)
    mask = residual > RESIDUAL_TOL
    off = int(mask.sum())
    if off > DIRTY_MIN_PX:
        ys, xs = np.nonzero(mask)
        return "dirty", alpha, (off, (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))
    if alpha < 0.02:
        return "old", alpha, off
    if alpha > 0.98:
        return "final", alpha, off
    return "blend", alpha, off


def window_mask(result, region, end, shape):
    """Union of the measured windows' client areas (excludes desktop noise, captions, shadows)."""
    x0, y0, _, _, down = region
    rects = [r for r in result.get("top_rects", []) if r[0] < end and r[4] > 1 and r[5] > 1]
    if not rects or result.get("full_mask"):
        return None
    mask = np.zeros(shape[:2], dtype=bool)
    for _, _, rx, ry, w, h in rects:
        left, top = max(0, (rx - x0) // down), max(0, (ry - y0) // down)
        mask[top:max(top, (ry - y0 + h) // down), left:max(left, (rx - x0 + w) // down)] = True
    return mask


def analyse(frames, result, case_end, region=None):
    marks = [(t, label) for t, label in result["marks"] if ":returned:" not in label and label != "constructed"]
    measured = [(t, label) for t, label in marks if label not in ("finish", "unmeasured")]
    skip_first = any(label == "unmeasured" for _, label in marks)
    segments = []
    ends = [t for t, _ in marks]
    for index, (start, label) in enumerate(measured):
        if skip_first and index == 0:
            continue
        end = min([t for t in ends if t > start] + [case_end])
        before = [f for f in frames if f[0] <= start]
        inside = [f for f in frames if start < f[0] < end]
        if not before:
            before = frames[:1]
        # (frames may be empty; see below)
        if not frames:   # no capture (Linux, or a locked / sleeping screen): Tk side only
            b = final = None
        else:
            b = before[-1][1]
            final = inside[-1][1] if inside else b
        mask = window_mask(result, region, end, b.shape) if region and b is not None else None
        rows = []
        for i, (t, image) in enumerate(inside):
            kind, alpha, off = classify(image, b, final, mask)
            shown_until = inside[i + 1][0] if i + 1 < len(inside) else end
            off, bbox = off if isinstance(off, tuple) else (off, None)
            rows.append({"t_ms": round((t - start) * 1000, 1), "kind": kind, "alpha": round(alpha, 2),
                         "off_px": off, "off_bbox": bbox, "shown_ms": round((shown_until - t) * 1000, 1), "image": image})
        visible = next((r["t_ms"] for r in rows if r["kind"] != "old"), None)
        final_from = None
        for r in reversed(rows):
            if r["kind"] != "final":
                break
            final_from = r["t_ms"]
        dirty = [r for r in rows if r["kind"] == "dirty"]
        # Tk side: geometry changes after the segment's window became visible.
        reveals = [t for t, top, how in result["reveals"] if start <= t < end]
        if label in ("open",):
            reveal_t = reveals[0] if reveals else None
        else:
            released = [t for t, top, how in result["reveals"] if start <= t < end and how.startswith("released")]
            reveal_t = released[-1] if released else start
        post = [c for c in result["changes"] if reveal_t is not None and reveal_t < c[0] < end
                and c[1] != result.get("backdrop", "")]
        segments.append({
            "segment": label, "frames": len(rows), "dirty": len(dirty),
            "dirty_ms": round(sum(r["shown_ms"] for r in dirty), 1),
            "blend": sum(r["kind"] == "blend" for r in rows),
            "visible_ms": visible, "settled_ms": final_from,
            "reveal_ms": round((reveal_t - start) * 1000, 1) if reveal_t else None,
            "tk_changes_after_reveal": len(post),
            "tk_changes_total": sum(1 for c in result["changes"] if start < c[0] < end),
            "rows": rows,
        })
    return segments


def frame_strip(path, title, rows):
    rows = [r for r in rows if r["kind"] != "old" or r is rows[0]][:STRIP_MAX_FRAMES]
    if not rows:
        return
    first = rows[0]["image"]
    scale = STRIP_THUMB_W / first.shape[1]
    th = max(1, int(first.shape[0] * scale))
    columns = min(6, len(rows))
    lines = -(-len(rows) // columns)
    sheet = Image.new("RGB", (columns * (STRIP_THUMB_W + 8) + 8, lines * (th + 30) + 34), "#202024")
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 8), title, fill="#ffffff")
    colours = {"dirty": "#ff5a4f", "blend": "#ffd23f", "final": "#5bd16b", "old": "#9a9aa0"}
    for i, r in enumerate(rows):
        x = 8 + (i % columns) * (STRIP_THUMB_W + 8)
        y = 34 + (i // columns) * (th + 30)
        sheet.paste(Image.fromarray(r["image"]).resize((STRIP_THUMB_W, th), Image.Resampling.BILINEAR), (x, y))
        draw.rectangle([x - 2, y - 2, x + STRIP_THUMB_W + 1, y + th + 1], outline=colours[r["kind"]], width=2)
        draw.text((x, y + th + 4), f"+{r['t_ms']:.0f}ms {r['kind']} ({r['shown_ms']:.0f}ms) a={r['alpha']}",
                  fill=colours[r["kind"]])
    sheet.save(path)


def screen_backdrop_main(stop):
    """A plain full-screen window, so main-window captures never show the desktop."""
    import tkinter as tk
    if IS_WINDOWS:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    root = tk.Tk()
    root.configure(bg="#808088")
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)

    def poll():
        if stop.is_set():
            root.destroy()
        else:
            root.after(100, poll)
    poll()
    root.mainloop()


def run_case(capture, scenario, approach, repeat):
    ctx = mp.get_context("spawn")
    backdrop_stop, backdrop = ctx.Event(), None
    if scenario == "main_window":
        backdrop = ctx.Process(target=screen_backdrop_main, args=(backdrop_stop,), daemon=True)
        backdrop.start()
        time.sleep(1.5)
    out_q = ctx.Queue()
    workdir = OUTPUT_DIR / "work" / f"{scenario}-{approach}-{repeat}"
    workdir.mkdir(parents=True, exist_ok=True)
    process = ctx.Process(target=case_main, args=(scenario, approach, out_q, str(workdir)), daemon=True)
    process.start()
    stop = threading.Event()
    holder = {}
    result, error = None, None
    deadline = time.time() + CASE_TIMEOUT_S
    thread = None
    try:
        while time.time() < deadline:
            try:
                message = out_q.get(timeout=0.5)
            except queue.Empty:
                if not process.is_alive():
                    break
                continue
            if message[0] == "region" and capture is not None:
                x, y, w, h, down = holder["region"] = message[1]
                thread = threading.Thread(target=lambda: holder.update(
                    zip(("frames", "missed"), capture.record((x, y, w, h), stop, down))), daemon=True)
                thread.start()
            elif message[0] == "result":
                result = message[1]
            elif message[0] == "error":
                error = message[1]
            elif message[0] == "done":
                break
            if result is not None and message[0] == "mark" and message[1] == "finish":
                pass
    finally:
        case_end = time.perf_counter()
        time.sleep(0.2)
        stop.set()
        if thread is not None:
            thread.join(timeout=5)
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
        if backdrop is not None:
            backdrop_stop.set()
            backdrop.join(timeout=5)
            if backdrop.is_alive():
                backdrop.kill()
    if error or result is None:
        return {"error": error or "no result (timeout)"}
    finish = next((t for t, label in result["marks"] if label == "finish"), case_end)
    frames = holder.get("frames", [])
    if scenario == "main_window":
        result["full_mask"] = True
    segments = analyse(frames, result, finish, holder.get("region"))
    busy = sorted(getattr(capture, "busy_ms", []) or [0])
    return {"segments": segments, "missed": holder.get("missed"),
            "capture_ms": (round(busy[len(busy) // 2], 1), round(busy[-1], 1)), "settles": result["settles"],
            "profile": result["profile"], "frames_total": len(frames), "result": result}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    capture = None
    if IS_WINDOWS:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        # Keep the display on: a display in power save presents no frames.
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x2)   # ES_CONTINUOUS | ES_DISPLAY_REQUIRED
        try:
            capture = DesktopCapture()
        except OSError as exc:
            print(f"Desktop capture unavailable ({exc}); Tk-side metrics only.")
    else:
        print("Desktop capture is Windows-only; Tk-side metrics only.")
    summary = []
    for scenario, approach in CASES:
        for repeat in range(REPEATS):
            outcome = run_case(capture, scenario, approach, repeat)
            if "error" in outcome:
                print(f"{scenario:15} {approach:20} r{repeat}: ERROR {outcome['error'].strip().splitlines()[-1]}")
                summary.append({"scenario": scenario, "approach": approach, "repeat": repeat, "error": outcome["error"]})
                continue
            for seg in outcome["segments"]:
                if repeat == 0:
                    frame_strip(OUTPUT_DIR / f"strip_{scenario}_{approach}_{seg['segment']}.png",
                                f"{scenario} / {approach} / {seg['segment']}", seg["rows"])
                row = {k: v for k, v in seg.items() if k != "rows"}
                row.update(scenario=scenario, approach=approach, repeat=repeat, missed=outcome["missed"],
                           capture_ms=outcome["capture_ms"],
                           settle_passes=[s["passes"] for s in outcome["settles"]],
                           settle_ms=[s["ms"] for s in outcome["settles"]], profile=outcome["profile"],
                           kinds="".join(r["kind"][0] for r in seg["rows"]))
                summary.append(row)
                capture_note = "" if outcome["frames_total"] else " [NO FRAMES CAPTURED: screen locked/off?]"
                print(f"{scenario:15} {approach:20} r{repeat} {seg['segment']:7} dirty={seg['dirty']:2} "
                      f"({seg['dirty_ms']:6.1f} ms) blend={seg['blend']:2} visible={seg['visible_ms']} "
                      f"settled={seg['settled_ms']} reveal={seg['reveal_ms']} tk_after={seg['tk_changes_after_reveal']:3} "
                      f"kinds={row['kinds'][:40]} capture_ms(med,max)={outcome['capture_ms']}{capture_note}", flush=True)
    (OUTPUT_DIR / "results.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print_table(summary)
    print(f"\nFrame strips and results.json: {OUTPUT_DIR}")


def print_table(summary):
    from statistics import median
    groups = {}
    for row in summary:
        if "error" in row:
            continue
        groups.setdefault((row["scenario"], row["segment"], row["approach"]), []).append(row)
    print("\nscenario        segment approach             dirty(max) dirty_ms(med) visible_ms(med) settled_ms(med) tk_after(max)")
    for (scenario, segment, approach), rows in groups.items():
        med = lambda key: median([r[key] for r in rows if r[key] is not None] or [float("nan")])
        print(f"{scenario:15} {segment:7} {approach:20} {max(r['dirty'] for r in rows):10} {med('dirty_ms'):13.1f} "
              f"{med('visible_ms'):15.1f} {med('settled_ms'):15.1f} {max(r['tk_changes_after_reveal'] for r in rows):13}")


if __name__ == "__main__":
    main()
