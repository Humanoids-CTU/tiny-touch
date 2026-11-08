"""Version 2 research exports. SQLite storage keys remain private to the app."""
import json
import logging
import math
from decimal import Decimal
from dataclasses import replace
from typing import Dict

import pandas as pd

from adapters.atomic_io import atomic_write
from adapters.export_diagram import write_export_diagram
from adapters.zone_masks import list_zone_names
from domain.coding_setup import PORTABLE_CHANNELS, default_coding_setup
from domain.templates import get_template, validate_template
from domain.model import FrameBundle, _normalize_param_state, empty_bundle
from domain.touch_stats import fps_is_usable

logger = logging.getLogger(__name__)
EXPORT_FORMAT_VERSION = 2


def write_export_metadata(meta_path, program_version, video_name, labeling_mode,
                          frame_rate, special_zones_list, param_labels=None,
                          limb_param_labels=None, labeling_time_seconds=None, *,
                          template, special_zones_note=None, zone_labels=None,
                          coding_setup=None, diagram_path=None):
    template = validate_template(template)
    setup = coding_setup or default_coding_setup(
        template,
        {f'Par{i}': (param_labels or {}).get(f'Parameter_{i}', (param_labels or {}).get(f'Par{i}', f'P{i}')) for i in (1,2,3)},
        {f'Par{i}': (limb_param_labels or {}).get(f'XX_Parameter_{i}', (limb_param_labels or {}).get(f'Par{i}', f'CP{i}')) for i in (1,2,3)},
    )
    if coding_setup is None:
        setup = replace(setup, zone_labels=zone_labels if zone_labels is not None else {})
    if setup.template != template:
        raise ValueError('Coding setup template does not match export template')
    definition = get_template(template)
    diagram = {'asset': definition.diagram, 'zone_masks': definition.masks_directory}
    if diagram_path is not None:
        diagram.update(write_export_diagram(diagram_path, setup))
    setup_snapshot = setup.to_dict()
    setup_snapshot['zone_labels'] = {
        zone: setup.zone_labels.get(zone, zone)
        for zone in list_zone_names(template, coding_setup=setup)
    }
    meta = {
        'Export Format Version': EXPORT_FORMAT_VERSION,
        'Metadata Format Version': 2,
        'Program Version': program_version, 'Video Name': video_name,
        'Labeling Mode': labeling_mode,
        'Frame Rate': float(frame_rate) if fps_is_usable(frame_rate) else None,
        'Frame Provenance': {'index_origin': 0, 'time_unit': 'milliseconds',
                             'time_decimal_places': 3, 'time_source': 'frame_index / source_fps',
                             'frame_rate_source': 'source video probe'},
        'Coordinate Convention': {'origin': 'top-left', 'x_direction': 'right',
                                  'y_direction': 'down', 'unit': 'diagram pixel',
                                  'diagram_size': list(definition.native_size)},
        'Coding Setup': setup_snapshot,
        'Diagram': diagram,
        'Special Zones': special_zones_list, 'Special Zones Note': special_zones_note,
    }
    if labeling_time_seconds is not None:
        meta['Total Labeling Time (hours)'] = round(float(labeling_time_seconds) / 3600, 4)
    atomic_write(meta_path, lambda f: json.dump(meta, f, indent=2, ensure_ascii=False, allow_nan=False))


def _paired_annotations(rec, frame, channel):
    xs, ys = rec.get('X') or [], rec.get('Y') or []
    if len(xs) != len(ys):
        raise ValueError(f'Frame {frame} {channel}: X/Y point lists must align')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in [*xs, *ys]):
        raise ValueError(f'Frame {frame} {channel}: coordinates must be finite numbers')
    zones = rec.get('Zones') or []
    # Older state may have clicks without zone hits. Retain the clicks explicitly.
    if not zones:
        zones = [[] for _ in xs]
    elif len(xs) == 1 and all(isinstance(z, str) for z in zones):
        zones = [zones]  # old flat multi-zone bucket, no relationship is lost
    else:
        zones = [[z] if isinstance(z, str) else z for z in zones]
    if len(zones) != len(xs) or any(not isinstance(z,list) or any(not isinstance(v,str) for v in z) for z in zones):
        raise ValueError(f'Frame {frame} {channel}: point and zone buckets must align')
    return list(map(list, zip(xs,ys))), zones


def export_from_unified(frames: Dict[int, FrameBundle], out_csv, program_version,
                        video_name, labeling_mode, frame_rate, special_zones_list,
                        total_frames, param_labels=None, limb_param_labels=None):
    """Write one row per zero-based frame, including the last frame index."""
    rows = []
    fps = Decimal(str(frame_rate)) if fps_is_usable(frame_rate) else None
    for frame in range(total_frames + 1):
        bundle = frames.get(frame, empty_bundle())
        row = {'Frame':frame, 'Time_ms': f'{Decimal(frame)*1000/fps:.3f}' if fps else ''}
        for channel, key in PORTABLE_CHANNELS.items():
            rec = bundle.get(key) or {}
            xy, zones = _paired_annotations(rec, frame, channel)
            row[f'{channel}_XY'] = json.dumps(xy, ensure_ascii=False, allow_nan=False)
            row[f'{channel}_Onset'] = rec.get('Onset') or ''
            row[f'{channel}_Zones'] = json.dumps(zones, ensure_ascii=False)
        for i in (1,2,3):
            row[f'Parameter_{i}'] = _normalize_param_state((bundle.get('Params') or {}).get(f'Par{i}')) or ''
        for channel,key in PORTABLE_CHANNELS.items():
            params = (bundle.get(key) or {}).get('LimbParams') or {}
            for i in (1,2,3):
                row[f'{channel}_Parameter_{i}'] = _normalize_param_state(params.get(f'Par{i}')) or ''
        row['Note'] = bundle.get('Note') or ''
        rows.append(row)
    atomic_write(out_csv, lambda f: pd.DataFrame(rows).to_csv(f, index=False))
    logger.debug('Export v2 -> %s (rows=%d)', out_csv, len(rows))
