# TinyTouch Pose export data format

## Version 1

A 3D Pose project publishes its own export, separate from the Touch export
described in [DATA_FORMAT.md](DATA_FORMAT.md). It was introduced in TinyTouch
9.5.0. Pose projects saved by earlier versions have no export until they are
opened and saved once.

Every successful Pose save writes two files:

```text
data/<video>/export/<video>_pose_export.csv
data/<video>/export/<video>_pose_metadata.json
```

`<video>` is the project folder name. A Reliability pass has the folder name
`<video>_reliability`, so its files are
`<video>_reliability_pose_export.csv` and `<video>_reliability_pose_metadata.json`.
A Touch project of the same video keeps its own files
(`<video>_export.csv`, `<video>_metadata.json`, `<video>_diagram.png`) in the same
folder; the two exports never share a file. There is no Pose diagram PNG.

The working database `state/<video>_pose.db` is the source of truth. The export
is regenerated from it. Both files are written whole and replaced atomically,
the CSV first and the metadata second. If a file cannot be replaced (typically
because the CSV is open in Excel), the labels are still saved, the previous
export pair stays in place, and TinyTouch reports that the export is out of
date. Keep the two files together when sharing a dataset.

## CSV

UTF-8 without BOM, comma-separated, standard CSV quoting, one header line and
**one row for every frame**, including frames without any label. `Frame` is
zero based and the last frame index is included. Line ends follow the platform
that wrote the file (CRLF on Windows).

The 13 columns, in this order:

| Column | Content |
| --- | --- |
| `Frame` | Zero-based frame index |
| `Time_ms` | `Frame * 1000 / frame rate`, three decimals; empty when the frame rate is unusable |
| `Zones_On` | JSON array of the zone IDs with an ON boundary on this frame; empty when none |
| `Zones_Off` | JSON array of the zone IDs with an OFF boundary on this frame; empty when none |
| `Body_Scale` | Body size factor, 0.50 to 1.50; empty when not set |
| `Body_Scale_Source` | `manual` or `carried`; empty when `Body_Scale` is empty |
| `Head_Scale` | Head size factor, 0.50 to 1.50; empty when not set |
| `Head_Scale_Source` | `manual` or `carried`; empty when `Head_Scale` is empty |
| `Quality` | Frame quality, 0.00 to 1.00; empty when not set |
| `Parameter_1` | `ON`, `OFF` or empty |
| `Parameter_2` | `ON`, `OFF` or empty |
| `Parameter_3` | `ON`, `OFF` or empty |
| `Note` | Free text; empty when there is no note |

### Empty cells

An empty cell means the label was **not set on that frame**. The export never
fills gaps and never substitutes a default:

- A frame the annotator did not reach has empty scale and quality cells, even
  if the frames before and after it have values.
- Quality `0.00` and scale `1.00` (neutral size) are explicit values that were
  saved, not placeholders.

Read the file so that empty cells stay empty strings, for example with pandas
`keep_default_na=False`, or convert them to missing values deliberately.

### Zone cells

`Zones_On` and `Zones_Off` hold JSON arrays of zone IDs, for example
`["A", "L", "BOX2"]`. In the raw file the cell is quoted and its quotes are
doubled (`"[""A"", ""L"", ""BOX2""]"`); this is CSV encoding. Parse the file
with a CSV reader first, then apply a JSON parser to non-empty cells.

IDs are always the fixed zone IDs of the Alternate diagram, never the names
the study gave them. The names are in the metadata (`Coding Setup.zone_labels`).
The 30 possible IDs, in the order used inside a cell, are `A` to `T`, `QB`,
`RB`, `SB`, `TB`, `BOX1` to `BOX6`.

Most boundary frames list zones in only one of the two columns, because a new
click sets the kind (ON or OFF) of every zone on that frame. Projects from
experimental builds can hold a frame with both; see the interval rule below.

### Scale, source and quality

Values are written as stored. The app stores them rounded to 0.01, so they
appear with two decimals (`1.20`, `0.85`, `1.00`). A stored value with more
digits would be written with all of them.

`manual` means the annotator set the value on that frame. `carried` means the
app copied the current value onto the frame while the annotator stepped or
played forward. Quality has no stored source: a carried quality value looks the
same as a typed one.

### Time

`Time_ms` is derived from the frame index and the source frame rate (constant
frame rate assumed), as in the Touch export: frame 1 at 30 FPS is `33.333`.
A missing, zero, negative or non-finite frame rate gives an empty cell on every
row; all other columns are unaffected.

### Example

```csv
Frame,Time_ms,Zones_On,Zones_Off,Body_Scale,Body_Scale_Source,Head_Scale,Head_Scale_Source,Quality,Parameter_1,Parameter_2,Parameter_3,Note
0,0.000,,,,,,,,,,,
1,40.000,"[""A"", ""L"", ""BOX2""]",,1.20,manual,1.00,manual,0.00,,,,
2,80.000,,,1.20,carried,1.00,carried,0.00,,,,
3,120.000,,,,,,,,,,,
4,160.000,,"[""B""]",,,,,0.85,ON,,OFF,"rolled over, twice"
```

## Metadata JSON

UTF-8, two-space indentation. Keys, in file order:

| Key | Content |
| --- | --- |
| `Export Format` | Always `tinytouch.pose-export`; identifies a Pose export |
| `Export Format Version` | `1` for the format described here |
| `Program Version` | TinyTouch version and platform that wrote the files |
| `Annotation Type` | Always `Pose` |
| `Video Name` | Project folder name (ends in `_reliability` for a Reliability pass) |
| `Labeling Mode` | `Normal` or `Reliability` |
| `Frame Rate` | Source frame rate, or `null` when unusable |
| `Total Frames` | Number of frames, equal to the number of CSV data rows; the last `Frame` is `Total Frames - 1` |
| `Frame Provenance` | Zero-based indexing, millisecond unit, three decimals, how time is derived |
| `Coding Setup` | The project's complete Pose coding setup (below) |
| `Value Conventions` | Value ranges, the neutral scale, the source and parameter vocabularies |
| `Interval Rule` | The interval rule below, as text |
| `Special Zones` | Zone IDs marked in the project-wide Special Zones dialog: unique, ordered by mark number; `[]` when none |
| `Special Zones Note` | The Special Zones note, or `null` when empty |
| `Total Labeling Time (hours)` | Cumulative labeling time; present when known |

`Coding Setup` contains `schema_version`, `name`, `template` (always
`alternate`), `annotation_type` (`Pose`), `parameter_labels` and `zone_labels`.
`parameter_labels` maps `Par1`, `Par2`, `Par3` to the study's names for the CSV
columns `Parameter_1`, `Parameter_2`, `Parameter_3`. `zone_labels` lists every
zone ID with its name; a zone that was not renamed has its ID as its name.

`Special Zones` describe the whole video, not single frames. A mark placed
outside every zone is listed as `NN` (no zone matched), the same sentinel the
Touch export uses.

## Semantic conventions

### One global ON/OFF channel

Pose has a single interval channel. `Zones_On` and `Zones_Off` say **where** a
boundary was clicked; they do not create one channel per zone.

- **Any OFF closes the active interval**, even when it was clicked on a
  different zone than the ON that opened it.
- Intervals are half-open, `[ON frame, OFF frame)`: active on the ON frame, not
  on the OFF frame. Duration in frames is `OFF frame - ON frame`.
- An ON while an interval is already active does not start a second interval.
- A frame listing zones in both `Zones_On` and `Zones_Off` is read as OFF.
- An ON with no later OFF is an open interval with no end; an OFF with no
  active interval closes nothing. The export writes both as they are stored.

### Independent labels

Zone boundaries, body scale, head scale, quality, parameters and notes are
independent of each other. Any of them can be set on a frame where the others
are empty.

### Reading the files

```python
import json
import pandas as pd

df = pd.read_csv("video_pose_export.csv", keep_default_na=False)
meta = json.load(open("video_pose_metadata.json", encoding="utf-8"))
assert meta["Export Format"] == "tinytouch.pose-export"
assert meta["Export Format Version"] == 1

names = meta["Coding Setup"]["zone_labels"]
for _, row in df[df["Zones_On"] != ""].iterrows():
    print(row["Frame"], [names[zone] for zone in json.loads(row["Zones_On"])])

body = pd.to_numeric(df["Body_Scale"])   # empty cells become NaN
```
