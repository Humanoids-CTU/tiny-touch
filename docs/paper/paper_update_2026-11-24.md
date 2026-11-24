# Paper update against the code (2026-11-24)

Status of `TinyTouch article.docx` (the copy in the repository root, saved
2026-11-24) against the code after v9.4.0, including the unreleased 9.5.0 changes.

Four parts:

1. What is already in the Word file.
2. Open tasks.
3. Your older comments in the Word file: keep, update or delete.
4. Comments still to add.

## 1. Already in the Word file

- **Section 2.3** is the new text, both paragraphs, with the Linux bracket and the
  3D Pose sentence.
- **Fig. X** is the updated figure (`export/` shows "CSV · JSON · diagram PNG").
- **2.4 intro**, on "can be changed in the settings": your comment that the map is
  chosen in the setup wizard and then fixed.
- **2.4.1**, on "can be adapted and changed by the user": your comment that custom
  diagrams need a code change and are not implemented.
- **2.4.5**, on the performance table placeholder: your question "What is
  performance table?".

## 2. Open tasks

- [ ] **Pose sentence in Section 2.3.** It ends with "and does not yet have an
  export". That is no longer true: since 2026-11-24 every Pose save writes its own
  CSV and JSON export (see `docs/POSE_DATA_FORMAT.md`). Replace the end of the
  sentence with the wording in part 4 ("Section 2.3").
- [ ] **Try the Pose export in the app.** It is covered by automated tests only:
  save a Pose project, check the two files in `export/`, and try a save while the
  CSV is open in Excel.
- [ ] **Performance table (2.4.5).** Waiting for the co-authors to say what the
  table should show.
- [ ] **Commit and build.** The `resource_utils` move is not committed, and the
  frozen build was not tested after it. Build the executable once and open a
  project before the 9.5.0 release.
- [ ] **Word file in the repository root.** It is untracked. Decide whether it
  belongs in git (for example under `docs/paper/`) or should stay out.

## 3. Your older comments in the Word file

| Where | Your comment (date) | What to do |
| --- | --- | --- |
| 2.4.1 heading | "I aded the general purpose diagram. Only 8 boxes 4 channels (instead of limbs)…" (3 Nov) | **Update.** The neutral map now has 12 selectable zones: 8 numbered boxes plus the 4 channel boxes. Replacement text in part 4. |
| 2.4.1, "This location map" | "maybe I would mention that the diagram is chosen at the start and then its locked" (3 Nov) | **Delete.** Your two new comments from 24 Nov say the same, more precisely. |
| 2.4.1, "A clothing section" | "I renamed it to special zones, is it ok?" (3 Nov) | **Keep**, or replace with the fuller text in part 4, which also offers a sentence. |
| 2.4.4, "(with a slightly reduced speed)" | "did some tricks with it in the version 9.1.0 and it runs smooth on my pc, can you maybe try…" (3 Nov) | **Replace** with the text in part 4. Since 9.4.0 playback runs at the video's own frame rate. |

## 4. Comments still to add

Each block is one comment. Paste it on the quoted words. Blocks marked "reply"
answer a co-author's existing comment.

### 2. Software description (heading)

Reply to Jason's "explicitly refer to the GITHUB":

> The repository is https://github.com/Humanoids-CTU/tiny-touch (the old
> ctu-vras/touch-coder address in the ICDL text is outdated). Executables are on
> its Releases page.

### 2.3 Software architecture (your text)

Replace the end of the last sentence, "stores its labels in a separate database,
and does not yet have an export", with:

> stores its labels in a separate database, and exports them as its own CSV and
> JSON files.

### 2.4.1 Spatial annotation of touches

Replacement for your comment on the heading (general purpose diagram):

> There are three built-in location maps: two infant body maps and one neutral map
> with 12 numbered zones (8 boxes plus one box for each of the 4 channels). Zones
> and channels can be renamed for a study.

On "upper left corner of image XXX":

> In the current version the location map is in the upper right corner of the
> window. Please check against the screenshot we use.

On "A clothing section is available for use [POTENTIALLY RENAME THAT, CHECK WITH
LUKAS]" (optional, replaces your short comment):

> In the software this is called "Special Zones". The user marks areas on the map
> and can add a note describing them; both are stored in the JSON output file.
> Suggest: "A Special Zones tool allows the user to mark areas of the map that must
> be treated as special cases, with a short note."

### 2.4.2 Temporal annotation

On "(green dot for onset and red dot for offset)":

> One detail worth stating: the offset is clicked on the first frame after the
> touch has ended, so a touch lasts from its onset frame up to, but not including,
> its offset frame.

On "(left and right hands, and left and right feet)":

> The software calls these left/right hand and left/right leg.

At the end of the section (optional):

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

On "(with a slightly reduced speed)" (replaces your comment from 3 Nov):

> No longer true. Playback now runs at the video's own frame rate (tested up to
> 100 frames per second); only slow computers fall below it. Suggest deleting the
> bracket, or "at the video's original speed".

Reply to Olivia's "on external media player / file type" (optional):

> The software reads common video files (mp4, mov, avi and other formats ffmpeg can
> decode) and needs no player or codec installed on the computer.

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

Reply to Jason's "does it work with the other templates? Same than for clothes
btw":

> Yes. The analysis and Special Zones work with all three location maps.

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

### 4.2 Applications

On "a location map that can be customized to fit different projects' needs":

> Same point as in 2.4.1: the user picks from built-in maps and renames zones, but
> cannot load a custom map. Suggest "a choice of location maps, including a neutral
> one, with zone names that can be adapted to a project's needs".

## Comments by others that only you can answer

- Jason, on the "2. Software description" heading: "check if Lukas made a video".
- Olivia, on "Datavyu" in 2.2: "what version?" This is probably about Datavyu, but
  the TinyTouch version used for the reliability coding may be wanted too.
