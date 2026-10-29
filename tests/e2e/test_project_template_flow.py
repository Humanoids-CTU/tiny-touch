"""Researcher workflows for template choice, locking, special zones and reopening."""

import json
import shutil
import sqlite3
import tkinter as tk
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageTk

from gui.resource_utils import asset_path
from adapters.sqlite_repo import SqliteRepository
from gui_driver import (
    click, click_canvas, dismiss_dialog, find_button, find_toplevel, find_widget,
    load_video, pump, save, select_radio,
)


pytestmark = pytest.mark.gui


def _metadata(paths):
    connection = sqlite3.connect(Path(paths.state_db).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return dict(connection.execute("SELECT key, value FROM meta"))
    finally:
        connection.close()


@pytest.mark.parametrize("choice,template,folder,zone,native_point", [
    ("Default", "default", "zones3", "I", (192, 336)),
    ("Alternate", "alternate", "zones3_new_template", "G", (192, 336)),
    ("General", "general", "zones_general", "1", (137, 102)),
])
def test_special_zones_displays_selected_template_and_permanently_locks_it(
    app, workspace, choice, template, folder, zone, native_point,
):
    load_video(app, workspace, workspace.video, template=choice)
    paths = workspace.project()
    assert _metadata(paths)["template"] == template
    assert _metadata(paths)["template_locked"] == "0"

    click(app, "Special Zones")
    pump(app)
    window = find_toplevel(app, "Special Zones")
    canvas = find_widget(window, cls=tk.Canvas)
    # Inspect the image sent to Tk, rather than just its configured file path.
    rendered = ImageTk.getimage(app._special_zones_app.photo2).convert("RGB")
    with Image.open(asset_path(f"icons/{folder}/LINE.png")) as outline:
        expected = outline.convert("RGB").resize(rendered.size, Image.Resampling.LANCZOS)
    assert ImageChops.difference(rendered, expected).getbbox() is None

    scale = app._special_zones_app.diagram_scale
    point = tuple(int(value * scale) for value in native_point)
    click_canvas(canvas, "<Button-1>", *point)
    pump(app)
    # Lock is durable before the user presses Save in Special Zones.
    assert _metadata(paths)["template_locked"] == "1"
    app._special_zones_app.on_close()  # same handler as the window's close button
    connection = sqlite3.connect(paths.state_db)
    try:
        assert connection.execute("SELECT zones FROM special_zone_dots").fetchall() == [(zone,)]
    finally:
        connection.close()

    click(app, "Special Zones")
    pump(app)
    window = find_toplevel(app, "Special Zones")
    click_canvas(find_widget(window, cls=tk.Canvas), "<Button-2>", *point)
    app._special_zones_app.on_close()
    assert _metadata(paths)["template_locked"] == "1"
    save(app)
    assert json.loads(Path(paths.export_metadata).read_text())["template"] == template

    opposite = "Alternate" if choice == "Default" else "Default"
    load_video(app, workspace, workspace.video, template=opposite)
    assert _metadata(paths)["template"] == template
    assert any(title == "Saved template restored" for _, title, _ in workspace.messages)
    assert not workspace.errors()


def test_special_zones_note_locks_template_exports_and_reopens(app, workspace):
    load_video(app, workspace, workspace.video, template="Default")
    paths = workspace.project()

    click(app, "Special Zones")
    pump(app)
    app._special_zones_app.note_var.set("  diaper and socks ")
    app._special_zones_app.on_close()

    # A note alone locks the template but does not light the button.
    assert _metadata(paths)["template_locked"] == "1"
    assert _metadata(paths)["special_zones_note"] == "diaper and socks"
    assert str(app.special_zones_btn.cget("style")) == "StateNeutral.TButton"

    save(app)
    meta = json.loads(Path(paths.export_metadata).read_text(encoding="utf-8"))
    assert meta["Special Zones"] is None
    assert meta["Special Zones Note"] == "diaper and socks"

    click(app, "Special Zones")
    pump(app)
    assert app._special_zones_app.note_var.get() == "diaper and socks"
    app._special_zones_app.on_close()
    assert not workspace.errors()


def test_reliability_inherits_template_and_locks_both_empty_projects(app, workspace):
    load_video(app, workspace, workspace.video, template="Alternate")
    assert _metadata(workspace.project())["template_locked"] == "0"
    load_video(app, workspace, workspace.video, mode="Reliability", template="Default")
    assert app.video_name == "tiny_reliability"
    assert app.video.frames == {}
    for name in ("tiny", "tiny_reliability"):
        meta = _metadata(workspace.project(name))
        assert meta["template"] == "alternate"
        assert meta["template_locked"] == "1"
    save(app)
    metadata = Path(workspace.project("tiny_reliability").export_metadata)
    assert json.loads(metadata.read_text())["template"] == "alternate"
    assert not workspace.errors()


def test_close_template_does_not_open_file_picker_or_change_active_project(
    loaded_app, workspace, monkeypatch,
):
    app = loaded_app
    video_before = app.video
    meta_before = _metadata(workspace.project())

    def unexpected_file_picker(**kwargs):
        pytest.fail("File picker opened after template selection was cancelled")

    monkeypatch.setattr("tkinter.filedialog.askopenfilename", unexpected_file_picker)
    dismiss_dialog(app, "Select Mode", "Continue", radio_text="Reliability")
    closed = []

    def close_template():
        window = find_toplevel(app, "Template for new projects")
        if window is None:
            app.after(15, close_template)
            return
        closed.append(True)
        window.destroy()

    app.after(15, close_template)
    app.load_video_btn.invoke()
    assert closed
    assert app.video is video_before
    assert app.labeling_mode == "Normal"
    assert _metadata(workspace.project()) == meta_before
    assert not workspace.errors()


def test_switching_templates_updates_annotation_masks(app, workspace, tmp_path):
    alternate_video = tmp_path / "alternate.mp4"
    shutil.copy(workspace.video, alternate_video)
    load_video(app, workspace, workspace.video, template="Default")
    click_canvas(app.diagram_canvas, "<Button-1>", 96, 168)
    assert app.video.frames[0]["RH"]["Zones"] == [["I"]]
    load_video(app, workspace, alternate_video, template="Alternate")
    click_canvas(app.diagram_canvas, "<Button-1>", 96, 168)
    assert app.video.frames[0]["RH"]["Zones"] == [["G"]]
    load_video(app, workspace, workspace.video, template="Alternate")
    assert app.video.frames[0]["RH"]["Zones"] == [["I"]]
    assert not workspace.errors()


@pytest.mark.parametrize("choice,template,zone,native_point", [
    ("Alternate", "alternate", "G", (192, 336)),
    ("General", "general", "1", (137, 102)),
])
def test_empty_project_can_change_template_through_settings(
    loaded_app, workspace, choice, template, zone, native_point,
):
    app = loaded_app
    click(app, "Settings")
    settings = find_toplevel(app, "Settings")
    selected = dismiss_dialog(
        app, "Template for new projects", "Continue", radio_text=choice,
    )
    click(settings, "Change project template")
    assert selected["clicked"]
    assert _metadata(workspace.project())["template"] == template
    assert _metadata(workspace.project())["template_locked"] == "0"
    assert json.loads(Path(workspace.project().export_metadata).read_text())["template"] == template
    selector = "Channel 1" if template == "general" else "Right Hand"
    assert find_widget(app.mode_controls_frame, text=selector) is not None
    find_toplevel(app, "Settings").destroy()
    point = tuple(int(value * app.diagram_scale) for value in native_point)
    click_canvas(app.diagram_canvas, "<Button-1>", *point)
    assert app.video.frames[0]["RH"]["Zones"] == [[zone]]
    click(app, "Settings")
    assert find_button(find_toplevel(app, "Settings"), "Change project template").instate(["disabled"])
    assert not workspace.errors()


def test_general_channels_annotate_all_squares_and_restore_limb_controls(app, workspace, tmp_path):
    load_video(app, workspace, workspace.video, template="General")
    assert find_widget(app.mode_controls_frame, text="Channel Selector") is not None
    assert app.limb_parameter_heading.cget("text") == "Channel-specific"
    assert find_widget(app.mode_controls_frame, text="Right Hand") is None
    scale = app.diagram_scale
    with Image.open(asset_path("icons/general.png")) as source:
        expected = source.convert("RGB").resize(
            (int(450 * scale), int(696 * scale)), Image.Resampling.LANCZOS,
        )
    for index, key in enumerate(("RH", "LH", "RL", "LL"), start=1):
        select_radio(app, f"Channel {index}")
        assert app.option_var_1.get() == key
        rendered = ImageTk.getimage(app.photo).convert("RGB")
        assert ImageChops.difference(rendered, expected).getbbox() is None
        for row in range(4):
            for column in range(2):
                x, y = 137 + column * 176, 102 + row * 164
                click_canvas(app.diagram_canvas, "<Button-1>", int(x * scale), int(y * scale))
        assert app.video.frames[0][key]["Zones"] == [[str(n)] for n in range(1, 9)]

    click(app, "Settings")
    settings = find_toplevel(app, "Settings")
    assert find_widget(settings, text="Channel Parameter 1") is not None
    assert find_widget(settings, text="Limb Parameter 1") is None
    settings.destroy()

    default_video = tmp_path / "default.mp4"
    shutil.copy(workspace.video, default_video)
    load_video(app, workspace, default_video, template="Default")
    assert find_widget(app.mode_controls_frame, text="Limb Selector") is not None
    assert find_widget(app.mode_controls_frame, text="Right Hand") is not None
    assert find_widget(app.mode_controls_frame, text="Channel 1") is None
    assert app.limb_parameter_heading.cget("text") == "Limb-specific"
    assert not workspace.errors()


@pytest.mark.parametrize("schema", [1, 2])
def test_unsupported_project_is_rejected_without_changing_active_session(
    loaded_app, workspace, tmp_path, schema,
):
    app = loaded_app
    previous_video = app.video
    source = tmp_path / "historical.mp4"
    shutil.copy(workspace.video, source)
    paths = workspace.project("historical")
    repo = SqliteRepository(paths.state_db)
    repo.close()
    with sqlite3.connect(paths.state_db) as connection:
        connection.execute("INSERT INTO frames(frame, note) VALUES (3, 'historical note')")
        connection.execute(f"PRAGMA user_version={schema}")
    original_bytes = Path(paths.state_db).read_bytes()
    workspace.chosen_video = str(source)

    dismiss_dialog(app, "Select Mode", "Continue")
    dismiss_dialog(app, "Template for new projects", "Continue")
    app.load_video_btn.invoke()
    assert app.video is previous_video
    assert Path(paths.state_db).read_bytes() == original_bytes
    assert not list(Path(paths.state_dir).glob("*.bak"))
    assert len(workspace.errors()) == 1
    assert workspace.errors()[0][1] == "Cannot select project template"
