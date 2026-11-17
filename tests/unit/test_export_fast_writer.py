"""The direct CSV writer must publish exactly the bytes the pandas route did.

`export_from_unified` used to build one dict per frame (an `empty_bundle()`
for every absent frame), then `pd.DataFrame(rows).to_csv(f, index=False)`.
That took ~20 s for a 3-hour video. The writer now streams rows itself and
emits one precomputed tail for absent frames. `_reference_export` below is
the retired pandas route, kept here as the oracle: the two must agree byte for
byte (line terminators included) over a long range of mostly absent frames.
"""
import json
from decimal import Decimal

import pandas as pd
import pytest

from adapters.export_writer import _paired_annotations, export_from_unified
from domain.coding_setup import PORTABLE_CHANNELS
from domain.model import _normalize_param_state, empty_bundle
from domain.touch_stats import fps_is_usable

LONG_RANGE = 20_000


def _reference_export(frames, path, frame_rate, total_frames):
    """The pre-optimization implementation, verbatim apart from the I/O."""
    rows = []
    fps = Decimal(str(frame_rate)) if fps_is_usable(frame_rate) else None
    for frame in range(total_frames + 1):
        bundle = frames.get(frame, empty_bundle())
        row = {'Frame': frame, 'Time_ms': f'{Decimal(frame)*1000/fps:.3f}' if fps else ''}
        for channel, key in PORTABLE_CHANNELS.items():
            rec = bundle.get(key) or {}
            xy, zones = _paired_annotations(rec, frame, channel)
            row[f'{channel}_XY'] = json.dumps(xy, ensure_ascii=False, allow_nan=False)
            row[f'{channel}_Onset'] = rec.get('Onset') or ''
            row[f'{channel}_Zones'] = json.dumps(zones, ensure_ascii=False)
        for i in (1, 2, 3):
            row[f'Parameter_{i}'] = _normalize_param_state((bundle.get('Params') or {}).get(f'Par{i}')) or ''
        for channel, key in PORTABLE_CHANNELS.items():
            params = (bundle.get(key) or {}).get('LimbParams') or {}
            for i in (1, 2, 3):
                row[f'{channel}_Parameter_{i}'] = _normalize_param_state(params.get(f'Par{i}')) or ''
        row['Note'] = bundle.get('Note') or ''
        rows.append(row)
    with open(path, 'w', encoding='utf-8', newline='') as stream:
        pd.DataFrame(rows).to_csv(stream, index=False)


def _sparse_frames():
    frames = {}
    for frame in (0, 1, 777, 9_999, LONG_RANGE):
        bundle = empty_bundle()
        bundle["LH"].update(X=[10 + frame % 50, 20], Y=[30, 40], Onset="ON", Zones=[["L"], ["I", "B"]])
        bundle["RL"]["LimbParams"] = {"Par2": "OFF", "Par3": "None"}
        bundle["Params"] = {"Par1": "ON", "Par2": None}
        frames[frame] = bundle
    for frame, note in ((5, "line1\nline2"), (6, '  "lead'), (7, "a\r\nb;c\t"), (8, 'comma, "quote" ěšč')):
        bundle = empty_bundle()
        bundle["Note"] = note
        frames[frame] = bundle
    frames[12] = empty_bundle()  # present but empty: same bytes as an absent frame
    return frames


@pytest.mark.parametrize("frame_rate", [25.0, 29.97, 0, None])
def test_long_mostly_empty_range_matches_the_pandas_bytes(tmp_path, frame_rate):
    frames = _sparse_frames()
    fast, reference = tmp_path / "fast.csv", tmp_path / "reference.csv"

    export_from_unified(frames, str(fast), "test", "vid", "Normal", frame_rate, None,
                        total_frames=LONG_RANGE)
    _reference_export(frames, str(reference), frame_rate, LONG_RANGE)

    assert fast.read_bytes() == reference.read_bytes()


def test_invalid_annotation_is_rejected_and_nothing_is_written(tmp_path):
    bundle = empty_bundle()
    bundle["RH"].update(X=[1, 2], Y=[3], Zones=[["A"]])
    out = tmp_path / "export.csv"
    with pytest.raises(ValueError, match="align"):
        export_from_unified({LONG_RANGE // 2: bundle}, str(out), "test", "vid", "Normal", 25, None,
                            total_frames=LONG_RANGE)
    assert list(tmp_path.iterdir()) == []
