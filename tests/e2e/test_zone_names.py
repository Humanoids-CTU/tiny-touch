"""All templates share project zone aliases and optional canvas labels."""
import csv
import json
import shutil
from pathlib import Path
from dataclasses import replace

from domain.coding_setup import default_coding_setup

import pytest

import labeling_app

from gui_driver import click, click_canvas, find_toplevel, find_widget, goto_frame, load_video, save, walk


pytestmark = pytest.mark.gui


def _show_toggle(settings):
    label = find_widget(settings, text="Show zone names on diagrams")
    info = label.grid_info()
    return next(widget for widget in label.master.grid_slaves(row=info["row"], column=1))


def _set_visibility(settings, show):
    toggle = _show_toggle(settings)
    if bool(toggle.instate(["selected"])) != show:
        toggle.invoke()
    click(settings, "Save")  # applies and closes the window


def _named_setup(choice, zone, name):
    return replace(default_coding_setup(choice.lower()), zone_labels={zone: name})


def _texts(canvas):
    return [canvas.itemcget(item, "text") for item in canvas.find_withtag("zone-label")
            if canvas.type(item) == "text"]


@pytest.mark.parametrize("choice,zone,point", [
    ("Default", "I", (192, 336)),
    ("Alternate", "G", (192, 336)),
    ("General", "1", (137, 102)),
])
def test_zone_names_save_reopen_freeze_and_keep_annotation_ids(app, workspace, tmp_path, choice, zone, point):
    load_video(app, workspace, workspace.video, template=choice, setup=_named_setup(choice, zone, "Light on"))
    paths = workspace.project()
    assert not app.diagram_canvas.find_withtag("zone-label")
    click_point = tuple(int(value * app.diagram_scale) for value in point)
    click_canvas(app.diagram_canvas, "<Button-1>", *click_point)
    assert app.state_repo.load_template().locked
    assert app.video.frames[0]["RH"]["Zones"] == [[zone]]
    app._set_note_entry_text("Unsubmitted draft")
    click(app, "Special Zones")
    special = app._special_zones_app
    assert not special.canvas2.find_withtag("zone-label")
    click(app, "Settings")
    settings = find_toplevel(app, "Settings")
    _set_visibility(settings, True)
    if labeling_app.SETTINGS_SHOW_ZONE_NAME_EDITOR:
        assert find_widget(settings, text="Edit zone names").instate(["disabled"])
    assert app._get_note_entry_text() == "Unsubmitted draft"
    assert "Light on" in _texts(app.diagram_canvas)
    assert "Light on" in _texts(special.canvas2)
    assert app.video.frames[0]["RH"]["Zones"] == [[zone]]
    meta = json.loads(Path(paths.export_metadata).read_text(encoding="utf-8"))
    assert meta["Coding Setup"]["zone_labels"] == {zone: "Light on"}
    with open(paths.export_csv, encoding="utf-8", newline="") as stream:
        assert json.loads(next(csv.DictReader(stream))["Channel1_Zones"]) == [[zone]]
    csv_before = Path(paths.export_csv).read_bytes()
    # Labels stay below dots and do not interfere with marking or deletion.
    anchor = app._zone_label_positions[zone]
    special_point = tuple(int(value * special.diagram_scale) for value in anchor)
    click_canvas(special.canvas2, "<Button-1>", *special_point)
    click_canvas(special.canvas2, "<Button-2>", *special_point)
    assert not special.dots
    special.on_close()
    settings.destroy()

    other = tmp_path / "other.mp4"
    shutil.copy(workspace.video, other)
    load_video(app, workspace, other, template=choice)
    assert not app.zone_display.show_names and not app.zone_display.labels
    load_video(app, workspace, workspace.video, template=choice)
    assert app.zone_display.show_names
    assert app.zone_display.label(zone) == "Light on"
    assert "Light on" in _texts(app.diagram_canvas)
    assert app.video.frames[0]["RH"]["Zones"] == [[zone]]

    click(app, "Settings")
    settings = find_toplevel(app, "Settings")
    if labeling_app.SETTINGS_SHOW_ZONE_NAME_EDITOR:
        assert find_widget(settings, text="Edit zone names").instate(["disabled"])
    _set_visibility(settings, False)
    assert not app.diagram_canvas.find_withtag("zone-label")
    assert app.zone_display.label(zone) == "Light on"
    assert json.loads(Path(paths.export_metadata).read_text())["Coding Setup"]["zone_labels"] == {zone: "Light on"}
    assert Path(paths.export_csv).read_bytes() == csv_before
    settings.destroy()
    click(app, "Special Zones")
    assert not app._special_zones_app.canvas2.find_withtag("zone-label")
    app._special_zones_app.on_close()
    assert not workspace.errors()


@pytest.mark.parametrize("choice,zone,point", [
    ("Default", "I", (192, 336)),
    ("Alternate", "G", (192, 336)),
    ("General", "1", (137, 102)),
])
def test_named_template_full_workflow_and_reliability(app, workspace, tmp_path, choice, zone, point):
    """Exercise Settings -> annotate -> reopen -> Analysis in both labeling passes."""
    assert not app.diagram_canvas.find_all()
    load_video(app, workspace, workspace.video, template=choice, setup=_named_setup(choice, zone, "Acceptance target"))
    assert app.diagram_canvas.find_withtag("diagram")
    click(app, "Settings")
    settings = find_toplevel(app, "Settings")
    _set_visibility(settings, True)
    settings.destroy()
    position = tuple(int(value * app.diagram_scale) for value in point)

    def annotate_and_analyze(paths):
        goto_frame(app, 0)
        click_canvas(app.diagram_canvas, "<Button-1>", *position)
        goto_frame(app, 2)
        click_canvas(app.diagram_canvas, "<Button-3>", *position)
        save(app)
        metadata = json.loads(Path(paths.export_metadata).read_text(encoding="utf-8"))
        assert metadata["Coding Setup"]["zone_labels"] == {zone: "Acceptance target"}
        assert metadata["Coding Setup"]["template"] == choice.lower()
        if choice == "General":
            assert metadata["Coding Setup"]["channel_labels"] == {
                "Channel1": "Channel 1", "Channel2": "Channel 2", "Channel3": "Channel 3", "Channel4": "Channel 4",
            }
        click(app, "Analysis")
        assert workspace.opened_urls
        report = Path(workspace.opened_urls[-1])
        assert report.is_file()
        assert report.parent == Path(paths.plots_dir)
        assert "Acceptance target" in (report.parent / "zone_table.html").read_text(encoding="utf-8")
        with (report.parent / "analysis_table_frames.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        rh = next(row for row in rows if row["Channel"] == "Channel1")
        assert float(rh["Total Duration [Frames]"]) == 2
        assert not workspace.errors()

    original = workspace.project()
    annotate_and_analyze(original)
    original_csv = Path(original.export_csv).read_bytes()
    other = tmp_path / "other.mp4"
    shutil.copy(workspace.video, other)
    load_video(app, workspace, other, template=choice)
    load_video(app, workspace, workspace.video, template=choice)
    assert app.zone_display.show_names
    assert "Acceptance target" in _texts(app.diagram_canvas)
    assert app.video.frames[0]["RH"]["Zones"] == [[zone]]
    assert app.video.frames[2]["RH"]["Onset"] == "OFF"
    assert Path(original.export_csv).read_bytes() == original_csv

    # A different picker preference must not override the linked original.
    load_video(app, workspace, workspace.video, mode="Reliability", template="Default")
    assert app.state_repo.load_template().template == choice.lower()
    assert app.zone_display.show_names
    assert "Acceptance target" in _texts(app.diagram_canvas)
    assert not app.video.frames
    annotate_and_analyze(workspace.project("tiny_reliability"))
    assert Path(original.export_csv).read_bytes() == original_csv
