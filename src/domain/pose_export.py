"""Pose export rules: columns, cell encodings and the metadata content. No I/O.

The format is specified for external readers in docs/POSE_DATA_FORMAT.md and is
independent of the Touch export (docs/DATA_FORMAT.md). One row per frame; a
label that was never set is an empty cell, never a default or a carried guess.
"""
import json
from decimal import Decimal

from domain.model import _normalize_param_state
from domain.pose import (POSE_ZONES, SCALE_MAX, SCALE_MIN, SCALE_NEUTRAL, PoseTables,
                         ScaleKind, ScaleSource, ZoneEvent)
from domain.pose_setup import PoseCodingSetup
from domain.touch_stats import fps_is_usable

POSE_EXPORT_FORMAT = "tinytouch.pose-export"
POSE_EXPORT_FORMAT_VERSION = 1
POSE_EXPORT_COLUMNS = (
    "Frame", "Time_ms",
    "Zones_On", "Zones_Off",
    "Body_Scale", "Body_Scale_Source",
    "Head_Scale", "Head_Scale_Source",
    "Quality",
    "Parameter_1", "Parameter_2", "Parameter_3",
    "Note",
)
INTERVAL_RULE = (
    "Pose has one global ON/OFF channel. Zones_On and Zones_Off name the zones "
    "clicked on a boundary frame. Any OFF closes the active interval, even when "
    "it was clicked on a different zone than the ON that opened it. Intervals "
    "are half-open [ON frame, OFF frame). A frame listing both ON and OFF zones "
    "is read as OFF."
)
_ZONE_ORDER = {zone: index for index, zone in enumerate(POSE_ZONES)}
_PARAMETER_KEYS = ("Par1", "Par2", "Par3")


def number_cell(value) -> str:
    """A stored scale or quality value as text.

    The controls store values rounded to 0.01, written with two decimals
    (`1.00`, `0.00`, `0.85`). A value stored with more digits keeps all of them.
    """
    text = f"{value:.2f}"
    return text if float(text) == value else repr(float(value))


class _NumberCells(dict):
    """value -> `number_cell(value)`, computed once per distinct value."""

    def __missing__(self, value):
        text = self[value] = number_cell(value)
        return text


def zones_cell(zones) -> str:
    """JSON array of zone IDs in `POSE_ZONES` order; empty cell for no zone."""
    ordered = sorted(zones, key=_ZONE_ORDER.__getitem__)
    return json.dumps(ordered, ensure_ascii=False) if ordered else ""


def _parameter_cell(frame, value) -> str:
    state = _normalize_param_state(value) or ""
    if state not in ("", "ON", "OFF"):
        raise ValueError(f"Frame {frame}: parameter state must be ON, OFF or unset")
    return state


def _boundary_cells(events) -> dict:
    """frame -> (Zones_On cell, Zones_Off cell) for frames with a boundary."""
    zones = {}
    for (frame, zone), event in events.items():
        zones.setdefault(frame, ([], []))[event is ZoneEvent.OFF].append(zone)
    return {frame: (zones_cell(on), zones_cell(off)) for frame, (on, off) in zones.items()}


def _reject_frames_past_the_end(tables, shared_frames, total_frames):
    last = max(
        max((frame for frame, _ in tables.events), default=-1),
        max(tables.quality, default=-1),
        max((frame for frame, _ in tables.scales), default=-1),
        max(shared_frames, default=-1),
    )
    if last > total_frames:
        raise ValueError(f"Frame {last} lies past the last video frame {total_frames}")


def pose_export_rows(tables: PoseTables, shared_frames, total_frames, frame_rate):
    """Yield one list of `POSE_EXPORT_COLUMNS` cells per frame 0..total_frames.

    `shared_frames` maps a frame to its `{"Note", "Params"}` bundle. Raises
    ValueError before the first row when a label lies outside the video, so
    nothing is silently dropped.
    """
    _reject_frames_past_the_end(tables, shared_frames, total_frames)
    fps = Decimal(str(frame_rate)) if fps_is_usable(frame_rate) else None
    boundaries = _boundary_cells(tables.events)
    quality, scales = tables.quality, tables.scales
    body_kind, head_kind = ScaleKind.BODY, ScaleKind.HEAD
    # Dense labels put this loop on hundreds of thousands of frames, with few
    # distinct values: texts are cached and the hot path avoids function calls.
    numbers = _NumberCells()
    sources = {source: source.value for source in ScaleSource}
    no_boundary = ("", "")
    no_scale = ("", "")
    thousand = Decimal(1000)

    for frame in range(total_frames + 1):
        on, off = boundaries.get(frame, no_boundary)
        body = scales.get((frame, body_kind))
        head = scales.get((frame, head_kind))
        value = quality.get(frame)
        # Time_ms: frame * 1000 / fps in decimal arithmetic, three decimals
        # (the Touch export's rule); empty without a usable frame rate.
        row = [frame, f"{frame * thousand / fps:.3f}" if fps else "", on, off]
        row += no_scale if body is None else (numbers[body.value], sources[body.source])
        row += no_scale if head is None else (numbers[head.value], sources[head.source])
        row.append("" if value is None else numbers[value])
        bundle = shared_frames.get(frame)
        if bundle is None:
            row += ("", "", "", "")
        else:
            params = bundle.get("Params") or {}
            row += [_parameter_cell(frame, params.get(key)) for key in _PARAMETER_KEYS]
            row.append(bundle.get("Note") or "")
        yield row


def special_zone_ids(rows) -> list:
    """Zone IDs marked in Special Zones: unique, in order of first dot ID.

    `rows` are stored `(dot_id, x, y, zones)` points; `zones` is comma-joined.
    """
    found = []
    for _, _, _, zones in sorted(rows, key=lambda row: row[0]):
        for zone in zones.split(","):
            if zone and zone not in found:
                found.append(zone)
    return found


def pose_export_metadata(*, program_version, video_name, labeling_mode, frame_rate,
                         total_frames, coding_setup, special_zones,
                         special_zones_note=None, labeling_time_seconds=None) -> dict:
    """The metadata document, in its published key order."""
    if not isinstance(coding_setup, PoseCodingSetup):
        raise ValueError("A Pose coding setup is required for the Pose export")
    setup = coding_setup.to_dict()
    # Every zone ID with its resolved label, as the Touch metadata does.
    setup["zone_labels"] = {zone: coding_setup.zone_labels.get(zone, zone)
                            for zone in POSE_ZONES}
    meta = {
        "Export Format": POSE_EXPORT_FORMAT,
        "Export Format Version": POSE_EXPORT_FORMAT_VERSION,
        "Program Version": program_version,
        "Annotation Type": "Pose",
        "Video Name": video_name,
        "Labeling Mode": labeling_mode,
        "Frame Rate": float(frame_rate) if fps_is_usable(frame_rate) else None,
        "Total Frames": total_frames + 1,
        "Frame Provenance": {"index_origin": 0, "time_unit": "milliseconds",
                             "time_decimal_places": 3,
                             "time_source": "frame_index / source_fps",
                             "frame_rate_source": "source video probe"},
        "Coding Setup": setup,
        "Value Conventions": {
            "empty_cell": "not set",
            "scale_range": [SCALE_MIN, SCALE_MAX],
            "scale_neutral": SCALE_NEUTRAL,
            "scale_sources": [source.value for source in ScaleSource],
            "quality_range": [0.0, 1.0],
            "parameter_states": ["ON", "OFF"],
        },
        "Interval Rule": INTERVAL_RULE,
        "Special Zones": list(special_zones),
        "Special Zones Note": special_zones_note or None,
    }
    if labeling_time_seconds is not None:
        meta["Total Labeling Time (hours)"] = round(float(labeling_time_seconds) / 3600, 4)
    return meta
