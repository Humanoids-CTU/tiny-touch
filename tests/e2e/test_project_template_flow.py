"""Researcher workflows for template choice, locking, clothing and reopening."""

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
    load_video, pump, save,
)


pytestmark = pytest.mark.gui


def _metadata(paths):
    connection = sqlite3.connect(Path(paths.state_db).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return dict(connection.execute("SELECT key, value FROM meta"))
    finally:
        connection.close()


@pytest.mark.parametrize("choice,template,folder,zone", [
    ("Default", "default", "zones3", "I"),
    ("Alternate", "alternate", "zones3_new_template", "G"),
])
def test_clothes_displays_selected_template_and_permanently_locks_it(
    app, workspace, choice, template, folder, zone,
):
    load_video(app, workspace, workspace.video, template=choice)
    paths = workspace.project()
    assert _metadata(paths)["template"] == template
    assert _metadata(paths)["template_locked"] == "0"

    click(app, "Clothes")
    pump(app)
    window = find_toplevel(app, "Clothes App")
    canvas = find_widget(window, cls=tk.Canvas)
    # Inspect the image sent to Tk, rather than just its configured file path.
    rendered = ImageTk.getimage(app._cloth_app.photo2).convert("RGB")
    with Image.open(asset_path(f"icons/{folder}/LINE.png")) as outline:
        expected = outline.convert("RGB").resize(rendered.size, Image.Resampling.LANCZOS)
    assert ImageChops.difference(rendered, expected).getbbox() is None

    scale = app._cloth_app.diagram_scale
    point = (int(192 * scale), int(336 * scale))
    click_canvas(canvas, "<Button-1>", *point)
    pump(app)
    # Lock is durable before the user presses Save in Clothes.
    assert _metadata(paths)["template_locked"] == "1"
    click(window, "Save & Close")
    connection = sqlite3.connect(paths.state_db)
    try:
        assert connection.execute("SELECT zones FROM clothes_dots").fetchall() == [(zone,)]
    finally:
        connection.close()

    click(app, "Clothes")
    pump(app)
    window = find_toplevel(app, "Clothes App")
    click_canvas(find_widget(window, cls=tk.Canvas), "<Button-2>", *point)
    click(window, "Save & Close")
    assert _metadata(paths)["template_locked"] == "1"
    save(app)
    assert json.loads(Path(paths.export_metadata).read_text())["template"] == template

    opposite = "Alternate" if choice == "Default" else "Default"
    load_video(app, workspace, workspace.video, template=opposite)
    assert _metadata(paths)["template"] == template
    assert any(title == "Saved template restored" for _, title, _ in workspace.messages)
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


def test_empty_project_can_change_template_through_settings(loaded_app, workspace):
    app = loaded_app
    click(app, "Settings")
    settings = find_toplevel(app, "Settings")
    selected = dismiss_dialog(
        app, "Template for new projects", "Continue", radio_text="Alternate",
    )
    click(settings, "Change project template")
    assert selected["clicked"]
    assert _metadata(workspace.project())["template"] == "alternate"
    assert _metadata(workspace.project())["template_locked"] == "0"
    assert json.loads(Path(workspace.project().export_metadata).read_text())["template"] == "alternate"
    find_toplevel(app, "Settings").destroy()
    click_canvas(app.diagram_canvas, "<Button-1>", 96, 168)
    assert app.video.frames[0]["RH"]["Zones"] == [["G"]]
    click(app, "Settings")
    assert find_button(find_toplevel(app, "Settings"), "Change project template").instate(["disabled"])
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
