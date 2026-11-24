"""Window reveal (gui.window_reveal): no window is seen before it has settled.

Tk-side checks, so they run on any platform with a display (skipped without
one); the screen-capture check is tests/e2e/test_window_reveal_visual.py.
Nothing shows on screen: the root sits off-screen at alpha 0, and the hook's
alpha changes are recorded instead of applied (every window stays at 0).

For every dialog the app opens: it becomes visible in one step (alpha 0 -> 1,
nothing in between), after its placement ran, and no widget in it changes
geometry after that moment.
"""
import time
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

import pytest

from adapters import config
from gui import theme, window_reveal

HOLD_MS = 300          # watch this long after a reveal for late geometry changes
OPEN_TIMEOUT_S = 5


@pytest.fixture(scope="module")
def root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    root.geometry("1000x760+6000+6000")
    root.attributes("-alpha", 0.0)
    theme.init_style(root, "light")
    root.update()
    yield root
    root.destroy()


class Probe:
    """Records alpha changes, <Configure> changes and placement calls."""

    def __init__(self, root, monkeypatch):
        self.root = root
        self.alpha = []        # (t, window path, value)
        self.changes = []      # (t, toplevel path, widget path, (x, y, w, h))
        self.placed = {}       # window path -> place() calls
        self.errors = []
        self._geometry = {}
        real_alpha = window_reveal._set_alpha

        def set_alpha(window, value):
            self.alpha.append((time.perf_counter(), str(window), float(value)))
            real_alpha(window, 0.0)
        monkeypatch.setattr(window_reveal, "_set_alpha", set_alpha)
        real_place = window_reveal.place_on_reveal

        def place_on_reveal(window, place):
            path = str(window)
            self.placed.setdefault(path, 0)

            def counted():
                self.placed[path] += 1
                place()
            real_place(window, counted)
        monkeypatch.setattr(window_reveal, "place_on_reveal", place_on_reveal)
        monkeypatch.setattr(root, "report_callback_exception",
                            lambda *exc: self.errors.append(exc), raising=False)
        root.bind_all("<Configure>", self._configure, add="+")

    def close(self):
        self.root.unbind_all("<Configure>")

    def _configure(self, event):
        widget = event.widget
        if isinstance(widget, str):
            return
        key = str(widget)
        geometry = (event.x, event.y, event.width, event.height)
        if self._geometry.get(key) != geometry:
            self._geometry[key] = geometry
            try:
                top = str(widget.winfo_toplevel())
            except tk.TclError:
                top = "?"
            self.changes.append((time.perf_counter(), top, key, geometry))

    def alphas(self, window):
        return [value for _, path, value in self.alpha if path == str(window)]

    def revealed_at(self, window):
        return next(t for t, path, value in self.alpha if path == str(window) and value > 0)

    def changes_after(self, window, t):
        return [c for c in self.changes if c[0] > t and c[1] == str(window)]


@pytest.fixture
def probe(root, monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "get_config_path", lambda: str(config_path))
    monkeypatch.setattr(config, "get_app_dir", lambda: str(tmp_path))
    monkeypatch.setattr(window_reveal, "REVEAL_WHEN_SETTLED", True)
    probe = Probe(root, monkeypatch)
    yield probe
    probe.close()
    for child in root.winfo_children():
        if isinstance(child, (tk.Toplevel, tk.Frame)):
            child.destroy()
    root.update()


def pump(root, seconds):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        root.update()
        time.sleep(0.005)


def toplevels(widget):
    """Every tk.Toplevel below ``widget`` (dialogs may be children of a frame)."""
    found = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Toplevel):
            found.append(child)
        found.extend(toplevels(child))
    return found


def open_and_close(root, opener):
    """Run ``opener`` (it may block in wait_window); close its window HOLD_MS after the reveal."""
    before = set(toplevels(root))
    state = {"window": None, "closed": False, "timeout": False}
    deadline = time.perf_counter() + OPEN_TIMEOUT_S

    def new_windows():
        return [w for w in toplevels(root) if w not in before and w.winfo_exists()]

    def close():
        for window in new_windows():
            window.destroy()
        state["closed"] = True

    def poll():
        windows = new_windows()
        if windows and not window_reveal.is_pending(windows[0]):
            state["window"] = windows[0]
            root.after(HOLD_MS, close)
            return
        if time.perf_counter() > deadline:
            state["timeout"] = True
            close()
            return
        root.after(5, poll)

    root.after(5, poll)
    opener()
    while not state["closed"] and time.perf_counter() < deadline + 1:
        root.update()
        time.sleep(0.002)
    assert not state["timeout"], "the window was never revealed"
    return state["window"]


# --- the dialogs ------------------------------------------------------------------
class FakeApp(tk.Frame):
    """Just enough LabelingApp for open_settings / progress windows."""

    def __init__(self, root):
        super().__init__(root, width=900, height=700)
        self.place(x=0, y=0)
        self.config = SimpleNamespace(appearance="light", video_renderer="cpu")
        self._renderer_status = tk.StringVar(master=root, value="CPU")
        self.zone_display = SimpleNamespace(show_names=False, labels={})
        self.video = None
        self.coding_setup = None
        self.diagram_scale = 1.0
        self.labeling_mode = "Normal"
        for name in ("change_project_template", "edit_project_zone_names", "_open_logs_folder",
                     "apply_runtime_settings", "_save_zone_display", "_assert_ui_thread"):
            setattr(self, name, lambda *a, **k: True)
        from labeling_app import LabelingApp
        self._format_duration = lambda seconds: LabelingApp._format_duration(self, seconds)


def _openers():
    from gui import app_dialogs
    from gui.app_dialogs import center_over_parent
    from gui.coding_setup_wizard import configure_video
    from gui.frame_dialog import FrameDialog
    from gui.open_touches_dialog import OpenTouchesDialog
    from gui.special_zones_app import SpecialZonesApp
    from gui.template_dialog import choose_template
    from gui.video_library import choose_existing_video, choose_video
    from gui.zone_names_dialog import edit_zone_names
    from domain.templates import TEMPLATE_LABELS
    from domain.zone_display import ZoneDisplaySettings
    import labeling_app

    template = next(iter(TEMPLATE_LABELS))
    entries = [SimpleNamespace(title=f"Video {i}", thumbnail=None, template=template, annotation_type="Touch",
                               preparation_state=("ready", "draft", None)[i % 3], setup_name="", source="x.mp4")
               for i in range(5)]
    from domain.touch import OpenTouch
    # The real record, so a field the dialog starts to read cannot be missing here.
    touches = [OpenTouch("LH", 10 * i, 10 * i) for i in range(3)]

    def progress_copy(root):
        update, close = labeling_app.LabelingApp._open_progress_window(FakeApp(root), "Copying Video", "Copying...")
        update(0, 100, "Starting...", 0.0)   # the copy loop's first report pumps events

    def progress_frames(root):
        import threading
        # Short work: the window closes itself (an outside destroy would leave its poll timer dangling).
        worker = threading.Thread(target=time.sleep, args=(0.25,), daemon=True)
        job = SimpleNamespace(thread=worker, cancel_event=threading.Event(), progress=None,
                              start=worker.start, cancel=lambda: None)
        labeling_app.LabelingApp._open_progress_window(FakeApp(root), "Preparing", "Frames", frame_job=job)

    def export(root):
        labeling_app.LabelingApp._run_export_with_progress(FakeApp(root), lambda: time.sleep(0.25))

    return {
        "confirm_close": lambda root: app_dialogs.custom_confirm_close(root),
        "labeling_mode": lambda root: app_dialogs.ask_labeling_mode(root),
        "settings": lambda root: app_dialogs.open_settings(FakeApp(root)),
        "frame_dialog": lambda root: FrameDialog(root, 10, 1000),
        "open_touches": lambda root: OpenTouchesDialog(root, touches, lambda limb: limb),
        "template": lambda root: choose_template(root, template, center=center_over_parent),
        "zone_names": lambda root: edit_zone_names(root, [f"Z{i}" for i in range(12)], ZoneDisplaySettings(),
                                                   lambda labels: True, center=center_over_parent),
        "special_zones": lambda root: SpecialZonesApp(root, lambda *a, **k: None, lambda *a, **k: None),
        "progress_copy": progress_copy,
        "progress_frames": progress_frames,
        "export": export,
        "library": lambda root: choose_video(root, entries, center=center_over_parent),
        "duplicate": lambda root: choose_existing_video(root, "a.mp4", "a (2).mp4", center=center_over_parent),
        "wizard": lambda root: configure_video(root, None, center=center_over_parent),
    }


# simpledialog places itself (no placement callback); the rest register one.
UNPLACED = {"frame_dialog"}


@pytest.mark.parametrize("name", list(_openers()))
def test_dialog_appears_settled_in_one_step(root, probe, name):
    window = open_and_close(root, lambda: _openers()[name](root))

    assert probe.alphas(window) == [0.0, 1.0]   # hidden at creation, shown once, no fade steps
    revealed = probe.revealed_at(window)
    assert probe.changes_after(window, revealed) == [], "geometry changed after the window was shown"
    if name not in UNPLACED:
        assert probe.placed.get(str(window)) == 1, "placement did not run before the reveal"
    assert not probe.errors


# --- edge cases ---------------------------------------------------------------------
def _record_focus_force(monkeypatch, probe):
    forced = []
    monkeypatch.setattr(tk.Misc, "focus_force",
                        lambda widget: forced.append((time.perf_counter(), str(widget))))
    return forced


def test_revealed_dialog_takes_keyboard_focus_on_its_focused_widget(root, probe, monkeypatch):
    # deiconify used to activate dialogs; a revealed (never deiconified) modal
    # must still take focus, or Escape and typing go to the main window.
    forced = _record_focus_force(monkeypatch, probe)
    window = tk.Toplevel(root)
    entry = ttk.Entry(window)
    entry.pack()
    entry.focus_set()
    pump(root, 0.3)

    assert not window_reveal.is_pending(window)
    assert [path for _, path in forced] == [str(entry)]
    assert forced[0][0] >= probe.revealed_at(window), "focused before the window was visible"


def test_borderless_popup_is_not_activated(root, probe, monkeypatch):
    forced = _record_focus_force(monkeypatch, probe)
    popup = tk.Toplevel(root)
    popup.overrideredirect(True)
    ttk.Label(popup, text="list").pack()
    pump(root, 0.3)

    assert forced == []


def test_window_destroyed_before_reveal_is_harmless(root, probe):
    window = tk.Toplevel(root)
    ttk.Label(window, text="gone").pack()
    window_reveal.place_on_reveal(window, lambda: pytest.fail("placed a destroyed window"))
    root.update_idletasks()   # mapped (alpha 0): the reveal is queued
    window.destroy()
    pump(root, 0.2)

    assert not probe.errors


def test_settle_is_capped_for_a_window_that_never_settles(root, probe, monkeypatch):
    monkeypatch.setattr(window_reveal, "REVEAL_BUDGET_MS", 150)
    window = tk.Toplevel(root)
    times = {}

    def spin():   # idle work that keeps coming for 0.8 s; an uncapped settle would wait for all of it
        if time.perf_counter() < times["stop"]:
            window.after_idle(spin)

    def start_spinning(event):
        if event.widget is window and "stop" not in times:
            times["mapped"] = time.perf_counter()
            times["stop"] = times["mapped"] + 0.8
            spin()
    window.bind("<Map>", start_spinning, add="+")
    pump(root, 1.2)

    assert probe.alphas(window) == [0.0, 1.0]
    assert probe.revealed_at(window) - times["mapped"] < 0.5
    window.destroy()


def test_reveal_started_inside_another_reveal(root, probe):
    """B is created while A settles (A's placement opens it): both reveal, once each."""
    a = tk.Toplevel(root)
    ttk.Label(a, text="A").pack()
    created = {}

    def place_a():
        b = created["b"] = tk.Toplevel(root)
        ttk.Label(b, text="B").pack()
        window_reveal.place_on_reveal(b, lambda: b.geometry("+40+40"))
        window_reveal.settle(b)   # B maps and reveals inside A's reveal
    window_reveal.place_on_reveal(a, place_a)
    pump(root, 0.3)

    assert probe.alphas(a) == [0.0, 1.0]
    assert probe.alphas(created["b"]) == [0.0, 1.0]
    assert probe.placed == {str(a): 1, str(created["b"]): 1}
    assert not probe.errors


def test_nested_modal_during_a_reveal_cannot_keep_the_window_hidden(root, probe, monkeypatch):
    """A modal entered from a settle (say, a key press) runs a full event loop:
    the watchdog shows the pending window instead of leaving it invisible."""
    monkeypatch.setattr(window_reveal, "REVEAL_WATCHDOG_MS", 100)
    a = tk.Toplevel(root)
    times = {}

    def place_a():
        modal = tk.Toplevel(root)
        root.after(500, modal.destroy)
        modal.wait_window()
        times["modal_closed"] = time.perf_counter()
    window_reveal.place_on_reveal(a, place_a)
    pump(root, 0.8)

    assert probe.alphas(a) == [0.0, 1.0]
    assert probe.revealed_at(a) < times["modal_closed"]


def test_withdraw_and_deiconify_settles_again(root, probe):
    window = tk.Toplevel(root)
    ttk.Label(window, text="again").pack()
    pump(root, 0.2)
    window.withdraw()
    pump(root, 0.1)
    window.deiconify()
    pump(root, 0.2)

    assert probe.alphas(window) == [0.0, 1.0, 0.0, 1.0]
    window.destroy()


def test_borderless_dropdown_appears_without_a_settle(root, probe, monkeypatch):
    from gui.widgets import DropdownList
    settles = []
    real_settle = window_reveal.settle
    monkeypatch.setattr(window_reveal, "settle", lambda widget: settles.append(widget) or real_settle(widget))
    combo = ttk.Combobox(root, values=("One", "Two"), state="readonly")
    combo.place(x=10, y=10)
    root.update()
    dropdown = DropdownList(combo)
    root.update()   # the <Map> event

    assert probe.alphas(dropdown.top) == [0.0, 1.0]
    assert settles == []
    dropdown.close()
    combo.destroy()


def test_modal_grab_before_the_window_is_mapped(root, probe):
    window = tk.Toplevel(root)
    assert not window.winfo_ismapped()
    window_reveal.modal_grab(window)
    pump(root, 0.2)

    assert window.grab_current() is window
    window.destroy()


def test_modal_grab_is_deferred_when_the_window_is_not_viewable(root, probe, monkeypatch):
    window = tk.Toplevel(root)
    calls = []
    real_grab = window.grab_set

    def grab_set():
        calls.append(window.winfo_ismapped())
        if len(calls) == 1:
            raise tk.TclError("grab failed: window not viewable")   # X11 with a button held
        real_grab()
    monkeypatch.setattr(window, "grab_set", grab_set)
    window_reveal.modal_grab(window)
    pump(root, 0.2)

    assert calls == [False, True]
    assert window.grab_current() is window
    window.destroy()


def test_hook_off_places_at_once(root, probe, monkeypatch):
    monkeypatch.setattr(window_reveal, "REVEAL_WHEN_SETTLED", False)
    window = tk.Toplevel(root)
    placed = []
    window_reveal.place_on_reveal(window, lambda: placed.append(True))
    window_reveal.on_reveal(window, lambda: placed.append("shown"))

    assert placed == [True, "shown"]
    assert probe.alphas(window) == []
    window.destroy()


def test_offscreen_fallback_moves_into_view_only_once_settled(root, probe, monkeypatch):
    """X11 without a compositor: the window settles off-screen, then moves into view."""
    from gui.template_dialog import choose_template
    from gui.app_dialogs import center_over_parent
    from domain.templates import TEMPLATE_LABELS
    monkeypatch.setattr(window_reveal, "_reveal_mode_cache", ["offscreen"])
    real_init = tk.Toplevel.__init__

    def init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        self.wm_attributes("-alpha", 0.0)   # invisible during the test; the hook does not use alpha here
    monkeypatch.setattr(tk.Toplevel, "__init__", init)
    window = open_and_close(root, lambda: choose_template(root, next(iter(TEMPLATE_LABELS)),
                                                          center=center_over_parent))
    in_view = [t for t, top, widget, (x, y, w, h) in probe.changes
               if widget == str(window) and x < window_reveal.REVEAL_OFFSCREEN_XY // 2]

    assert probe.alphas(window) == []        # no alpha in this mode
    assert probe.placed[str(window)] == 1
    assert len(in_view) == 1                 # one move into view ...
    assert probe.changes_after(window, in_view[0]) == []   # ... of a finished window


# --- the main window ----------------------------------------------------------------
def test_root_path_is_cloaked_while_built_and_shown_once_fitted(root, probe, monkeypatch):
    """The main window's path (Windows: withdraw + DWM cloak), on a stand-in window.

    The cloak is recorded, not applied; the window stays invisible at alpha 0.
    It is shown once, after its placement (the diagram fit) ran on the
    settled layout, and nothing changes geometry after that.
    """
    cloaks = []
    monkeypatch.setattr(window_reveal, "IS_WINDOWS", True)
    monkeypatch.setattr(window_reveal, "set_cloaked", lambda window, cloaked: cloaks.append(cloaked) or True)
    monkeypatch.setattr(window_reveal, "REVEAL_WHEN_SETTLED", False)
    window = tk.Toplevel(root)            # not armed by the Toplevel hook
    window.wm_attributes("-alpha", 0.0)
    window.geometry("+6000+6000")
    monkeypatch.setattr(window_reveal, "REVEAL_WHEN_SETTLED", True)
    window_reveal.hide_root_until_settled(window)
    assert window.state() == "withdrawn" and cloaks == [True]
    assert window_reveal.is_pending(window)

    for i in range(6):                    # the build, while withdrawn
        ttk.Label(window, text=f"row {i}").pack()
    fitted = []

    def fit():
        fitted.append(window.winfo_ismapped())
        ttk.Label(window, text="fitted").pack()   # a layout change, before the reveal
        cloaks.append("fit")
    window_reveal.place_on_reveal(window, fit)
    shown = []
    window_reveal.on_reveal(window, lambda: shown.append(time.perf_counter()))
    pump(root, 0.3)

    assert fitted == [True]               # fitted once, mapped, on the settled layout
    assert cloaks == [True, "fit", False]
    assert len(shown) == 1
    assert probe.changes_after(window, shown[0]) == []
    assert probe.alphas(window) == []     # the cloak path never makes the window layered
    window.destroy()


def test_root_is_left_alone_with_the_hook_off(root, probe, monkeypatch):
    monkeypatch.setattr(window_reveal, "REVEAL_WHEN_SETTLED", False)
    window = tk.Toplevel(root)
    window.wm_attributes("-alpha", 0.0)
    window_reveal.hide_root_until_settled(window)

    assert window.state() == "normal"
    assert not window_reveal.is_pending(window)
    window.destroy()
