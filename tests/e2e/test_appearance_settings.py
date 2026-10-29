"""Exercise the actual Settings controls and live, loaded-project repaint."""

from tkinter import ttk

import pytest

from adapters import config
from gui import theme
from gui.special_zones_app import SpecialZonesApp
from gui_driver import click, find_toplevel, pump, walk

pytestmark = pytest.mark.gui


def test_settings_switches_both_ways_and_remembers_choice(loaded_app):
    app = loaded_app
    click(app, app.config.parameter1)
    click(app, app.config.limb_parameter1)
    frames = repr(app.video.frames)
    frame_index = app.video.current_frame
    app.note_entry.insert("1.0", "Unsaved note")
    special = SpecialZonesApp(app, None, None)
    app.open_settings()
    settings = find_toplevel(app, "Settings")
    picker = next(w for w in walk(settings) if isinstance(w, ttk.Combobox)
                  and tuple(w.cget("values")) == ("Light", "Dark"))

    for appearance in ("Dark", "Light", "Dark"):
        picker.set(appearance)
        click(settings, "Apply")
        pump(app, 0.1)
        assert config.load_app_config().appearance == appearance.lower()
        assert app.note_entry.get("1.0", "end-1c") == "Unsaved note"
        assert repr(app.video.frames) == frames
        assert app.video.current_frame == frame_index
        assert app.par1_btn.cget("style") == "StateOn.TButton"
        assert app.limb_par1_btn.cget("style") == "StateOn.TButton"
        assert app.cget("bg") == theme.SURFACE
        assert app.video_frame.cget("bg") == theme.VIDEO_BG
        assert app.timeline_canvas.cget("bg") == theme.SURFACE_ALT
        assert app.note_entry.cget("bg") == theme.NEUTRAL
        assert app.note_entry.cget("insertbackground") == theme.TEXT
        assert app.diagram_canvas.cget("bg") == "#ffffff"
        assert special.canvas2.cget("bg") == "#ffffff"
        assert special.top_level.cget("bg") == theme.SURFACE
        assert settings.cget("bg") == theme.SURFACE
        assert app.style.lookup("Tool.TButton", "foreground") == theme.TEXT
        assert app.style.lookup("StateOn.TButton", "background") == theme.ON_GREEN
        fills = {app.timeline_canvas.itemcget(item, "fill")
                 for item in app.timeline_canvas.find_all()}
        assert theme.TL_EMPTY in fills

    click(settings, "Close")


def test_startup_uses_saved_dark_appearance(workspace, app_factory):
    saved = config.load_config()
    saved["appearance"] = "dark"
    config.save_config(saved)
    restarted = app_factory()
    assert restarted.config.appearance == "dark"
    assert restarted.cget("bg") == theme.SURFACE
    assert restarted.style.theme.type == "dark"
