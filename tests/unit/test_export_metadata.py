"""
Golden lock on `export/<video>_metadata.json` (`write_export_metadata`).

The metadata sidecar replaced the old 5-line CSV preamble; downstream tooling
reads it by key NAME, and humans (and diff-based review) rely on its stable key
ORDER, 2-space indentation, and literal UTF-8 (ensure_ascii=False). Until this
file existed there were ZERO tests on it — pin every observable byte-level
property before the refactor.

json.load preserves the file's key order in the returned dict (Python dicts are
insertion-ordered), so `list(d.keys())` asserts the on-disk order exactly.
"""
import json
import pytest

from adapters.export_writer import write_export_metadata


BASE_KEYS = ["Export Format Version", "Metadata Format Version", "Program Version", "Video Name", "Labeling Mode", "Frame Rate", "Frame Provenance", "Coordinate Convention", "Coding Setup", "Diagram", "Special Zones", "Special Zones Note"]


def _write(tmp_path, **overrides):
    kwargs = dict(
        program_version=8.0,
        video_name="vid",
        labeling_mode="Normal",
        template="default",
        frame_rate=25.0,
        special_zones_list=["BELLY", "17L"],
        special_zones_note="diaper and socks",
        param_labels={"Par1": "Looking1"},
        limb_param_labels={"Par1": "Grasp"},
    )
    kwargs.update(overrides)
    path = tmp_path / "vid_metadata.json"
    write_export_metadata(str(path), **kwargs)
    return path


@pytest.mark.parametrize("template", ["default", "alternate"])
def test_metadata_key_set_and_order_without_labeling_time(tmp_path, template):
    path = _write(tmp_path, template=template)
    with open(path, encoding="utf-8") as fh:
        meta = json.load(fh)
    assert list(meta.keys()) == BASE_KEYS


@pytest.mark.parametrize("labeling_time", [None, 3600.0])
def test_general_metadata_maps_stored_keys_to_channel_labels(tmp_path, labeling_time):
    path = _write(tmp_path, template="general", labeling_time_seconds=labeling_time)
    meta = json.loads(path.read_text(encoding="utf-8"))
    assert meta["Coding Setup"]["template"] == "general"
    assert meta["Coding Setup"]["channel_labels"] == {
        "Channel1": "Channel 1", "Channel2": "Channel 2", "Channel3": "Channel 3", "Channel4": "Channel 4",
    }
    assert list(meta["Coding Setup"]["channel_labels"]) == ["Channel1", "Channel2", "Channel3", "Channel4"]
    expected_keys = BASE_KEYS.copy()
    if labeling_time is not None:
        expected_keys.append("Total Labeling Time (hours)")
    assert list(meta) == expected_keys


def test_metadata_labeling_time_appends_as_last_key(tmp_path):
    path = _write(tmp_path, labeling_time_seconds=3600.0)
    with open(path, encoding="utf-8") as fh:
        meta = json.load(fh)
    assert list(meta.keys()) == BASE_KEYS + ["Total Labeling Time (hours)"]
    assert meta["Total Labeling Time (hours)"] == 1.0


def test_metadata_exact_values_roundtrip(tmp_path):
    path = _write(tmp_path, labeling_time_seconds=7200.0)
    with open(path, encoding="utf-8") as fh:
        meta = json.load(fh)
    assert meta["Export Format Version"] == 2
    assert "limb_parameter_labels" not in meta["Coding Setup"]
    assert "Limb Param Labels" not in meta
    assert meta["Program Version"] == 8.0
    assert meta["Video Name"] == "vid"
    assert meta["Frame Rate"] == 25.0
    assert meta["Coding Setup"]["parameter_labels"]["Par1"] == "Looking1"
    assert meta["Coding Setup"]["channel_parameter_labels"]["Par1"] == "Grasp"
    assert meta["Special Zones"] == ["BELLY", "17L"]
    assert meta["Special Zones Note"] == "diaper and socks"
    assert meta["Total Labeling Time (hours)"] == 2.0



def test_metadata_labeling_time_rounds_to_4dp(tmp_path):
    # 3661 s = 1.01694444... h -> 1.0169 (round-half-even at 4 decimals).
    path = _write(tmp_path, labeling_time_seconds=3661.0)
    meta = json.loads(path.read_text(encoding="utf-8"))
    assert meta["Total Labeling Time (hours)"] == 1.0169


def test_metadata_special_zones_none_stays_null_and_labels_default_to_empty(tmp_path):
    """No Special Zones dialog run -> list and note are serialized as JSON null
    (NOT an empty list — downstream distinguishes 'never marked' from 'marked
    nothing'). Absent label dicts collapse to {}."""
    path = _write(tmp_path, special_zones_list=None, special_zones_note=None,
                  param_labels=None, limb_param_labels=None)
    meta = json.loads(path.read_text(encoding="utf-8"))
    assert meta["Special Zones"] is None
    assert meta["Special Zones Note"] is None
    assert meta["Coding Setup"]["parameter_labels"] == {f"Par{i}": f"P{i}" for i in (1,2,3)}
    assert meta["Coding Setup"]["channel_parameter_labels"] == {f"Par{i}": f"CP{i}" for i in (1,2,3)}
    assert '"Special Zones": null' in path.read_text(encoding="utf-8")


def test_metadata_is_indent2_json(tmp_path):
    """The sidecar is pretty-printed with indent=2 and LF newlines (atomic_write
    opens with newline='' so json's own '\\n' is never translated, even on
    Windows) — diffs and hand-inspection depend on this layout."""
    raw = _write(tmp_path).read_bytes()
    text = raw.decode("utf-8")
    assert text.startswith('{\n  "Export Format Version": 2,'), text[:40]
    assert '\n  "Video Name": "vid",\n' in text
    assert b"\r\n" not in raw


def test_metadata_non_ascii_survives_as_utf8_not_escapes(tmp_path):
    """ensure_ascii=False is part of the contract: a Czech zone/param label must
    land in the file as literal UTF-8 bytes, never \\uXXXX escapes."""
    path = _write(tmp_path, special_zones_list=["Bříško"],
                  special_zones_note="Plenka ěšč",
                  param_labels={"Par1": "Pohled ěšč"})
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "metadata grew a UTF-8 BOM"
    assert "Bříško".encode("utf-8") in raw
    assert "Pohled ěšč".encode("utf-8") in raw
    assert "Plenka ěšč".encode("utf-8") in raw
    assert b"\\u" not in raw
    meta = json.loads(path.read_text(encoding="utf-8"))
    assert meta["Special Zones"] == ["Bříško"]
    assert meta["Coding Setup"]["parameter_labels"]["Par1"] == "Pohled ěšč"


def test_fallback_metadata_freezes_zone_names_in_every_snapshot(tmp_path):
    path = _write(tmp_path, zone_labels={'I': 'Target'})
    meta = json.loads(path.read_text(encoding='utf-8'))
    from adapters.zone_masks import list_zone_names
    assert meta['Coding Setup']['zone_labels'] == {
        zone: 'Target' if zone == 'I' else zone
        for zone in list_zone_names('default')
    }
    assert "zones" not in meta["Diagram"]
    assert "Zone Labels" not in meta


def test_fallback_metadata_rejects_invalid_zone_names_before_writing(tmp_path):
    with pytest.raises(ValueError):
        _write(tmp_path, zone_labels={'I': 'invalid\nname'})
    assert not (tmp_path / 'vid_metadata.json').exists()


def test_metadata_lists_fixed_zone_ids_and_resolved_labels_once(tmp_path):
    from adapters.zone_masks import list_zone_names
    from domain.coding_setup import CodingSetup
    path = _write(tmp_path, template="general", zone_labels={"1": "Head"})
    metadata = json.loads(path.read_text(encoding="utf-8"))
    setup = metadata["Coding Setup"]
    assert set(setup["zone_labels"]) == set(list_zone_names("general"))
    assert setup["zone_labels"]["1"] == "Head"
    assert setup["zone_labels"]["9"] == "9"
    assert setup["channel_zones"] == {
        "Channel1": ["9"], "Channel2": ["10"],
        "Channel3": ["11"], "Channel4": ["12"],
    }
    assert "Zone Labels" not in metadata
    assert dict(CodingSetup.from_dict(setup).zone_labels) == {"1": "Head"}
