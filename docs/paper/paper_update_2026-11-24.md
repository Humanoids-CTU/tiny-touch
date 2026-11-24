# Paper update against the code (2026-11-24)

Checked against the article PDF of 2026-11-24 and the code after v9.4.0
(including the unreleased changes up to 2026-11-24).

Three parts:

1. Things to solve before the text is final.
2. Section 2.3, rewritten, ready to paste.
3. Comments to add to paragraphs written by others.

## 1. To solve

- [ ] **Performance table (Section 2.4.5).** The draft has the placeholder
  "[ASK LUKAS for performance TABLE]" under "Display and performance settings".
  The co-authors expect a table from you; nothing in the repository defines its
  content. Ask them what it should show before measuring anything.
- [ ] **Figure.** Replace the figure in the document with the updated
  `figures/sw_architecture.png`.
- [ ] **Commit and build.** The `resource_utils` move is not committed, and the
  frozen build was not tested after it. Build the executable once and open a
  project before the next release.

Decided on 2026-11-24:

- Linux: no build of the current version; the text names 9.3.0 as the latest
  Linux version.
- Pose: mentioned in one sentence at the end of Section 2.3.

Solved on 2026-11-24:

- Adapters no longer import from the `gui` package (`resource_utils.py` moved to
  `src/`, with a test that guards it). "Dependencies point in one direction only"
  is now true as written.
- Figure: the `export/` box now reads "CSV · JSON · diagram PNG" and the Export
  adapter "CSV · JSON · PNG" (SVG and PNG both updated).
- README: "New in 9.4.1" section added, Linux note updated, `D` key added to the
  controls table.

## 2. Section 2.3 Software architecture: replace the whole section with this

What changed compared with the PDF: the section references (2.3.x became 2.4.x),
the Linux version in brackets, "first opened" became "prepared", "continuous
playback" became "real-time playback", the export sentence now lists the three
exported files, and a closing sentence mentions 3D Pose.

> TinyTouch is a desktop application written in Python 3.12 with a Tkinter
> graphical interface, using open-source components including: ffmpeg (with OpenCV
> as a fallback) for frame extraction, Pillow for image decoding, SQLite for storing
> work in progress, pandas for tabular output, and Plotly for analysis reports. It
> is distributed as a standalone executable for Windows (and for Linux up to
> version 9.3.0) that requires no Python installation, and it runs fully offline,
> so video recordings of participants never leave the researcher's computer. The code is organized in four
> layers (Fig. X). The domain layer contains the annotation rules (the per-frame
> data model, the assignment of each click to a zone on the selected template, and
> the reconstruction of touch episodes and their statistics) and has no file,
> interface, or plotting code. Adapters handle all input and output, services
> orchestrate the use cases (opening a project, annotating, saving, analyzing), and
> the graphical interface sits on top. Dependencies point in one direction only,
> towards the domain layer, which is independent of the other application layers;
> this keeps the rules testable and their results reproducible independently of the
> interface.
>
> Each video becomes a self-contained project folder. When a video is prepared, all
> its frames are extracted once to image files; during coding, a background buffer
> decodes the frames around the current position, supporting frame-by-frame stepping
> and real-time playback without an external media player (Section 2.4.4).
> Annotations are kept in memory and saved to a per-video SQLite database, from
> which work is resumed; each database save is a single transaction, protecting the
> stored annotations from partially completed database writes. Every save also
> brings the export up to date: a CSV file with one row per video frame, a JSON file
> recording the frame rate, annotation template, zone, channel and parameter labels,
> and labeling time, and an image of the labeled diagram (Section 2.4.6). The export
> format is documented, and the built-in analysis (Section 2.4.7) reads only the CSV
> and JSON files, so its results can be reproduced from the exported data alone.
> Automated tests, including tests that check the export format byte for byte,
> protect this behavior as the software evolves. In addition to touch coding, the
> software includes a second annotation type, 3D Pose, which records body-zone
> events and body and head size per frame; it uses the same video handling, stores
> its labels in a separate database, and does not yet have an export.

Figure caption: unchanged.

## 3. Comments for paragraphs written by others

Each block is one comment. Paste it on the quoted words.

### 2.4 Software functionalities (intro)

On "can be changed in the settings":

> The location map is not changed in Settings. It is chosen when a new video is
> set up (a short wizard), and it is fixed for that video afterwards. Settings only
> shows which map the video uses. Suggest: "the location map is chosen when a video
> is set up".

### 2.4.1 Spatial annotation of touches

On "upper left corner of image XXX":

> In the current version the location map is in the upper right corner of the
> window. Please check against the screenshot we use.

On "can be adapted and changed by the user according to their needs" and "the
user is free to change it for a more neutral location map":

> More precisely: the user chooses one of three built-in maps (two infant body
> maps and one neutral map with 12 numbered zones) and can rename the zones and the
> four channels. Loading a user's own map is not supported yet. Suggest: "The user
> selects one of the built-in location maps, including a neutral one, and can
> rename its zones."

On "A clothing section is available for use [POTENTIALLY RENAME THAT, CHECK WITH
LUKAS]":

> In the software this is called "Special Zones". The user marks areas on the map
> and can add a note describing them; both are stored in the JSON output file.
> Suggest: "A Special Zones tool allows the user to mark areas of the map that must
> be treated as special cases, with a short note."

### 2.4.2 Temporal annotation

On "(green dot for onset and red dot for offset)":

> Correct. One detail worth stating: the offset is clicked on the first frame after
> the touch has ended, so a touch lasts from its onset frame up to, but not
> including, its offset frame.

On "(left and right hands, and left and right feet)":

> The software calls these left/right hand and left/right leg.

At the end of the section (optional addition):

> Possible addition: "Before closing or running the analysis, the software lists
> any onset without an offset and any offset without an onset, so they can be
> corrected."

### 2.4.3 Parameters and notes

On "that they can turn on and off":

> Each button has three states: not set, ON and OFF. There are up to three
> channel-independent buttons and three per channel, and the user names them when
> setting up a video.

On "by writing directly in the cell 'note'":

> The note is stored for the current frame when the user clicks "Save Note" next to
> the field.

### 2.4.4 Video navigation

On "(with a slightly reduced speed)":

> No longer true. Playback now runs at the video's own frame rate (tested up to
> 100 frames per second); only slow computers fall below it. Suggest deleting the
> bracket, or "at the video's original speed".

### 2.4.5 Display and performance settings

On "[ASK LUKAS for performance TABLE]":

> What should this table show? For example: playback speed reached on different
> computers, or time needed to prepare a video. Tell me what you have in mind and I
> will measure it. (Lukas)

### 2.4.6 Data output

On "Data is automatically exported when the user closes the software as a .csv
file and an .json file":

> Two corrections. (1) On closing, the software asks whether to save; the user can
> choose "Save and close" or "Don't save". Data is also exported when the user
> presses Save and before the analysis runs. (2) The output is three files: the
> .csv, the .json, and an image of the labeled location map. Suggest: "Data is
> exported each time the user saves, including when closing the software, as a .csv
> file and a .json file that together contain all the information needed for
> subsequent analysis, plus an image of the labeled location map."

### 2.4.7 Built-in analysis

On "generate heat maps of the locations labelled":

> The heat maps show, for each channel, where touches start and where they end
> (transitions between zones). The report also contains a plot of the touches on
> the location map, histograms of touch onsets and durations, and a table of touch
> counts per zone.

On "[would that be difficult to pull all files together and produce the same
stats?]":

> The analysis works on one video at a time. There is no summary across videos in
> the software; the summary CSV tables of each video can be combined in an external
> script. A built-in version would be new development.

### 4.1 Efficiency

On "automatically exported to a csv file that updates each time progress is
saved":

> Correct.

### 4.2 Applications

On "a location map that can be customized to fit different projects' needs":

> Same point as in 2.4.1: the user picks from built-in maps and renames zones, but
> cannot yet load a custom map. Suggest "a choice of location maps, including a
> neutral one, with zone names that can be adapted to a project's needs".

### Old ICDL abstract block

On "https://github.com/ctu-vras/touch-coder":

> The repository has moved: https://github.com/Humanoids-CTU/tiny-touch
