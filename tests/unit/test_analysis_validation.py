"""Export-schema validation and format tolerance for Analysis.

Before the split, `_load_limb_rows` used `rec.get(f"{limb}_Onset", "")`, so ANY
CSV with a `Frame` column "parsed" successfully and produced a complete
dashboard of zeros with no warning whatsoever — an easy way to publish numbers
for a file that never contained the limb data. Validation is now strict and up
front, and these tests pin the strictness, the tolerance of extra columns
(retired `Look` column), and the rejection of unversioned exports.
"""

import json
import logging

import pandas as pd
import pytest

from adapters.export_reader import ExportReadError, read_export_df
from adapters.export_writer import export_from_unified
from domain.model import LIMBS, empty_bundle
from domain.touch_stats import (
    ExportSchemaError,
    optional_columns,
    parse_export,
    required_columns,
    validate_export_columns,
)
from domain.project import ProjectPaths
from service_layer import analysis_service


# --- helpers ---------------------------------------------------------------

def write_real_export(path, frames=None, total_frames=3, frame_rate=25.0):
    """Write an export CSV through the REAL exporter, so these tests break if
    the export schema itself ever drifts away from what analysis requires."""
    export_from_unified(
        frames if frames is not None else {},
        str(path),
        program_version=8.0,
        video_name="vid",
        labeling_mode="Normal",
        frame_rate=frame_rate,
        special_zones_list=None,
        total_frames=total_frames,
    )
    return path


def touch_frames():
    """RH ON at frame 1 (zone A), OFF at frame 3 (zone B)."""
    frames = {}
    for frame, onset, zone in ((1, "ON", "A"), (3, "OFF", "B")):
        bundle = empty_bundle()
        bundle["RH"] = {
            "X": [10], "Y": [20], "Onset": onset, "Bodypart": "RH",
            "Zones": [[zone]], "Touch": None,
        }
        frames[frame] = bundle
    return frames


# --- the real exporter satisfies the validator -----------------------------

def test_real_export_passes_validation(tmp_path):
    path = write_real_export(tmp_path / "vid_export.csv", touch_frames())
    df = read_export_df(str(path))

    assert validate_export_columns(df) == []   # nothing optional missing either
    data = parse_export(df)
    assert data.total_frames == 4
    assert len(data.episodes["RH"]) == 1


def test_required_columns_are_exactly_frame_time_and_per_limb_onset_zones():
    expected = {"Frame", "Time_ms"}
    for limb in LIMBS:
        expected |= {f"{limb}_Onset", f"{limb}_Zones"}

    assert set(required_columns()) == expected
    # X/Y are optional: they feed only the trajectory plot.
    assert set(optional_columns()) == {f"{limb}_{ax}" for limb in LIMBS for ax in ("X", "Y")}


# --- missing columns are loud ---------------------------------------------

def test_frame_only_csv_is_rejected_naming_every_missing_column():
    df = pd.DataFrame({"Frame": [0, 1, 2]})

    with pytest.raises(ExportSchemaError) as caught:
        validate_export_columns(df)

    message = str(caught.value)
    assert "Time_ms" in message
    for limb in LIMBS:
        assert f"{limb}_Onset" in message and f"{limb}_Zones" in message


def test_single_missing_limb_column_is_named(tmp_path):
    path = write_real_export(tmp_path / "vid_export.csv", touch_frames())
    df = read_export_df(str(path)).drop(columns=["LF_Zones"])

    with pytest.raises(ExportSchemaError) as caught:
        parse_export(df)

    # The message names the missing column(s) first, then lists what WAS found.
    missing_part = str(caught.value).split("(found:")[0]
    assert "LF_Zones" in missing_part
    assert "RH_Zones" not in missing_part  # only the missing ones are blamed


def test_service_aborts_on_missing_columns_without_writing_anything(tmp_path, caplog):
    paths = ProjectPaths(video_name="vid", base_dir=str(tmp_path / "data"))
    (tmp_path / "data" / "vid" / "export").mkdir(parents=True)
    write_real_export(paths.export_csv, touch_frames())
    pd.read_csv(paths.export_csv).drop(columns=["Time_ms"]).to_csv(paths.export_csv, index=False)
    out_dir = tmp_path / "plots"

    with pytest.raises(ExportSchemaError):
        analysis_service.run_analysis(paths, frame_rate=25.0, output_folder=str(out_dir))

    assert any(record.levelname == "ERROR" for record in caplog.records)
    # No half-written dashboard: the output folder is not even created.
    assert not out_dir.exists()


def test_missing_xy_columns_only_warn(tmp_path, capsys):
    path = write_real_export(tmp_path / "vid_export.csv", touch_frames())
    df = read_export_df(str(path)).drop(columns=["RH_X", "RH_Y"])

    missing = validate_export_columns(df)
    assert set(missing) == {"RH_X", "RH_Y"}

    data = parse_export(df)
    assert len(data.episodes["RH"]) == 1        # stats unaffected
    assert data.episodes["RH"][0].points == ()  # nothing to draw


# --- legacy tolerance ------------------------------------------------------

def test_legacy_look_column_is_tolerated_and_ignored(tmp_path):
    path = write_real_export(tmp_path / "vid_export.csv", touch_frames())
    df = read_export_df(str(path))
    for limb in LIMBS:
        df[f"{limb}_Look"] = "No"          # retired per-limb Look field
    df["Look"] = "Yes"                      # and the old global one

    assert validate_export_columns(df) == []
    data = parse_export(df)
    episode = data.episodes["RH"][0]
    assert episode.duration_frames == 2
    assert episode.zones_start == ("A",) and episode.zones_end == ("B",)


def _write_unversioned_export(path):
    """A pre-format-2 export: anatomical per-limb columns, no Channel columns."""
    columns = {"Frame": [0], "Time_ms": [0.0]}
    for limb in ("LH", "RH"):
        columns.update({f"{limb}_X": [""], f"{limb}_Y": [""],
                        f"{limb}_Onset": [""], f"{limb}_Zones": ["[]"]})
    pd.DataFrame(columns).to_csv(path, index=False)
    return path


def test_unversioned_export_is_rejected_with_one_clear_error(tmp_path):
    """Unversioned exports are no longer analysed: one ExportReadError, never a
    silently empty or misattributed result."""
    path = _write_unversioned_export(tmp_path / "unversioned.csv")

    with pytest.raises(ExportReadError, match="no longer be analysed"):
        read_export_df(str(path))


def test_old_six_line_preamble_export_is_rejected(tmp_path):
    current = write_real_export(tmp_path / "current.csv", touch_frames())
    legacy = tmp_path / "legacy.csv"
    preamble = "\n".join(f"Program Version: 7.8 line {i}" for i in range(6))
    legacy.write_text(preamble + "\n" + current.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ExportReadError):
        read_export_df(str(legacy))


def test_service_rejects_unversioned_export_without_writing_anything(tmp_path):
    paths = ProjectPaths(video_name="vid", base_dir=str(tmp_path / "data"))
    (tmp_path / "data" / "vid" / "export").mkdir(parents=True)
    _write_unversioned_export(paths.export_csv)
    out_dir = tmp_path / "plots"

    with pytest.raises(ExportReadError, match="no longer be analysed"):
        analysis_service.run_analysis(paths, frame_rate=25.0, output_folder=str(out_dir))
    assert not out_dir.exists()


def test_header_only_export_is_handled(tmp_path):
    """An export with no rows analyses to an all-zero dashboard, legitimately."""
    real = write_real_export(tmp_path / "real_export.csv", total_frames=0)
    path = tmp_path / "empty_export.csv"
    path.write_text(real.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")

    df = read_export_df(str(path))
    data = parse_export(df)

    assert data.row_count == 0
    assert data.total_frames == 0
    assert all(data.episodes[limb] == [] for limb in LIMBS)


def test_unreadable_bytes_raise_export_read_error(tmp_path):
    path = tmp_path / "junk.csv"
    path.write_bytes(b"\xff\xfe\xfa")

    with pytest.raises(ExportReadError):
        read_export_df(str(path))


# --- frame-rate provenance -------------------------------------------------

def test_frame_rate_prefers_caller_then_metadata_then_none(tmp_path, caplog):
    meta = tmp_path / "vid_metadata.json"
    meta.write_text(json.dumps({"Frame Rate": 25.0}), encoding="utf-8")

    with caplog.at_level(logging.INFO, logger="service_layer.analysis_service"):
        assert analysis_service.resolve_frame_rate(30.0, str(meta)) == (30.0, "caller")
        assert "overrides export metadata" in caplog.text

        # A 0.0 probe (some containers report 0 for CAP_PROP_FPS) is not a value.
        assert analysis_service.resolve_frame_rate(0.0, str(meta)) == (25.0, "metadata")
        assert analysis_service.resolve_frame_rate(None, str(meta)) == (25.0, "metadata")
        assert "from export metadata" in caplog.text

        assert analysis_service.resolve_frame_rate(0.0, str(tmp_path / "nope.json")) == (
            None, "unavailable",
        )
        assert any(record.levelname == "WARNING" for record in caplog.records)


def test_frame_rate_metadata_with_zero_value_is_not_used(tmp_path):
    meta = tmp_path / "vid_metadata.json"
    meta.write_text(json.dumps({"Frame Rate": 0.0}), encoding="utf-8")

    assert analysis_service.resolve_frame_rate(None, str(meta)) == (None, "unavailable")


def test_frame_rate_corrupt_metadata_does_not_raise(tmp_path, caplog):
    meta = tmp_path / "vid_metadata.json"
    meta.write_text("{not json", encoding="utf-8")

    assert analysis_service.resolve_frame_rate(None, str(meta)) == (None, "unavailable")
    assert any(record.levelname == "WARNING" for record in caplog.records)
