"""
adapters/export_reader.py
Reading side of `export/<video>_export.csv` — the counterpart to
`adapters/export_writer.py`. Only export format 2 (`Channel1`..`Channel4`
columns, header on the first line) is read. Unversioned exports from before
format 2, including the pre-8.x layout with a 6-line preamble, are rejected
with `ExportReadError` rather than analysed.

A file that cannot be parsed, has no `Frame` column, or is not a format 2
export raises `ExportReadError` (chained to the underlying pandas error where
there is one). Missing FILES raise the OSError as-is — a caller must be able to
tell "no export yet" from "corrupt export".

Column-level validation of the translated table is deliberately NOT done here;
it is a pure rule and lives in `domain.touch_stats.validate_export_columns`.
"""

import logging

import pandas as pd


logger = logging.getLogger(__name__)

_PARSE_ERRORS = (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError)

UNVERSIONED_EXPORT_MESSAGE = (
    "is not a TinyTouch export format 2 file (no Channel1..Channel4 columns). "
    "Unversioned exports from older TinyTouch versions can no longer be analysed."
)


class ExportReadError(ValueError):
    """Raised when an export CSV cannot be read as export format 2."""


def read_export_df(export_path: str) -> pd.DataFrame:
    """Load a format 2 export CSV as a DataFrame in the calculation vocabulary.

    Raises the original OSError for a missing/unopenable file, and
    `ExportReadError` when the bytes are not a readable format 2 export.
    """
    try:
        df = pd.read_csv(export_path)
    except OSError as exc:
        logger.error("cannot open export CSV %s: %r", export_path, exc)
        raise
    except _PARSE_ERRORS as exc:
        logger.warning("export CSV parse failed for %s: %r", export_path, exc)
        raise ExportReadError(f"Could not read export CSV {export_path}") from exc
    if "Frame" not in df.columns:
        logger.warning("export CSV %s has no 'Frame' column", export_path)
        raise ExportReadError(
            f"Could not read export CSV {export_path}: required 'Frame' column is missing"
        )
    if not any(str(column).startswith("Channel") for column in df.columns):
        logger.warning("export CSV %s is unversioned; refusing to analyse it", export_path)
        raise ExportReadError(f"Export CSV {export_path} {UNVERSIONED_EXPORT_MESSAGE}")
    logger.debug("read export CSV %s (%d rows)", export_path, len(df))
    return normalize_export_df(df)


def normalize_export_df(df):
    """Adapt v2 public channel columns to the private calculation vocabulary."""
    import json
    import math
    from domain.coding_setup import PORTABLE_CHANNELS
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
    return result
