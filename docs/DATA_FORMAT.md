# TinyTouch export data format

## Version 2 contract

New saves write export format **2**. This is an intentional breaking change from
unversioned anatomical-column exports. Keep the CSV together with its metadata JSON and labeled diagram PNG.
SQLite working state still uses its established internal keys; no state migration occurs.

Paths remain `data/<video>/export/<video>_export.csv` and
`data/<video>/export/<video>_metadata.json`. Before the first version 2 save replaces
an older export, both existing files are copied unchanged into a timestamped
`export/legacy-<UTC timestamp>/` folder. Analysis can still read those older CSVs,
including the pre-v8 six-line preamble, without modifying them.

The save service validates and stages all three files before replacing published
files. Ordinary replacement failures restore the previous set. Separate files
cannot be replaced in one filesystem transaction: a process or machine crash between
replacements may require regenerating exports from the SQLite working state.

## CSV columns and values

UTF-8 without BOM, standard comma-separated CSV with a header and **one row for every
frame**, including empty frames. `Frame` is zero based. The last frame index is
included. The exact 30-column order is:

1. `Frame`, `Time_ms`
2. For each of `Channel1`, `Channel2`, `Channel3`, `Channel4`, in order:
   `ChannelN_XY`, `ChannelN_Onset`, `ChannelN_Zones`
3. `Parameter_1`, `Parameter_2`, `Parameter_3`
4. For each channel in the same order:
   `ChannelN_Parameter_1`, `ChannelN_Parameter_2`, `ChannelN_Parameter_3`
5. `Note`

Public channel IDs are stable and independent of editable study labels. Their
private state mapping is RH -> Channel1, LH -> Channel2, RL -> Channel3,
LL -> Channel4. No anatomical prefix is emitted in version 2 columns.

`ChannelN_XY` is a JSON array of numeric coordinate pairs, for example
`[[120, 130], [9, 0]]`. `ChannelN_Zones` is a matching array of zone buckets,
for example `[["A", "B"], ["OUTSIDE"]]`. The first point belongs to A and B;
the second belongs to OUTSIDE. All points and all zone memberships are retained.
An empty annotation has `[]` in both cells. A point without a recorded zone has
an empty bucket, such as `[[]]`. X/Y length differences and ambiguous point/zone
alignment are rejected instead of silently dropping data. Legacy state containing
one point with flat multiple zones is normalized into one multi-zone bucket.

`Time_ms` is `Frame * 1000 / source_fps`, serialized to **three decimal places**:
frame 201 at 25 FPS is `8040.000`; frame 1 at 30 FPS is `33.333`.
Missing, zero, negative or non-finite FPS produces an **empty time cell**. Frame
indices remain usable. FPS is retained at the source probe precision, not rounded
to one decimal place. This is a constant-frame-rate index-derived time, not an
independently probed presentation timestamp for variable-frame-rate video.

Onset and parameter cells contain `ON`, `OFF`, or an empty cell. `Note` is arbitrary
text. Read empty scalar cells as empty strings, for example with pandas
`keep_default_na=False`. Use a real CSV parser before applying `json.loads` to XY
and Zones. CSV necessarily quotes fields containing commas or quotes and doubles
embedded quotes: this is CSV encoding, not extra annotation data.

## Metadata snapshot

CSV format remains **2**. New metadata has `"Metadata Format Version": 2`;
metadata without that key is the older revision. Analysis reads both revisions.
External readers of new exports must use the paths below rather than the retired
`Param Labels`, `Channel Param Labels`, `Channel Labels`, and `Zone Labels` fields.

- `Program Version`, `Video Name`, `Labeling Mode`, `Frame Rate`: export context.
- `Coding Setup`: the single authoritative settings snapshot. It includes the
  setup name and schema version, `template`, `zone_labels`, `channel_labels`,
  `parameter_labels`, and `channel_parameter_labels`. Channel keys are Channel1..4;
  parameter keys Par1..3 correspond to CSV Parameter_1..3 and
  ChannelN_Parameter_1..3. Zone labels contain overrides; an unlisted zone retains
  its ID as its name. The setup can still be reused as a coding configuration.
- `Diagram`: source diagram/mask asset identifiers, `image` (the companion PNG's
  relative filename), and `image_sha256` (checksum of that PNG).
- `Coordinate Convention`: native diagram size, top-left origin, x right, y down,
  and diagram-pixel units. These are not video-pixel coordinates.
- `Frame Provenance`: zero-based indexing, milliseconds, and the rounding rule.
- `Special Zones`, `Special Zones Note`, and optional cumulative
  `Total Labeling Time (hours)` retain their existing meanings.

Each normal application save publishes `<video>_diagram.png` alongside the CSV
and JSON. It contains the project's diagram with CSV zone IDs burned into their
regions and a full ID-to-saved-name legend, including boundary/unmatched markers.
The reference image is enlarged and has margins: exported XY coordinates still
refer to the native diagram, not the reference PNG. It has no per-frame dots or
selected-channel highlight. Labels come from the saved coding setup, not current
machine preferences. Assets are the selected template assets installed at export
time; this does not reconstruct historical assets from an older app installation.

Before replacing an older metadata revision, existing export files are archived
unchanged in `legacy-<UTC timestamp>/`. CSV, JSON, and PNG are staged before
publication, and ordinary replacement failures restore the previous files. A
process/machine crash between replacements can still require regenerating the
export from SQLite. Keep all three files together when sharing a dataset.

Version 2 analysis tables use a `Channel` ID column and heatmap files use
`heatmap_ChannelN.html`. Internal calculations retain their established keys.
Old unversioned exports retain their legacy analysis filenames/table IDs.

## 3. Semantic conventions

These are the scientifically load-bearing rules. They are implemented in
[`src/domain/touch_stats.py`](../src/domain/touch_stats.py), which is the normative
reference; anything computing statistics from the export should follow them so numbers are
comparable across studies.

### A touch episode is half-open: `[ON, OFF)`

An episode starts on the frame carrying `ON` and ends on the frame carrying the next `OFF`.
Its duration is

```
duration_frames = OFF_frame - ON_frame
```

The touch is **active on the onset frame** and the **offset frame is excluded**. The
shortest possible closed touch is therefore 1 frame (`ON` at *f*, `OFF` at *f+1*), not 0.
This matches the interval the app shades on its timeline, so the published numbers agree
with what the annotator saw.

Duration in seconds is `duration_frames / frame_rate`, and is undefined when the frame rate
is unusable (`None`, `0`, negative).

### Unterminated touches are censored, not completed

An `ON` with no matching `OFF` before the end of the file is a **censored** episode. It has
no end frame and no duration. It is excluded from durations, totals, percentages, means,
standard deviations, transition counts and both histograms — but it is **not** discarded:
TinyTouch reports it separately as an "open (unterminated) touch", with its start frame, in
the analysis tables, on the dashboard and in the log.

Treating it as a touch that runs to the end of the video would let one stray onset dominate
every statistic, so any independent reimplementation should censor it the same way. A
stray `OFF` with no preceding `ON` belongs to no episode and is ignored entirely.

### Multi-zone transitions are counted pairwise

A zone transition is (deduplicated start zones) × (deduplicated end zones). An episode whose
`ON` row resolved to 2 zones and whose `OFF` row resolved to 2 zones contributes **4**
counts to the transition matrix.

Consequence: **heatmap totals are greater than or equal to the number of touches and must
not be read as a touch count.** The heatmap subtitle in the dashboard says so.

When an episode edge carries no zone at all, the transition uses the sentinel `NN` so the
touch is still represented. The per-zone *touch count* deliberately does **not** get that
sentinel — it counts observed zones only.

### `minimal_touch_length` filters nothing

The `minimal_touch_length` key in `config.json` is a **visualization threshold in
milliseconds**. The app displays its frame equivalent as a readout for the annotator.
Analysis has never filtered by it and does not now: every closed episode, including
1-frame ones, is counted. If you want a minimum-duration criterion, apply it yourself,
downstream, and report it.

### Onsets per touch

Extra `ON` rows *inside* an already-open episode do not start a new touch; they increment
that episode's onset count and their clicks are recorded as mid-touch waypoints. The
"touch length distribution" histogram plots this onset count, which is why its x-axis is
labeled "number of onsets" rather than a duration.

---

## 4. Zone names

Zone names in `ChannelN_Zones` are the **file names of the zone-mask PNGs**, minus the
extension. Adding a PNG to the mask directory adds a zone; nothing else needs to change.

| Template | Directory | Zones |
| --- | --- | --- |
| Default | [`src/resources/icons/zones3/`](../src/resources/icons/zones3/) | 38 masks: `A`–`Z`, `WB`, `XB`, `YB`, `ZB`, `BOX1`–`BOX6`, `LINE`, `OUTSIDE` |
| Alternate | [`src/resources/icons/zones3_new_template/`](../src/resources/icons/zones3_new_template/) | 32 masks: `A`–`T`, `QB`, `RB`, `SB`, `TB`, `BOX1`–`BOX6`, `LINE`, `OUTSIDE` |
| General | [`src/resources/icons/zones_general/`](../src/resources/icons/zones_general/) | 14 masks: `1`–`8`, `Channel1`–`Channel4`, `LINE`, `OUTSIDE`. Eight square targets, numbered left-to-right, top-to-bottom in two columns (the IDs are not printed on the diagram; the labeler draws them when zone names are shown), plus the four footer boxes, one per channel in portable order, so a channel can itself be the target of a touch (as a hand or leg can on the anatomical diagrams). |

Select a video from the library, then choose Default, Alternate, or General in the
preparation wizard. The prepared project choice determines the annotation diagram, Special Zones outline, and channel images. **The zone name alone does not tell you which
template produced it** — `A` means different anatomy in the two sets. Keep the metadata JSON with your dataset: its `Coding Setup.template` field identifies the set (top-level `template` in older metadata).

Special names:

- `BOX1` … `BOX6` — the six catch-all boxes drawn beside the body diagram. They have no
  fixed anatomical meaning; teams assign them (ground, prop, caregiver, ...) by convention.
- `OUTSIDE` — the click fell in the region masked as outside the body.
- `LINE` — the click fell exactly on a boundary line between zones, so the intended zone is
  genuinely **ambiguous**. It is recorded only when no other mask claims the pixel (see the
  precedence below), which makes it a meaningful "cannot tell" marker rather than an
  artifact of zone naming.
- `NN` — **no mask matched**. This is a sentinel produced by the hit test, not a mask file.
  It appears in `ChannelN_Zones` cells and, for transitions only, stands in for an episode
  edge that carries no zone at all.

Masks are grayscale PNGs where the zone is drawn in **black on white**; a click hits a zone
when the mask pixel under it is 0. The masks OVERLAP — 1.4% (default set) / 2.2%
(alternate set) of the diagram is claimed by two or more of them, nearly all of it the
`LINE` mask lying on top of the zones it separates — so the winner is decided by
**precedence** (highest first):

1. any real anatomical zone,
2. `BOX1`–`BOX6`,
3. `OUTSIDE`,
4. `LINE`,
5. `NN`, only when no mask matched at all.

Ties within one level fall back to sorted filename order, so the result is always
deterministic; in the shipped mask sets that only ever happens on the borders two boxes
share.

> **Datasets written by TinyTouch 8.0.0 and earlier** used plain "first mask in sorted
> filename order wins", which made the outcome depend on the zone's NAME: an edge click on `Q` was
> recorded as `LINE` while the identical click on `F` was recorded as `F`. The change affects
> 0.6% (default) / 1.1% (alternate) of the diagram area; every changed pixel previously read
> `LINE` and now reads the zone that actually covers it (mostly `OUTSIDE`). Nothing else in
> the format changed.

---

## Reading version 2

```python
import json
import pandas as pd

df = pd.read_csv("video_export.csv", keep_default_na=False)
points = json.loads(df.loc[0, "Channel1_XY"])
buckets = json.loads(df.loc[0, "Channel1_Zones"])
assert len(points) == len(buckets)
for (x, y), zones in zip(points, buckets):
    print(x, y, zones)
```

Existing unversioned datasets use separate comma-joined LH/LL/RH/RL X and Y
columns and nested JSON Zones. They are archival inputs, not the current writer
contract. The original legacy byte fixture remains in the test suite alongside
the version 2 golden fixture.
