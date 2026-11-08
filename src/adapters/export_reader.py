"""
adapters/export_reader.py
Reading side of `export/<video>_export.csv` — the counterpart to
`adapters/export_writer.py`. All the file-format tolerance lives here so the
domain never touches a path:

  1. Current exports are plain CSVs whose first line IS the header.
  2. Legacy exports (pre-8.x) prefixed the table with a 6-line human-readable
     preamble (`Program Version: …`, `Video Name: …`, …). Those are retried
     with `skiprows=LEGACY_PREAMBLE_LINES`.

A file that yields no `Frame` column either way is unreadable and raises
`ExportReadError` (chained to the underlying pandas error). Missing FILES raise
the OSError as-is — a caller must be able to tell "no export yet" from
"corrupt export".

Column-level validation is deliberately NOT done here; it is a pure rule and
lives in `domain.touch_stats.validate_export_columns`.
"""

import logging

import pandas as pd


logger = logging.getLogger(__name__)

# Legacy exports carried metadata on the first 6 lines before the header row.
LEGACY_PREAMBLE_LINES = 6

_PARSE_ERRORS = (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError)


class ExportReadError(ValueError):
    """Raised when neither current nor legacy export CSV parsing succeeds."""


def read_export_df(export_path: str) -> pd.DataFrame:
    """Load an export CSV as a DataFrame, tolerating the legacy preamble.

    Raises the original OSError for a missing/unopenable file, and
    `ExportReadError` when the bytes cannot be parsed as either layout.
    """
    try:
        df = pd.read_csv(export_path)
        if "Frame" in df.columns:
            logger.debug("read export CSV %s (%d rows, current layout)", export_path, len(df))
            return normalize_export_df(df)
        last_exc = ValueError("required 'Frame' column is missing")
        logger.warning("current export CSV parse failed for %s: %s", export_path, last_exc)
    except OSError as exc:
        logger.error("cannot open export CSV %s: %r", export_path, exc)
        raise
    except _PARSE_ERRORS as exc:
        last_exc = exc
        logger.warning("current export CSV parse failed for %s: %r", export_path, exc)

    # Fallback for older exports with a 6-line metadata preamble.
    try:
        df = pd.read_csv(export_path, skiprows=LEGACY_PREAMBLE_LINES)
        if "Frame" in df.columns:
            logger.debug(
                "read export CSV %s (%d rows, legacy preamble layout)", export_path, len(df)
            )
            return normalize_export_df(df)
        last_exc = ValueError("required 'Frame' column is missing after legacy header")
        logger.warning("legacy export CSV parse failed for %s: %s", export_path, last_exc)
    except OSError as exc:
        logger.error("cannot open export CSV %s: %r", export_path, exc)
        last_exc = exc
    except _PARSE_ERRORS as exc:
        last_exc = exc
        logger.warning("legacy export CSV parse failed for %s: %r", export_path, exc)

    raise ExportReadError(
        f"Could not read export CSV {export_path}; current and legacy formats failed"
    ) from last_exc


def normalize_export_df(df):
    """Adapt v2 public channel columns to the private calculation vocabulary."""
    import json
    import math
    from domain.coding_setup import PORTABLE_CHANNELS
    if not any(column.startswith('Channel') for column in df.columns):
        return df
    result = df.copy()
    for channel,key in PORTABLE_CHANNELS.items():
        required = [f'{channel}_{suffix}' for suffix in ('XY','Onset','Zones')]
        missing = [column for column in required if column not in df.columns]
        if missing:
            raise ExportReadError('Missing v2 export columns: ' + ', '.join(missing))
        xs, ys = [], []
        for index,row in df.iterrows():
            try:
                points = json.loads(row[f'{channel}_XY'])
                zones = json.loads(row[f'{channel}_Zones'])
                if not isinstance(points,list) or not isinstance(zones,list) or len(points) != len(zones):
                    raise ValueError('point and zone buckets must align')
                if any(not isinstance(p,list) or len(p)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in p) for p in points):
                    raise ValueError('XY must contain finite numeric pairs')
                if any(not isinstance(z,list) or any(not isinstance(v,str) for v in z) for z in zones):
                    raise ValueError('Zones must contain lists of zone IDs')
            except (ValueError, TypeError) as exc:
                raise ExportReadError(f'Frame {index} {channel}: invalid aligned annotations: {exc}') from exc
            xs.append(','.join(str(p[0]) for p in points))
            ys.append(','.join(str(p[1]) for p in points))
        result[f'{key}_X'], result[f'{key}_Y'] = xs,ys
        for suffix in ('Onset','Zones','Parameter_1','Parameter_2','Parameter_3'):
            if f'{channel}_{suffix}' in df:
                result[f'{key}_{suffix}'] = df[f'{channel}_{suffix}']
    result.attrs['export_format_version'] = 2
    return result
