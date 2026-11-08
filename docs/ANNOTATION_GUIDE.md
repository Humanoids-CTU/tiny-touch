# TinyTouch Annotation Guide

A coding manual for annotators. It assumes you have TinyTouch installed (see the
[README](../README.md)) and have never used it before. If you need the exact structure of
the files it produces, read [DATA_FORMAT.md](DATA_FORMAT.md) instead.

**Contents**

1. [What you are coding](#1-what-you-are-coding)
2. [Labeling modes: Normal and Reliability](#2-labeling-modes-normal-and-reliability)
3. [Loading a video](#3-loading-a-video)
4. [The window](#4-the-window)
5. [Marking special zones](#5-marking-special-zones)
6. [Coding a touch](#6-coding-a-touch)
7. [Zones](#7-zones)
8. [Gaze and parameters](#8-gaze-and-parameters)
9. [Notes](#9-notes)
10. [Saving](#10-saving)
11. [Analysis](#11-analysis)
12. [Practical tips and common mistakes](#12-practical-tips-and-common-mistakes)

---

## 1. What you are coding

For each of the infant's four limbs — **RH** (right hand), **LH** (left hand), **RL**
(right leg), **LL** (left leg) — you mark every episode in which that limb is in contact
with the infant's own body, and where on the body the contact happens.

An episode is two events:

- an **onset** on the first frame where the contact is established, and
- an **offset** on the first frame where the contact has ended.

Both events also carry the contact **location**, which you indicate by clicking the
matching place on the body diagram. TinyTouch converts the click into a zone name
automatically.

The duration of a touch is `offset frame − onset frame`: the touch is counted as active on
the onset frame and *not* on the offset frame. The shortest touch you can code is one
frame long.

---

## 2. Labeling modes: Normal and Reliability

Choose the mode while preparing a new video. Opening an existing project from
the video library restores its saved mode and coding setup.

**Normal** — ordinary coding. The project folder is named after the video.

**Reliability** — a second, independent pass over a video that has already been coded, used
to compute inter-rater agreement. Choose it when you are re-coding someone else's video (or
your own, blind) so the two datasets can be compared instead of overwriting each other:

- The project folder gets a `_reliability` suffix (`data/infant_042_reliability/`), so the
  original dataset is untouched.
- When the original project's frames are available, they are copied so the two passes
  see byte-identical images and frame indices line up exactly. Otherwise frames are
  extracted from the selected video.
- `Labeling Mode` in the export metadata records which pass produced the file.

The mode chip in the bottom-left corner of the window shows which mode you are in; it turns
amber in Reliability mode. Your choice is remembered as the default for next time.

---

## 3. Loading a video

1. Click **Load Video** to browse existing projects by thumbnail, title, and diagram.
   Open a prepared project to resume at its saved position.
2. For a new project, choose **Load new video** and select a file (`.mp4`, `.mov`,
   `.avi`, `.mkv`, `.flv`, `.wmv`).
   If a project with that video name already exists in the selected mode, choose
   **Resume existing** or **Create new copy**. A copy starts a fresh Normal
   project named `<video>_copy` (then `_copy2`, `_copy3`, etc.), with its own
   setup and annotations. It shares the source video without duplicating it.
3. Choose the mode and a diagram: **Default**, **Alternate**, or **General**.
   Alternatively, load a shared coding configuration from `config/` to prefill
   all the settings. This folder sits beside the application's `config.json`.
4. Review the zone names, four channel names, three global parameter labels, and
   three channel-specific parameter labels. Keep defaults or edit them; **Back**
   lets you revisit earlier steps. The geometry of the zones does not change.
5. Review the complete setup. Save a named configuration JSON if another video or
   coder should reuse it, then prepare the video.
6. TinyTouch copies the video into `videos/` and extracts frames into
   `data/<video>/frames/`. Reliability reuses the original frames when available.
   Successful preparation locks the coding setup and opens the annotation view.

Cancelling the library or setup leaves the current project intact. Failed or
interrupted preparation must be retried before coding. An existing prepared
project restores its own settings; it does not reread the shared configuration.
Reliability inherits a complete copy of the original setup. Conflicting existing
passes cannot be linked silently.

The diagram and zone/channel/parameter names are fixed after preparation.
Deleting annotations does not unlock them. Use the same configuration to prepare
a new project when a different coding definition is needed. Display preferences,
annotation values, notes, and Special Zones markings remain editable.

Existing supported databases without a complete coding setup need a one-time
review if their exported metadata cannot establish the parameter meanings. This
does not add support for retired pre-SQLite working-state formats.

Keep the exported CSV and metadata JSON together. The metadata records the exact
coding setup and export format version; see [the export specification](DATA_FORMAT.md).

Launch from the same working directory each time and use the same mode and video to
resume. Project names come from video filenames without their extensions; use unique
names for distinct videos. See the README for [backup and transfer instructions](../README.md#find-your-data-and-run-analysis).

Do not close the terminal window while using the application. If something goes wrong,
use **Settings -> Open Logs Folder** to find the session log for your bug report.

---

## 4. The window

**Left** — the video frame, and below it two timelines.

- **Timeline 1** (the taller one) shows the current block of 100 frames for the
  **currently selected limb**, one cell per frame: green = a frame carrying an onset, red =
  a frame carrying an offset, pale green = frames inside an open touch, grey = nothing
  coded. Cells past the end of the video are hatched. Thin vertical ticks mark frames where
  a global or limb parameter is set. A playhead marks the current frame.
- **Timeline 2** (the slimmer one, above it) spans the whole video and acts as a scrub bar.

Clicking either timeline jumps to that frame.

**Right** — the body diagram, the limb selector, the parameter buttons and the note box.

**Top bar** — Load Video, Settings, Special Zones, Analysis, Save on the left; the navigation
buttons, Play/Stop and the frame/time counters on the right.

**Bottom strip** — the mode chip, the buffer indicator, the minimal-touch-length readout,
the jump size, and the video name. A red **Buffer: Loading** indicator means the decoded
frames around your position are still being read; wait a second and it turns green.

### Keyboard and mouse

| Input | Action |
| --- | --- |
| `←` / `→` | Play backward / forward while held when Hold arrows is enabled; otherwise step on keyboard repeat |
| `Shift`+`←` / `Shift`+`→` | Jump back / forward by the fast-jump distance |
| Mouse wheel | Previous / next frame |
| `Space` | Toggle Play / Stop |
| **Left-click** on the diagram | Mark a touch **onset** at that point (green dot) |
| **Right-click** on the diagram | Mark a touch **offset** at that point (red dot) |
| **Middle-click** on the diagram | Delete the dot nearest the pointer on the current frame |
| `d` | Same as middle-click, using the last pointer position over the diagram |
| Click on Timeline 1 or Timeline 2 | Jump to that frame |
| `<<` / `<` / `>` / `>>` buttons | Fast-jump back, back one, forward one, fast-jump forward |
| **Play** / **Stop** buttons | Start / stop playback |
| **Save** button | Write the state database and the export |

The fast-jump distance is set in Settings as **Fast-jump seconds** and is converted to a
frame count using the video's frame rate; the current value is shown as `Jump: N` in the
bottom strip.

Navigation keys are ignored while the cursor is inside the note box, so typing a note that
contains a `d` or an arrow key does not move you off the frame.

With **Hold arrows to play** enabled, key-down steps one frame. A tap released within
150 ms stays on that frame; holding longer starts playback. Release or focus loss
stops playback. **< / >** always step one frame. Playback targets the video's frame
rate but slows down if rendering cannot keep up, preserving frames.

---

## 5. Marking special zones

Click **Special Zones** to open the dialog. It shows the whole-body diagram and a
**Note** field. Use it to mark any project-wide set of body zones, for example zones
covered by clothing.

- Moving the pointer lights the zone under it and names it, exactly as on the coding
  diagram, so you can see which zone a dot will mark before you click.
- **Left-click** places a green dot on a zone.
- **Middle-click** on a dot removes it.
- Type in **Note** what the marked zones mean (e.g. "covered by diaper and socks").
- Closing the window stores the current dots and the note. The window stays in front of
  the main window and blocks it until you close it, so it cannot get lost behind the app.

The zones under the dots are resolved with the same masks used for touch coding. The
resulting list is written to the export metadata as `Special Zones`, and the note as
`Special Zones Note`. It is best done before you start coding, so downstream analysis
knows, for example, which contacts were skin-to-skin and which were through clothing.
You can reopen the window at any time, also after coding has started, to fix a mark
or add a zone you noticed later: the existing dots and note come back, and closing
the window saves the new state.

---

## 6. Coding a touch

1. **Select the limb** with the radio buttons under the diagram (Right Hand, Left Hand,
   Right Leg, Left Leg). The diagram redraws with that limb's zone map, and the timeline
   switches to that limb. Annotations for the other three limbs are untouched — you code
   one limb at a time, but all four coexist in the same project.
2. **Find the first frame of the contact** with the arrow keys or the wheel.
3. **Left-click on the body diagram at the place being touched.** A green dot appears and
   the frame is marked as an onset for the selected limb.
4. **Step forward to the first frame where the contact has ended.**
5. **Right-click at the place the limb was touching last.** A red dot appears and the frame
   is marked as an offset. The touch is now closed.

While a touch is open, the onset's dot is redrawn as a hollow green ring on later frames as
a reminder of where the touch started and that it is not yet closed.

**Several clicks on one frame.** You may click more than once on the same frame for the
same limb — for example when a hand spans two zones, or when you want to record several
contact points. All clicks on that frame are stored, each with its own zone. The
onset/offset state, however, belongs to the whole frame-and-limb: the most recent click
sets it. Do not left-click and then right-click on the same frame for the same limb
expecting two events; you will end up with one offset frame carrying two dots.

**The limb moves during a touch.** If the contact drifts to a different zone without
breaking, left-click on an intermediate frame to record the new location. That extra
onset becomes a mid-touch waypoint in the trajectory plot and increases the episode's
onset count; it does not start a separate episode. The "touch length distribution"
histogram counts these onsets. Right-click only when the contact ends, because it closes
the touch.

**Before you click.** As you move the pointer over the diagram, the zone under it lights
up in amber and a small tag next to the pointer shows its name, so you can see which zone
a click will record before you commit. A renamed zone shows as `Name (ID)`. The boundary
lines and the off-body area are named but not lit. After a click the zone flashes briefly
in the dot's colour. Settings > "Highlight the zone under the pointer" turns this off.

**Deleting.** Middle-click near a dot, or hover over it and press `d`, to remove it. The
dot must be within roughly 20 pixels of the pointer. Removing the last dot on a frame also
clears that frame's onset/offset state for the limb, so the frame goes back to being blank.

---

## 7. Zones

You never type a zone name. TinyTouch determines it from where you clicked, using a set of
per-zone mask images that exactly overlay the body diagram.

- The **default zone set** has 38 zones: `A`–`Z`, `WB`, `XB`, `YB`, `ZB`, six boxes, `LINE`
  and `OUTSIDE`.
- The **alternate zone set** (selected when opening a new project) has 32: `A`–`T`,
  `QB`, `RB`, `SB`, `TB`, six boxes, `LINE` and `OUTSIDE`. It uses a different body diagram,
  so the same letter means different anatomy. Agree on one template before a study starts
  and record which one you used.

Both diagrams are shipped as figures you can print for reference:

| Default template | Alternate template |
| --- | --- |
| ![Default left-hand zone map](../assets/readme_images/LH.png) | ![Alternate left-hand zone map](../assets/readme_images/LH_new_template.png) |

Special zones:

- **`BOX1`–`BOX6`** — the six boxes drawn beside the body. They are catch-alls with no
  built-in meaning: use them for contacts with something that is not the infant's body
  (the ground, a toy, the caregiver's hand). Decide what each box means in your coding
  scheme and write it down, because the export only records `BOX3`, not what you meant by
  it.
- **`OUTSIDE`** — you clicked in the area masked as off-body.
- **`LINE`** — you clicked exactly on a boundary line between two zones, and *no zone at all
  covers that pixel*, so TinyTouch genuinely cannot tell which one you meant. Nudge the click
  a pixel or two into the intended zone.
- **`NN`** — **no zone matched at all.** Almost always a misclick outside the diagram's
  masked area. `NN` clicks are kept in the data and show up in the analysis, so treat `NN`
  in a finished dataset as a defect to be corrected, not as a category. Every `NN` click is
  also announced with a `WARN` line in the console, naming the frame and limb, so you can
  fix it while you are still on the video.

The zone masks overlap slightly, so a click can match several. The winner is decided by
precedence, not by name: **a real body zone beats a box, a box beats `OUTSIDE`, and
`OUTSIDE` beats `LINE`.** That is why `LINE` and `NN` really mean "nothing claimed this
pixel" and are worth chasing down — they are never just an artifact of which zone happens
to sort first.

---

### Custom zone names

Set zone names in the new-video setup wizard. This works for **Default**,
**Alternate**, and **General**. Enter names beside the zone IDs: for example,
General's `1` could become `Light on`. General's four footer boxes are zones too,
`Channel1` through `Channel4`, so a touch *of* a channel can be recorded; name them
here like any other zone. A name given to a channel zone is carried over as that
channel's name in the next step, unless you type a different channel name there. Names can contain up to 40 characters on one
line. Leave a name blank to use the original ID again. `LINE` and `NN` remain fixed.

Enable **Show zone names on diagrams** in Settings to show names on the annotation
diagram and in **Special Zones**. This visibility preference remains editable;
the names themselves are frozen when preparation succeeds.

Names are saved with each project. A new Reliability pass inherits the
original pass's coding setup. CSV zone IDs and mask
files stay unchanged; the export metadata's **Coding Setup.zone_labels** maps IDs to custom names.

## 8. Gaze and parameters

Below the diagram there are two groups of three buttons.

**Channel parameters** — apply to the selected channel on the current frame.

**Parameters (global)** — apply to the whole frame, regardless of the selected channel.

Every button is a three-state toggle. Clicking it cycles:

```
unset  →  ON  →  OFF  →  unset  →  ...
```

The button is colored to show the state, and the state of the current frame is reflected
whenever you move between frames.

**Gaze** can be recorded with **global Parameter 1** by study convention; there is no
separate gaze control. The shipped labels are `P1`–`P3` and `CP1`–`CP3`. Rename global
Parameter 1 to a meaningful label such as `Looking1` if you use it for gaze. One convention
is `ON` when the infant is looking at the contact, `OFF` when demonstrably not looking,
and unset when you cannot tell. Agree on both the meanings and which frames to label
before coding begins; parameter values belong to individual frames.

**Configure button labels before preparation.** The setup wizard edits the three
global and three channel-specific labels. The same three channel-specific meanings
apply to all four channels. Save a shared coding configuration to reuse these
definitions. Each prepared video retains its own immutable copy, which is written
into export metadata. Global columns are `Parameter_1..3`; channel-specific columns
are `Channel1_Parameter_1..3` through `Channel4_Parameter_1..3`.

Settings also holds the display options: video downscale (higher values render smaller frames),
dot size, the fast-jump distance, and whether holding an arrow key starts playback
after a 150 ms tap delay at the video's target frame rate. Changes apply on **Apply** or **Apply & Close**.
The diagram size is not a Settings field: drag the grip in the diagram's bottom-left corner
(the pointer turns into a resize arrow there). The proportions stay fixed, recorded coordinates
are unaffected, and the chosen size is remembered for the next launch.

Choose **Appearance: Light / Dark** to change the interface colors. Your choice is
remembered after closing the app. The body diagrams keep their white background.

---

## 9. Notes

The text box at the bottom right stores one free-text note per frame.

- Type the text and click **Save Note**. The note is attached to the frame you are on and
  reappears when you return to it.
- Saving an empty box clears the note.
- **Save Note** also leaves the note box so arrow keys immediately move between frames.
- Purple diamond markers show saved notes on both timelines, regardless of the selected
  limb. Click a diamond to jump to its exact frame and read the note in the box.

To jump to a specific frame, click **Select Frame** between the backward and forward
buttons (`<<  <  Select Frame  >  >>`). Playback pauses and a dialog opens with the
current frame number selected. Type a frame number and press **Enter** or click
**OK** to jump. **Escape**, **Cancel**, or closing the dialog leaves the frame unchanged.
The dialog shows the allowed range; numbering starts at **0**. Invalid numbers keep
the dialog open so you can correct them. The frame counter remains read-only.

Notes end up in the `Note` column of the export, one per frame.

---

## 10. Saving

Click **Save** regularly. Saving:

1. writes your annotations to the project's working database
   (`data/<video>/state/<video>.db`), and
2. rewrites the published dataset,
   `data/<video>/export/<video>_export.csv` plus `<video>_metadata.json` and `<video>_diagram.png`.

TinyTouch also saves automatically before loading another video and when you close the
window. A progress dialog appears during the export; on a long video this takes a few
seconds.

Practical rules:

- **Do not open the CSV in Excel while labeling.** A file lock can make a save fail.
- **Load Video** can open another video in the same session; the current project is saved
  before switching.
- The application keeps a labeling-time counter per video and reports it in the metadata as
  `Total Labeling Time (hours)`.

### Export diagram reference

Saving also writes `<video>_diagram.png` into the export folder. Share it with the
CSV and metadata JSON. The image shows CSV zone IDs on the diagram and a burned-in
legend of the saved zone names, so a reader can locate each exported zone.
The metadata stores labels once under `Coding Setup`; older exports are archived
on their first save with this format. Existing files update on the next Save.

---

## 11. Analysis

**Analysis** saves first, then computes per-limb statistics from the export and writes an
interactive dashboard to `data/<video>/plots/`, opening the index page
(`master_<video>.html`) in your browser. It contains:

- a **touch-trajectory plot**, one panel per limb, showing every click drawn over the limb
  diagram — green for the onset, red for the offset, black for mid-touch waypoints;
- a **summary table**: touch counts, total and mean duration, standard deviation, percentage
  of the video spent touching, touch rate per minute;
- a **zone-count table**: readable zone names, original IDs, and counts of closed touches;
- **transition heatmaps**, one per limb, counting start zone → end zone;
- two **histograms**: number of onsets per touch, and touch duration.

Reports use names from the exported metadata. Renamed zones appear as **Name (ID)**
in heatmaps and trajectory hovers, keeping zones distinct even if they share a name.
General uses channel names in titles, legends, and tables. Its diagram footer highlights
the corresponding channel in both the app and each report trajectory panel. Clicking a
footer box records a touch of that channel (zone `Channel1`–`Channel4`) for the channel
selected in the radio buttons; it does not switch channels.
Older exports without custom names use the original IDs and template defaults.
The two analysis CSV files retain their original headers and channel IDs.

Two things to read carefully:

- Heatmap totals can exceed the number of touches. A touch whose onset resolved to two
  zones and whose offset resolved to two zones contributes four counts, by design.
- Any **open (unterminated) touch** is reported separately in the table and in a warning
  banner at the top of the page, and is excluded from every duration statistic. The app
  shows such touches in a dialog *before* it runs the analysis, so you can fix them first —
  see below.

The `Minimal Touch Length` readout in the app is a visual aid only. It never filters
anything, in the app or in the analysis.

---

## 12. Practical tips and common mistakes

**An `ON` without a matching `OFF` is the most common error.** It is easy to mark an onset,
get distracted, and never close the touch — or to delete an offset dot and forget to
replace it. Such a touch is **unterminated**: it has no duration, and it is excluded from
totals, means, standard deviations, percentages, transition counts and both histograms. It
is not silently dropped — the analysis reports it separately with its start frame, in the
summary table, in the banner on the dashboard page and in the log — but it contributes
nothing to your statistics.

When you press **Analysis** with such a touch in the data, the app first shows an
**Open touches** dialog listing each open onset (channel and frame). **Go to onset** jumps
there without running the analysis so you can place the missing offset (right-click).
**Skip and analyze** runs the analysis with the touch left open: it is reported as "open
(unterminated)" and excluded from the durations. If a touch genuinely lasts until the end of
the recording, place its offset on the last frame yourself.

**Run Analysis before you consider a video finished and check that the "Open
(Unterminated) Touches" column is zero for all four limbs.**

**A stray `OFF` is silently ignored.** An offset with no preceding onset belongs to no
touch. It appears nowhere in the statistics and produces no warning, so it is harder to
notice than a missing offset. Work forward through the video in order rather than jumping
around, and you will rarely create one.

**Check the selected limb before you click.** Nothing stops you from coding a right-hand
touch onto the left leg. The limb selector and the timeline are the only cues; get into the
habit of coding one limb through the whole video before switching.

**Do not left-click twice where you meant onset then offset.** The second left-click adds a
point and keeps the frame marked as an onset. Onset is left, offset is right, always.

**Watch for `NN` and `LINE`.** Both mean your click did not land cleanly inside a zone.
Delete the dot and click again a little further from the boundary.

**Set the parameter labels before the study, not during it.** They are recorded once, in
the metadata of whatever save happened last.

**Coordinates are independent of the diagram scale**, so changing the diagram size mid-study
does not shift previously stored clicks. Dot size and video downscale are equally
display-only.

**If the frame looks stale, check the buffer indicator.** A red `Buffer: Loading` means the
frames around your position are still being read from disk; the display catches up on its
own.

**If something goes wrong**, do not close the terminal window — it holds the log. Save a
screenshot of it along with a description of what you were doing.

---

## See also

- [../README.md](../README.md) — installation and a short quick start.
- [DATA_FORMAT.md](DATA_FORMAT.md) — the exact structure and semantics of the exported
  files.
