"""Load a coworker's JSON through the real wizard and freeze it per video."""
import json
from dataclasses import replace
from pathlib import Path
from tkinter import ttk

import pytest

from adapters import config
from adapters.coding_configs import CodingConfigStore
from domain.coding_setup import default_coding_setup
from gui_driver import click, dismiss_dialog, find_toplevel, find_widget, load_video, save

pytestmark = pytest.mark.gui


def test_shared_json_prefills_wizard_and_reopening_uses_frozen_copy(app, workspace):
    store = CodingConfigStore(Path(config.get_config_path()).parent / "config")
    setup = replace(
        default_coding_setup("general"), name="Coworker looking protocol",
        zone_labels={"1": "Target"},
        channel_labels={"RH": "Observer", "LH": "Target", "RL": "Object", "LL": "Background"},
        parameter_labels={"Par1": "Looking", "Par2": "P2", "Par3": "P3"},
    )
    store.save(setup, "coding_look.json")
    workspace.chosen_video = str(workspace.video)
    dismiss_dialog(app, "Video library", "Load new video")
    dismiss_dialog(app, "Select Mode", "Continue", radio_text="Normal")
    state = {"selected": False, "errors": [], "attempts": 0, "timer": None}

    def advance():
        state["attempts"] += 1
        window = find_toplevel(app, "Prepare video")
        try:
            if state["attempts"] > 250:
                raise AssertionError("Coding wizard did not complete")
            if window is not None:
                if not state["selected"]:
                    picker = find_widget(window, cls=ttk.Combobox)
                    assert "coding_look" in picker.cget("values")
                    picker.set("coding_look")
                    click(window, "Use configuration")
                    state["selected"] = True
                button = find_widget(window, text="Next", cls=ttk.Button)
                if button is not None:
                    button.invoke()
                else:
                    click(window, "Prepare video")
                    return
            state["timer"] = app.after(20, advance)
        except Exception as exc:
            state["errors"].append(exc)
            if window is not None:
                window.destroy()

    state["timer"] = app.after(20, advance)
    try:
        app.load_video_btn.invoke()
    finally:
        if state["timer"]:
            app.after_cancel(state["timer"])
    assert not state["errors"]
    assert state["selected"]
    assert app.coding_setup == setup
    assert app.state_repo.load_preparation_state() == "ready"
    assert app.par1_btn.cget("text") == "Looking"
    assert find_widget(app.mode_controls_frame, text="Observer") is not None
    store.save(replace(setup, name="Changed protocol", zone_labels={"1": "Changed target"}), "coding_look.json", overwrite=True)
    load_video(app, workspace, workspace.video)
    assert app.coding_setup == setup
    save(app)
    metadata = json.loads(Path(workspace.project().export_metadata).read_text(encoding="utf-8"))
    assert metadata["Coding Setup"] == setup.to_dict()
    assert metadata["Coding Setup"]["channel_labels"]["Channel1"] == "Observer"
    assert not workspace.errors()
