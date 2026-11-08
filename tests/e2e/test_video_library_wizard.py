"""Real wizard controls preserve drafts, save configuration, and freeze preparation."""
import pytest

import labeling_app
from gui.coding_setup_wizard import CodingSetupWizard
from gui_driver import click, pump, load_video, find_button, walk, dismiss_dialog
from domain.coding_setup import default_coding_setup
from adapters.coding_configs import CodingConfigStore
from adapters import config
from pathlib import Path

pytestmark = pytest.mark.gui


def test_wizard_back_and_configuration_save(app, workspace):
    original = default_coding_setup("general")
    wizard = CodingSetupWizard(app, original)
    click(wizard.win, "Next")
    pump(app)
    zone = next(iter(wizard.variables))
    wizard.variables[zone].set("Study zone")
    click(wizard.win, "Next")
    wizard.variables["RH"].set("Camera channel")
    wizard.variables["P1"].set("Attention")
    click(wizard.win, "Back")
    assert wizard.variables[zone].get() == "Study zone"
    click(wizard.win, "Next")
    assert wizard.variables["RH"].get() == "Camera channel"
    assert wizard.variables["P1"].get() == "Attention"
    click(wizard.win, "Next")
    wizard.variables["save_name"].set("Study coding")
    click(wizard.win, "Prepare video")
    assert original.channel_labels["RH"] == "Channel 1"
    assert wizard.result.zone_labels[zone] == "Study zone"
    store = CodingConfigStore(Path(config.get_config_path()).parent / "config")
    saved, = store.list_configs()
    assert store.load(saved) == wizard.result


def test_prepared_video_resumes_without_setup(app, workspace, monkeypatch):
    load_video(app, workspace, workspace.video, template="General")
    assert app.state_repo.load_preparation_state() == "ready"
    assert app.state_repo.load_template().locked
    setup = app.coding_setup
    # Opening the library and cancelling leaves this exact project alive.
    dismiss_dialog(app, "Video library", "Cancel")
    app.load_video_btn.invoke()
    assert app.coding_setup == setup
    assert app.video is not None
    def unexpected(*args, **kwargs):
        raise AssertionError("Ready video repeated coding setup")
    monkeypatch.setattr("labeling_app.configure_video", unexpected)
    dismiss_dialog(app, "Video library", "Resume")
    app.load_video_btn.invoke()
    assert app.coding_setup == setup
    assert workspace.errors() == []
    app.open_settings()
    if labeling_app.SETTINGS_SHOW_ZONE_NAME_EDITOR:
        assert str(find_button(app._settings_win, "Edit zone names").cget("state")) == "disabled"
    app._settings_win.destroy()


def test_library_missing_thumbnail_and_search(app):
    import tkinter as tk
    from gui.video_library import choose_video
    from adapters.project_catalog import LibraryEntry
    from domain.project import ProjectPaths
    from gui_driver import find_toplevel, find_widget
    from tkinter import ttk
    entry = LibraryEntry(ProjectPaths("Study clip"), None, "general", "draft", None)
    observed = []
    def inspect():
        window = find_toplevel(app, "Video library")
        if window is None:
            app.after(20, inspect)
            return
        assert find_widget(window, cls=ttk.Label, text="No thumbnail") is not None
        assert all(widget.cget("style") == "Tool.TButton" for widget in walk(window) if isinstance(widget, ttk.Button))
        search = next(widget for widget in walk(window) if isinstance(widget, ttk.Entry))
        search.insert(0, "unmatched")
        pump(app)
        assert find_widget(window, cls=ttk.Label, text="No videos yet. Select Load new video to begin.") is not None
        observed.append(True)
        click(window, "Cancel")
    app.after(20, inspect)
    assert choose_video(app, [entry]) is None
    assert observed


def test_general_zone_review_lists_channel_boxes_as_editable_zones(app):
    from PIL import ImageTk, ImageChops
    from gui_driver import find_widget
    from tkinter import ttk
    from domain.templates import general_footer_box, get_template
    wizard = CodingSetupWizard(app, default_coding_setup("general"))
    click(wizard.win, "Next")
    pump(app)
    assert find_widget(wizard.win, cls=ttk.LabelFrame, text="Reserved channel selectors") is None
    for index in range(1, 5):
        assert find_widget(wizard.win, cls=ttk.Label, text=str(index + 8)) is not None
        assert str(index + 8) in wizard.variables
    assert not set(wizard.setup.channel_labels).intersection(wizard.variables)
    # Highlighting a channel zone tints its own box and nothing else. (Capture
    # both images without pumping: a pending <FocusIn> on the first entry
    # would otherwise re-highlight zone `1` in between.)
    wizard.highlight_zone(None)
    before = ImageTk.getimage(wizard.zone_photo).convert("RGB")  # RGBA getbbox() looks at alpha only
    wizard.highlight_zone("10")
    after = ImageTk.getimage(wizard.zone_photo).convert("RGB")
    scale = before.width / get_template("general").native_size[0]
    for index in range(4):
        left, top, right, bottom = general_footer_box(index)
        box = tuple(round(value * scale) for value in (left + 4, top + 4, right - 4, bottom - 4))
        changed = ImageChops.difference(before.crop(box), after.crop(box)).getbbox() is not None
        assert changed == (index == 1)
    click(wizard.win, "Cancel")


def test_general_zone_names_do_not_change_channel_names(app):
    wizard = CodingSetupWizard(app, default_coding_setup("general"))
    click(wizard.win, "Next")
    wizard.variables["9"].set("Mother")
    wizard.variables["10"].set("Toy")
    click(wizard.win, "Next")
    assert wizard.variables["RH"].get() == "Channel 1"
    assert wizard.variables["LH"].get() == "Channel 2"
    assert wizard.variables["RL"].get() == "Channel 3"
    wizard.variables["LH"].set("Favourite toy")  # typed by hand: must survive
    click(wizard.win, "Back")
    wizard.variables["9"].set("Father")
    wizard.variables["10"].set("Ball")
    click(wizard.win, "Next")
    assert wizard.variables["RH"].get() == "Channel 1"
    assert wizard.variables["LH"].get() == "Favourite toy"
    click(wizard.win, "Cancel")


def test_general_footer_click_records_a_channel_zone_without_switching_channel(app, workspace):
    from domain.templates import general_footer_box
    from gui_driver import click_canvas, save, select_radio
    load_video(app, workspace, workspace.video, template="General")
    select_radio(app, "Channel 2")
    for index in range(4):
        left, top, right, bottom = general_footer_box(index)
        x = round((left + right) / 2 * app.diagram_scale)
        y = round((top + bottom) / 2 * app.diagram_scale)
        click_canvas(app.diagram_canvas, "<Button-1>", x, y)
        assert app.option_var_1.get() == "LH"
    assert app.video.frames[0]["LH"]["Zones"] == [[str(n)] for n in range(9, 13)]
    assert app.video.frames[0]["LH"]["Onset"] == "ON"
    save(app)  # leave no unsaved annotations behind for the fixture teardown
    assert workspace.errors() == []


def test_diagram_changes_update_only_default_labels(app):
    from dataclasses import replace
    from gui_driver import select_radio
    base = default_coding_setup("default")
    custom = replace(base,
        channel_labels={**base.channel_labels, "RH": "Study channel"},
        parameter_labels={**base.parameter_labels, "Par1": "Attention"},
        limb_parameter_labels={**base.limb_parameter_labels, "Par1": "Contact type"})
    wizard = CodingSetupWizard(app, custom)
    for template, caption in (("general", "General"), ("alternate", "Alternate")):
        select_radio(wizard.win, caption)
        click(wizard.win, "Next")
        expected = default_coding_setup(template)
        assert wizard.setup.template == template
        assert wizard.setup.channel_labels == {**expected.channel_labels, "RH": "Study channel"}
        assert wizard.setup.parameter_labels == {**expected.parameter_labels, "Par1": "Attention"}
        assert wizard.setup.limb_parameter_labels == {**expected.limb_parameter_labels, "Par1": "Contact type"}
        click(wizard.win, "Back")
    click(wizard.win, "Cancel")


def test_setup_actions_use_neutral_style_and_diagram_previews_select(app):
    from tkinter import ttk
    from gui_driver import find_widget
    wizard = CodingSetupWizard(app)
    def neutral_buttons(window):
        assert all(widget.cget("style") == "Tool.TButton" for widget in walk(window) if isinstance(widget, ttk.Button))
    neutral_buttons(wizard.win)
    preview = next(widget for widget in walk(wizard.win) if getattr(widget, "template_id", None) == "general")
    preview.event_generate("<Button-1>")
    click(wizard.win, "Next")
    assert wizard.setup.template == "general"
    click(wizard.win, "Next")
    assert find_widget(wizard.win, cls=ttk.LabelFrame, text="Channel names") is not None
    assert find_widget(wizard.win, cls=ttk.LabelFrame, text="Global parameters") is not None
    assert find_widget(wizard.win, cls=ttk.LabelFrame, text="Channel parameters") is not None
    neutral_buttons(wizard.win)
    click(wizard.win, "Cancel")
