# TinyTouch

A desktop application for labelling events in infant videos. Mark when touches
start and end on a body diagram, and use custom parameter buttons to label other
events and observations.

![TinyTouch main window](assets/readme_images/showcase.png)



## Install

Download TinyTouch from the
[Releases page](https://github.com/Humanoids-CTU/tiny-touch/releases).

**Windows 10/11 (64-bit):** download **windows-x64.zip**, extract it, and
double-click the **TinyTouch.exe** file.

**Linux (Ubuntu 24.04 or newer, Intel/AMD 64-bit):** download **linux-x64.zip**
and extract it. Open a terminal in the extracted folder and run
(use the version number you downloaded):

```bash
chmod +x TinyTouch-v9.0.0
./TinyTouch-v9.0.0
```

## Label a video

1. Click **Load Video**, choose **Normal**, select a body diagram and open your
   video. Preparing it may take a few minutes the first time.
2. Use **Clothes** to mark body areas covered by clothing.
3. Select the hand or leg you are labeling. (It’s easier to focus on one limb at a time.)
4. At the **first frame of a touch**, **left-click** its location on the body
   diagram. A green dot marks the start.
5. At the **first frame after the touch ends**, **right-click** its last location.
   A red dot marks the end.
6. Use the global or limb-specific parameter buttons to label additional
   observations as **ON** or **OFF**.
7. Add text notes to individual frames as needed.

| Control | Action |
| --- | --- |
| Left / right arrow, or mouse wheel | Previous / next frame |
| Shift + arrow, or **<<** / **>>** | Jump back / forward |
| Space, or **Play / Stop** | Play or pause |
| Click a timeline | Jump to that point |
| Left-click on the body diagram | Mark touch start (onset, green dot) |
| Right-click on the body diagram | Mark touch end (offset, red dot) |
| Middle-click a dot | Delete a mark |

The boxes beside the body diagram can represent custom actions, such as touching
or picking up an object; agree on what each box means before labeling.

## Settings

| Setting | What it does |
| --- | --- |
| Video downscale | Makes video images smaller. Try `2` (half size) if the app feels slow. |
| Diagram scale | Makes the body diagram larger or smaller to suit your screen. |
| Dot size | Changes the size of the marks on the diagram. |
| Fast-jump seconds | Sets how far **<< / >>** and **Shift + arrow** jump. |
| Realtime hold | Plays at the video's frame rate while you hold an arrow key. |
| Parameter Labels | Names your limb-specific and global observations. |

## Find your data and run analysis

Your work is stored in `data/`, with a separate folder for each video.
For example, labels for `infant_042.mp4` are saved in:

```text
data/infant_042/export/infant_042_metadata.json
data/infant_042/export/infant_042_export.csv
```
The **JSON** records supporting information such as frame rate, body diagram and
parameter names.

The **CSV** has one row for each video frame. Its columns contain your labels:
touch starts and ends (onsets and offsets), body areas, notes, and ON/OFF values
for global and limb-specific parameters. You can use these data in your own
analysis to study infant behaviour.

For a quick overview, click **Analysis** to open a report in your browser with
touch counts, durations and charts.
The report and summary CSV tables are saved in `data/infant_042/plots/`.
Open `master_infant_042.html` to view it again, or share the whole `plots/` folder.



## Reliability between two coders

For a second coder's pass, load the same video and choose **Reliability**.
TinyTouch adds `_reliability` to the project and output names, keeping the two
coders' labels separate. Compare the two exports in your own analysis to measure
agreement between coders. TinyTouch does not calculate reliability itself.

## License and contact

Copyright (c) 2026 Czech Technical University in Prague.
Licensed under [GNU GPL version 3 only](LICENSE).

Contact: **Lukáš Navara** — [lukas.navara@cvut.cz](mailto:lukas.navara@cvut.cz).
