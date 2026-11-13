"""Content swap (gui.content_swap): the cover's lifetime around ``build`` and ``ready``.

Tk-side, so the logic runs on any platform with a display (skipped without
one): the cover is replaced by a recording stand-in. The Windows-only tests
use the real Win32 cover over a root that sits off-screen, so nothing shows.
"""
import sys
import time
import tkinter as tk

import pytest

from gui import content_swap, theme

TIMEOUT_MS = 300
SLACK_S = 1.5            # settle budget + event-loop latency allowed past a deadline


@pytest.fixture(scope="module")
def root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    root.geometry("400x300+6000+6000")
    root.attributes("-alpha", 0.0)
    theme.init_style(root, "light")
    root.update()
    yield root
    root.destroy()


class FakeCover:
    def __init__(self, log):
        self.log = log
        self.showing = True
        self.closed_at = None
        log.append("cover")

    def close(self):
        self.closed_at = time.perf_counter()
        self.showing = False
        self.log.append("close")


@pytest.fixture
def covers(root, monkeypatch):
    """Every swap gets a FakeCover; the list collects them."""
    made, log = [], []

    def over(window):
        made.append(FakeCover(log))
        return made[-1]
    monkeypatch.setattr(content_swap, "IS_WINDOWS", True)
    monkeypatch.setattr(content_swap, "_opaque", lambda window: True)
    monkeypatch.setattr(content_swap._Cover, "over", staticmethod(over))
    yield SimpleLog(made, log)
    assert content_swap._active is False


class SimpleLog:
    def __init__(self, made, log):
        self.made, self.log = made, log


def test_cover_stays_until_ready_then_is_removed(root, covers):
    state = {"ready": False}

    def build():
        covers.log.append("build")
        root.after(80, lambda: state.update(ready=True))   # a frame painted from a timer
        return "built"

    started = time.perf_counter()
    result = content_swap.swap_content(root, build, ready=lambda: state["ready"], timeout_ms=5000)

    assert result == "built"
    assert covers.log == ["cover", "build", "close"]
    assert state["ready"], "the cover came down before ready() was true"
    assert covers.made[0].closed_at - started < 5000 / 1000 / 2, "waited for the timeout instead of ready()"


def test_cover_is_removed_at_the_timeout_when_never_ready(root, covers):
    started = time.perf_counter()
    content_swap.swap_content(root, lambda: None, ready=lambda: False, timeout_ms=TIMEOUT_MS)
    elapsed = covers.made[0].closed_at - started

    assert covers.log == ["cover", "close"]
    assert TIMEOUT_MS / 1000 <= elapsed < TIMEOUT_MS / 1000 + SLACK_S


def test_build_error_removes_the_cover_and_propagates(root, covers):
    asked = []

    def build():
        raise ValueError("load failed")

    with pytest.raises(ValueError, match="load failed"):
        content_swap.swap_content(root, build, ready=lambda: asked.append(1) or False, timeout_ms=5000)
    assert covers.log == ["cover", "close"]
    assert not asked, "ready() was waited for after a failed build"


def test_ready_error_removes_the_cover_and_propagates(root, covers):
    def ready():
        raise RuntimeError("predicate failed")

    with pytest.raises(RuntimeError, match="predicate failed"):
        content_swap.swap_content(root, lambda: None, ready=ready, timeout_ms=5000)
    assert covers.log == ["cover", "close"]


def test_wait_ends_when_the_cover_was_dropped_for_another_window(root, covers):
    def build():
        root.after(50, lambda: setattr(covers.made[0], "showing", False))   # a dialog activated

    started = time.perf_counter()
    content_swap.swap_content(root, build, ready=lambda: False, timeout_ms=5000)
    assert covers.made[0].closed_at - started < 5000 / 1000 / 2


def test_without_a_cover_ready_is_not_waited_for(root, covers, monkeypatch):
    monkeypatch.setattr(content_swap, "SWAP_COVER", False)
    started = time.perf_counter()
    assert content_swap.swap_content(root, lambda: 7, ready=lambda: False, timeout_ms=5000) == 7
    assert time.perf_counter() - started < 5000 / 1000 / 2
    assert covers.made == []


def test_nested_swap_only_builds(root, covers):
    inner = content_swap.swap_content
    result = content_swap.swap_content(root, lambda: inner(root, lambda: "inner", ready=lambda: False))
    assert result == "inner"
    assert len(covers.made) == 1


# --- the real Win32 cover ---------------------------------------------------------
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Win32 cover")


def _visible(hwnd):
    import ctypes
    user32 = ctypes.WinDLL("user32")
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    return bool(user32.IsWindowVisible(hwnd))


@pytest.fixture
def real_cover(root, monkeypatch):
    made = []
    real_over = content_swap._Cover.over

    def over(window):
        made.append(real_over(window))
        return made[-1]
    monkeypatch.setattr(content_swap, "_opaque", lambda window: True)
    monkeypatch.setattr(content_swap._Cover, "over", staticmethod(over))
    return made


@windows_only
def test_real_cover_is_shown_during_build_and_destroyed_after(root, real_cover):
    seen = {}

    def build():
        cover = real_cover[0]
        seen["hwnd"], seen["visible"] = cover.hwnd, _visible(cover.hwnd)

    content_swap.swap_content(root, build, ready=lambda: True)
    assert seen["visible"]
    assert real_cover[0].hwnd is None and real_cover[0].hook is None


@windows_only
def test_real_cover_is_hidden_when_a_dialog_activates(root, real_cover):
    seen = {}

    def build():
        dialog = tk.Toplevel(root)
        dialog.geometry("200x100+6100+6100")
        dialog.update()
        dialog.focus_force()
        dialog.update()
        seen["showing"], seen["visible"] = real_cover[0].showing, _visible(real_cover[0].hwnd)
        dialog.destroy()

    started = time.perf_counter()
    content_swap.swap_content(root, build, ready=lambda: False, timeout_ms=5000)
    assert seen == {"showing": False, "visible": False}
    assert time.perf_counter() - started < 5000 / 1000 / 2, "kept waiting after the cover was dropped"
