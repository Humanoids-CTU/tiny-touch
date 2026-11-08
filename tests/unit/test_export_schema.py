"""
Export-schema lock (regression tripwire).

External research pipelines read `export/<video>_export.csv` by column name and
order. This test pins the EXACT current columns of the touch export. It is GREEN
today and must stay green: any fix or feature that adds, removes, renames, or
reorders an export column turns it RED — which is the signal that the pipeline
contract is about to break.

If a schema change is ever genuinely intended, it must be coordinated with the
downstream pipeline and this golden list updated deliberately in the same change.

Run:  uv run pytest tests/ -k schema
"""
import pandas as pd

from adapters.export_writer import export_from_unified


TOUCH_EXPORT_COLUMNS = [
    "Frame", "Time_ms",
    "Channel1_XY", "Channel1_Onset", "Channel1_Zones",
    "Channel2_XY", "Channel2_Onset", "Channel2_Zones",
    "Channel3_XY", "Channel3_Onset", "Channel3_Zones",
    "Channel4_XY", "Channel4_Onset", "Channel4_Zones",
    "Parameter_1", "Parameter_2", "Parameter_3",
    "Channel1_Parameter_1", "Channel1_Parameter_2", "Channel1_Parameter_3",
    "Channel2_Parameter_1", "Channel2_Parameter_2", "Channel2_Parameter_3",
    "Channel3_Parameter_1", "Channel3_Parameter_2", "Channel3_Parameter_3",
    "Channel4_Parameter_1", "Channel4_Parameter_2", "Channel4_Parameter_3", "Note",
]


def test_touch_export_schema_is_frozen(tmp_path):
    out = tmp_path / "vid_export.csv"
    export_from_unified(
        {}, str(out), program_version=7.8, video_name="vid",
        labeling_mode="Normal", frame_rate=30.0, special_zones_list=None, total_frames=2,
    )
    cols = list(pd.read_csv(out).columns)
    assert cols == TOUCH_EXPORT_COLUMNS, (
        "Touch export schema drifted — downstream pipelines will break.\n"
        f"got:      {cols}\nexpected: {TOUCH_EXPORT_COLUMNS}"
    )
