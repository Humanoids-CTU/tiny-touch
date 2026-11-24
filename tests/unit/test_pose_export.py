"""The Pose export format: columns, cell encodings and metadata.

docs/POSE_DATA_FORMAT.md is the specification. `fixtures/golden_pose_export.csv`
was generated from the writer and checked by hand; it pins every cell encoding.
Line ends are the one platform-dependent byte (os.linesep, like the Touch
export), so comparisons normalize CRLF to LF.

A red test here means the published Pose format changed: revert, or bump
`POSE_EXPORT_FORMAT_VERSION`, update the document and regenerate the fixture
in the same change.
"""
import csv
import io
import json
import os

import pytest

from adapters.pose_export_writer import write_pose_export_csv, write_pose_export_metadata
from domain.pose import (PoseLabels, PoseSnapshot, ScaleKind, ScaleLabel, ScaleSource,
                         ZoneEvent)
from domain.pose_export import (POSE_EXPORT_COLUMNS, number_cell, pose_export_rows,
                                special_zone_ids, zones_cell)
from domain.pose_setup import PoseCodingSetup
from domain.project import ProjectPaths

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "golden_pose_export.csv")
GOLDEN_FPS = 25.0
GOLDEN_TOTAL_FRAMES = 7   # rows for frames 0..7 inclusive
NOTE = 'said "hi", then\nrolled over ěšč'
MANUAL, CARRIED = ScaleSource.MANUAL, ScaleSource.CARRIED
BODY, HEAD = ScaleKind.BODY, ScaleKind.HEAD
ON, OFF = ZoneEvent.ON, ZoneEvent.OFF


def golden_tables():
    """Labels exercising every encoding. Frames 0 and 3 carry nothing at all.

    Built through the storage boundary because frame 4 holds ON and OFF
    together, which older stored projects can contain but the editor no longer
    produces.
    """
    return PoseLabels.from_snapshot(PoseSnapshot(
        events=(
            (1, "L", ON), (1, "BOX2", ON), (1, "A", ON),   # several zones, one frame
            (4, "C", ON), (4, "B", OFF),                   # ON and OFF on one frame
            (6, "QB", OFF),
        ),
        quality=((1, 0.0), (2, 0.0), (4, 0.85), (7, 1.0)),  # explicit 0 is a value
        scales=(
            (1, BODY, ScaleLabel(1.2, MANUAL)), (1, HEAD, ScaleLabel(1.0, MANUAL)),
            (2, BODY, ScaleLabel(1.2, CARRIED)), (2, HEAD, ScaleLabel(1.0, CARRIED)),
            (5, BODY, ScaleLabel(0.5, MANUAL)),
            (7, HEAD, ScaleLabel(1.5, CARRIED)),
        ),
    )).tables()


def golden_shared_frames():
    return {
        4: {"Note": None, "Params": {"Par1": "ON", "Par2": None, "Par3": "OFF"}, "Changed": False},
        5: {"Note": NOTE, "Params": {}, "Changed": True},
        6: {"Note": "", "Params": {"Par2": "ON"}},
    }


def _write(tmp_path, tables=None, shared=None, *, total_frames=GOLDEN_TOTAL_FRAMES,
           frame_rate=GOLDEN_FPS):
    out = tmp_path / "vid_pose_export.csv"
    write_pose_export_csv(str(out), tables or golden_tables(),
                          golden_shared_frames() if shared is None else shared,
                          total_frames=total_frames, frame_rate=frame_rate)
    return out


def _rows(path):
    with open(path, encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _normalized(raw: bytes) -> bytes:
    return raw.replace(b"\r\n", b"\n")


# === columns ==================================================================
def test_column_set_and_order():
    assert POSE_EXPORT_COLUMNS == (
        "Frame", "Time_ms", "Zones_On", "Zones_Off",
        "Body_Scale", "Body_Scale_Source", "Head_Scale", "Head_Scale_Source",
        "Quality", "Parameter_1", "Parameter_2", "Parameter_3", "Note",
    )


def test_header_and_one_row_per_frame_including_the_last(tmp_path):
    out = _write(tmp_path)
    with open(out, encoding="utf-8", newline="") as stream:
        table = list(csv.reader(stream))
    assert tuple(table[0]) == POSE_EXPORT_COLUMNS
    assert [row[0] for row in table[1:]] == [str(frame) for frame in range(8)]
    assert all(len(row) == len(POSE_EXPORT_COLUMNS) for row in table)


# === golden fixture ===========================================================
def test_export_matches_the_golden_fixture(tmp_path):
    with open(FIXTURE, "rb") as stream:
        expected = _normalized(stream.read())
    assert _normalized(_write(tmp_path).read_bytes()) == expected


def test_export_is_utf8_without_bom_and_uses_the_platform_line_end(tmp_path):
    raw = _write(tmp_path).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert "ěšč".encode("utf-8") in raw and b"\\u" not in raw
    header = raw[:raw.index(b"\n") + 1]
    assert header.endswith(b"\r\n") == (os.linesep == "\r\n")


# === cells ====================================================================
def test_sparse_gaps_stay_empty(tmp_path):
    rows = _rows(_write(tmp_path))
    for frame in (0, 3):
        cells = dict(rows[frame])
        assert cells.pop("Frame") == str(frame)
        assert cells.pop("Time_ms") == f"{frame * 40}.000"
        assert set(cells.values()) == {""}
    # Carried scale ended at frame 2; nothing is filled in afterwards.
    assert rows[3]["Body_Scale"] == "" and rows[3]["Quality"] == ""
    assert rows[6]["Body_Scale"] == "" and rows[6]["Head_Scale_Source"] == ""


def test_explicit_zero_quality_and_neutral_scale_are_values(tmp_path):
    rows = _rows(_write(tmp_path))
    assert rows[1]["Quality"] == "0.00"
    assert rows[1]["Head_Scale"] == "1.00" and rows[1]["Head_Scale_Source"] == "manual"
    assert rows[7]["Quality"] == "1.00"


def test_manual_and_carried_provenance(tmp_path):
    rows = _rows(_write(tmp_path))
    assert (rows[1]["Body_Scale"], rows[1]["Body_Scale_Source"]) == ("1.20", "manual")
    assert (rows[2]["Body_Scale"], rows[2]["Body_Scale_Source"]) == ("1.20", "carried")
    assert (rows[2]["Head_Scale"], rows[2]["Head_Scale_Source"]) == ("1.00", "carried")
    assert (rows[5]["Body_Scale"], rows[5]["Head_Scale"]) == ("0.50", "")
    assert (rows[7]["Head_Scale"], rows[7]["Head_Scale_Source"]) == ("1.50", "carried")


def test_multiple_zones_on_one_frame_use_ids_in_a_fixed_order(tmp_path):
    rows = _rows(_write(tmp_path))
    assert json.loads(rows[1]["Zones_On"]) == ["A", "L", "BOX2"]
    assert rows[1]["Zones_Off"] == ""
    assert b'"[""A"", ""L"", ""BOX2""]"' in _write(tmp_path).read_bytes()


def test_on_and_off_on_the_same_frame_are_both_written(tmp_path):
    rows = _rows(_write(tmp_path))
    assert json.loads(rows[4]["Zones_On"]) == ["C"]
    assert json.loads(rows[4]["Zones_Off"]) == ["B"]
    assert (rows[6]["Zones_On"], json.loads(rows[6]["Zones_Off"])) == ("", ["QB"])


def test_note_with_comma_quotes_and_newline_survives_a_csv_reader(tmp_path):
    rows = _rows(_write(tmp_path))
    assert rows[5]["Note"] == NOTE
    assert rows[4]["Note"] == "" and rows[6]["Note"] == ""


def test_parameters_use_on_off_or_empty(tmp_path):
    rows = _rows(_write(tmp_path))
    assert [rows[4][f"Parameter_{i}"] for i in (1, 2, 3)] == ["ON", "", "OFF"]
    assert [rows[6][f"Parameter_{i}"] for i in (1, 2, 3)] == ["", "ON", ""]
    assert [rows[5][f"Parameter_{i}"] for i in (1, 2, 3)] == ["", "", ""]


def test_invalid_parameter_state_stops_the_export(tmp_path):
    with pytest.raises(ValueError, match="parameter"):
        _write(tmp_path, shared={2: {"Note": None, "Params": {"Par1": "MAYBE"}}})
    assert not (tmp_path / "vid_pose_export.csv").exists()


@pytest.mark.parametrize("frame_rate", [None, 0, 0.0, -25.0, float("nan"), float("inf")])
def test_unusable_fps_gives_empty_time_and_keeps_everything_else(tmp_path, frame_rate):
    good = _rows(_write(tmp_path))
    bad = _rows(_write(tmp_path, frame_rate=frame_rate))
    assert all(row["Time_ms"] == "" for row in bad)
    for row in good:
        row["Time_ms"] = ""
    assert bad == good


def test_time_ms_has_three_decimals_at_source_fps_precision(tmp_path):
    rows = _rows(_write(tmp_path, frame_rate=30))
    assert [row["Time_ms"] for row in rows[:3]] == ["0.000", "33.333", "66.667"]


@pytest.mark.parametrize("value, text", [
    (0, "0.00"), (0.0, "0.00"), (1, "1.00"), (1.0, "1.00"), (0.5, "0.50"),
    (0.85, "0.85"), (1.37, "1.37"), (0.07, "0.07"),
    (0.125, "0.125"), (1.23456, "1.23456"),   # more stored digits are never cut
])
def test_number_cell(value, text):
    assert number_cell(value) == text
    assert float(number_cell(value)) == value


def test_zone_cell_order_is_the_zone_list_order_not_alphabetical():
    assert zones_cell(["BOX1", "TB", "T", "B"]) == '["B", "T", "TB", "BOX1"]'
    assert zones_cell([]) == ""


def test_labels_past_the_last_frame_stop_the_export(tmp_path):
    with pytest.raises(ValueError, match="past the last video frame"):
        _write(tmp_path, total_frames=6)
    with pytest.raises(ValueError, match="past the last video frame"):
        list(pose_export_rows(PoseLabels().tables(), {9: {"Note": "late"}}, 8, 25.0))
    assert not (tmp_path / "vid_pose_export.csv").exists()


def test_empty_project_exports_empty_rows(tmp_path):
    rows = _rows(_write(tmp_path, PoseLabels().tables(), {}, total_frames=2))
    assert [row["Frame"] for row in rows] == ["0", "1", "2"]
    assert all(set(list(row.values())[2:]) == {""} for row in rows)


def test_tables_are_detached_from_later_edits():
    labels = PoseLabels()
    labels.set_quality(1, 0.5, displayed_frame=1)
    tables = labels.tables()
    labels.set_quality(1, 0.9, displayed_frame=1)
    labels.set_quality(2, 0.1, displayed_frame=2)
    assert tables.quality == {1: 0.5}


# === metadata =================================================================
BASE_KEYS = ["Export Format", "Export Format Version", "Program Version", "Annotation Type",
             "Video Name", "Labeling Mode", "Frame Rate", "Total Frames", "Frame Provenance",
             "Coding Setup", "Value Conventions", "Interval Rule", "Special Zones",
             "Special Zones Note"]


def _metadata(tmp_path, **overrides):
    fields = dict(
        program_version="9.5.0 (Windows)", video_name="vid", labeling_mode="Normal",
        frame_rate=25.0, total_frames=7,
        coding_setup=PoseCodingSetup(
            "Study A", parameter_labels={"Par1": "Looking", "Par2": "Crying", "Par3": "P3"},
            zone_labels={"L": "Left hand ěš"}),
        special_zones=("B", "L"), special_zones_note="socks",
    )
    fields.update(overrides)
    path = tmp_path / "vid_pose_metadata.json"
    write_pose_export_metadata(str(path), **fields)
    return path


def test_metadata_keys_and_order(tmp_path):
    meta = json.loads(_metadata(tmp_path).read_text(encoding="utf-8"))
    assert list(meta) == BASE_KEYS
    timed = json.loads(_metadata(tmp_path, labeling_time_seconds=5400).read_text(encoding="utf-8"))
    assert list(timed) == BASE_KEYS + ["Total Labeling Time (hours)"]
    assert timed["Total Labeling Time (hours)"] == 1.5


def test_metadata_values(tmp_path):
    meta = json.loads(_metadata(tmp_path).read_text(encoding="utf-8"))
    assert meta["Export Format"] == "tinytouch.pose-export"
    assert meta["Export Format Version"] == 1
    assert "Metadata Format Version" not in meta   # not a Touch metadata file
    assert meta["Annotation Type"] == "Pose"
    assert (meta["Video Name"], meta["Labeling Mode"]) == ("vid", "Normal")
    assert meta["Frame Rate"] == 25.0
    assert meta["Total Frames"] == 8                # frames 0..7, the CSV row count
    assert meta["Special Zones"] == ["B", "L"] and meta["Special Zones Note"] == "socks"
    assert "any off closes the active interval" in meta["Interval Rule"].lower()
    assert "different zone" in meta["Interval Rule"]
    assert meta["Value Conventions"]["scale_sources"] == ["manual", "carried"]


def test_metadata_holds_the_full_coding_setup_with_every_zone_label(tmp_path):
    setup = json.loads(_metadata(tmp_path).read_text(encoding="utf-8"))["Coding Setup"]
    assert setup["name"] == "Study A" and setup["template"] == "alternate"
    assert setup["annotation_type"] == "Pose"
    assert setup["parameter_labels"] == {"Par1": "Looking", "Par2": "Crying", "Par3": "P3"}
    assert len(setup["zone_labels"]) == 30
    assert setup["zone_labels"]["L"] == "Left hand ěš"
    assert setup["zone_labels"]["A"] == "A"         # unlabeled zones resolve to their ID
    # The snapshot can be loaded back as a Pose coding setup.
    assert PoseCodingSetup.from_dict(setup).parameter_labels["Par1"] == "Looking"


def test_metadata_formatting_and_empty_values(tmp_path):
    path = _metadata(tmp_path, frame_rate=0, special_zones=(), special_zones_note="")
    text = path.read_text(encoding="utf-8")
    assert text.startswith('{\n  "Export Format": "tinytouch.pose-export",')
    assert "Left hand ěš" in text and "\\u" not in text
    meta = json.loads(text)
    assert meta["Frame Rate"] is None
    assert meta["Special Zones"] == [] and meta["Special Zones Note"] is None


def test_metadata_requires_a_pose_coding_setup(tmp_path):
    with pytest.raises(ValueError):
        _metadata(tmp_path, coding_setup=None)
    assert not (tmp_path / "vid_pose_metadata.json").exists()


def test_special_zone_ids_are_unique_and_follow_dot_order():
    rows = [(3, 1.0, 2.0, "B"), (1, 5.0, 6.0, "L,B"), (2, 7.0, 8.0, ""), (4, 0.0, 0.0, "A")]
    assert special_zone_ids(rows) == ["L", "B", "A"]
    assert special_zone_ids([]) == []


# === paths ====================================================================
def test_pose_export_paths_never_collide_with_touch(tmp_path):
    for reliability, name in ((False, "cat3"), (True, "cat3_reliability")):
        pose = ProjectPaths.for_video("cat3", reliability, str(tmp_path), "Pose")
        touch = ProjectPaths.for_video("cat3", reliability, str(tmp_path), "Touch")
        export = os.path.join(str(tmp_path), name, "export")
        assert pose.pose_export_csv == os.path.join(export, f"{name}_pose_export.csv")
        assert pose.pose_export_metadata == os.path.join(export, f"{name}_pose_metadata.json")
        assert not {pose.pose_export_csv, pose.pose_export_metadata} & {
            touch.export_csv, touch.export_metadata, touch.export_diagram}


def test_writer_streams_through_a_plain_csv_reader():
    stream = io.StringIO()
    csv.writer(stream).writerows(pose_export_rows(golden_tables(), golden_shared_frames(), 7, 25.0))
    assert len(list(csv.reader(io.StringIO(stream.getvalue())))) == 8
