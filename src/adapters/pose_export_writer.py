"""Pose export files: the per-frame CSV and its metadata JSON (write only).

The cell and metadata rules live in `domain.pose_export`; this module only
streams them to disk. Both files are written whole and atomically. Neither
function touches SQLite or Tk, so they may run on a worker thread against
detached data (`PoseLabels.tables()` and a copy of the shared frames).
"""
import csv
import json
import logging
import os

from adapters.atomic_io import atomic_write
from domain.pose_export import POSE_EXPORT_COLUMNS, pose_export_metadata, pose_export_rows

logger = logging.getLogger(__name__)
# The platform line end, like the Touch export: CRLF on Windows, LF elsewhere.
CSV_LINE_TERMINATOR = os.linesep


def write_pose_export_csv(out_csv, tables, shared_frames, *, total_frames, frame_rate):
    """Write one row per zero-based frame, including the last frame index.

    UTF-8 without BOM, csv QUOTE_MINIMAL. Raises ValueError (and writes
    nothing) when a label lies past the last frame.
    """
    def write(stream):
        writer = csv.writer(stream, lineterminator=CSV_LINE_TERMINATOR)
        writer.writerow(POSE_EXPORT_COLUMNS)
        writer.writerows(pose_export_rows(tables, shared_frames, total_frames, frame_rate))

    atomic_write(out_csv, write)
    logger.debug("Pose export -> %s (rows=%d)", out_csv, max(total_frames + 1, 0))


def write_pose_export_metadata(meta_path, **fields):
    """Write the metadata document built by `domain.pose_export.pose_export_metadata`."""
    meta = pose_export_metadata(**fields)
    atomic_write(meta_path, lambda f: json.dump(meta, f, indent=2, ensure_ascii=False,
                                                allow_nan=False))
