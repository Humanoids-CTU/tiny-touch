# TinyTouch

Frame-by-frame annotation of infant self-touch, for behavioral research.

![TinyTouch main window](assets/readme_images/showcase.png)

![version](https://img.shields.io/badge/version-9.0.0-blue) ![platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey) ![python](https://img.shields.io/badge/python-3.12-blue) ![license](https://img.shields.io/badge/license-GPLv3-green)

## What it does

TinyTouch is a desktop tool for coding self-contact in infant video: for each frame you
mark which limb (left/right hand, left/right leg) touches which body zone, together with
the onset and offset of the episode. Three global and three per-limb parameters let you
record additional observations, such as gaze. Contact locations are entered by clicking
a body diagram and resolved to zone names automatically. Each labeled video produces a
flat CSV dataset plus a JSON metadata
sidecar, ready for statistical analysis.

## Install

Download the ZIP for your system from the
[Releases page](https://github.com/Humanoids-CTU/tiny-touch/releases), extract it into a folder you can write to, and
run the executable inside — `TinyTouch-<tag>.exe` on Windows, `TinyTouch-<tag>` on Linux.
No installation step and no Python required.

Three builds are published per release: `windows-x64` (Windows 10/11, 64-bit), `linux-x64`
(current distributions) and `linux-legacy-x64` (older glibc; built on Debian Bullseye). On
Linux, launch from a terminal so you can see the log.

On Windows, open PowerShell in the extracted folder and run `./TinyTouch-v9.0.0.exe`.
On Linux, open a terminal in the extracted folder and run:

```bash
chmod +x TinyTouch-v9.0.0
./TinyTouch-v9.0.0
```

TinyTouch creates `data/` and `videos/` in the **current working directory** (the
folder your terminal is in). Always launch from the same folder to find your projects
again. The editable `config.json` lives beside the executable, or in the repository root
when running from source. Allow space for both a video copy and every extracted JPEG
frame; these can take substantially more space than the original video.

> **Start new projects with this release.** Previously coded projects are not
> imported or upgraded. Keep them as archives and use a fresh data folder.
> The CSV columns and cell encoding are preserved; see the compatibility notes below.

<details>
<summary><b>Run from source</b></summary>

Requires Python 3.12 with Tk support and [uv](https://docs.astral.sh/uv/). For a
distribution-provided Python on Debian/Ubuntu, install its matching Tk package
(for example, `python3.12-tk` where available).

```bash
git clone https://github.com/Humanoids-CTU/tiny-touch.git
cd tiny-touch
uv venv --python 3.12
uv pip install -r requirements.txt
uv run python src/main.py
```

Build a standalone executable with `uv run pyinstaller TinyTouch.spec`; the result lands in
`dist/`. Run the test suite with `uv run pytest` (GUI end-to-end tests are excluded by
default; add `-m gui` to include them).

</details>

## Quick start

1. **Load Video** — choose `Normal` or `Reliability`, choose a body template, then pick the video file. TinyTouch
   accepts `.mp4`, `.mov`, `.avi`, `.mkv`, `.flv`, and `.wmv` files. It copies the video into
   `videos/` and prepares frames in `data/<video>/frames/`. This can take several minutes;
   later sessions reuse the frames.
2. **Settings** — choose labels for the three global and three per-limb parameters before
   coding. The shipped labels are `P1`–`P3` and `LP1`–`LP3`. To code gaze, agree on a
   convention such as using global Parameter 1 and rename its label accordingly.
3. **Clothes** — mark the body zones covered by clothing. Saved with the project and
   recorded in the export metadata.
4. **Select a limb** with the radio buttons under the diagram.
5. **Mark the onset** — navigate to the first frame of the contact and **left-click** the
   body diagram where the touch occurs. A green dot appears.
6. **Mark the offset** — navigate to the first frame after the contact ends and
   **right-click** the last contact location on the diagram. A red dot appears and the
   episode is closed.
7. **Set parameters** with the buttons on the right (`unset → ON → OFF → unset`); type
   per-frame remarks in the note box and click **Save Note**.
8. **Save** — writes `data/<video>/export/<video>_export.csv` and
   `data/<video>/export/<video>_metadata.json` identifying the
   body template as `"template": "default"` or `"alternate"`. Keep these two files together. TinyTouch also saves on close.

The template picker applies to new projects. Existing projects restore their saved
template, and Reliability inherits the original project's template. **Settings** shows the active
template and allows a change only before annotation begins. The first annotation or
clothing mark permanently locks it, including if that mark is later deleted. The Clothes
window and analysis use the same template. See [project template provenance](docs/DATA_FORMAT.md#2-the-metadata-sidecar).

**Normal** is the main annotation pass. **Reliability** creates or resumes a separate
`<video>_reliability` project for a second pass, so the original annotations stay separate.
It copies the original project's frames when available; otherwise it extracts them from
the video. Compare the two exports in your own agreement analysis.

**Resume later:** launch from the same working folder, click **Load Video**, choose the
same mode, and select the same video (the copy in `videos/` is suitable). TinyTouch restores
saved annotations, the template, and your last frame position. `<video>` is the filename
without its extension, for example `infant_042` for `infant_042.mp4`. Give distinct videos
unique names before loading them, even if they come from different folders or have
different extensions; project lookup uses this name.

Unsupported working databases and exports without a working database are rejected
without conversion. Export CSVs alone cannot be reopened for annotation.

| Input | Action |
| --- | --- |
| `←` / `→` | Previous / next frame |
| `Shift`+`←` / `Shift`+`→`, `<<` / `>>` | Fast jump back / forward |
| Mouse wheel | Previous / next frame |
| `Space`, **Play** / **Stop** | Toggle playback |
| Left-click on diagram | Touch onset (green dot) |
| Right-click on diagram | Touch offset (red dot) |
| Middle-click on diagram, or `d` | Delete the nearest dot |
| Click a timeline | Jump to that frame |
| **Select Frame** | Enter a frame number to jump directly (numbering starts at 0) |
| **Save** | Write the working state and the export |

The full coding manual — modes, zones, parameters, and the mistakes worth avoiding — is in
[docs/ANNOTATION_GUIDE.md](docs/ANNOTATION_GUIDE.md).

## Output data

Each labeled video gets a project folder under the working directory:

```
data/<video>/
├── export/     <video>_export.csv + <video>_metadata.json
├── state/      <video>.db          working state, internal
├── frames/     frame0.jpg …        extracted video frames
└── plots/                          analysis dashboards
```

**Share data for analysis:** keep the two files under `export/` together.
The CSV has one row per frame with per-limb coordinates, onset/offset markers and zone
lists; the JSON records program version, frame rate, labeling mode, clothing zones,
parameter labels, total labeling time, and the body template (`template`). See the
[metadata specification](docs/DATA_FORMAT.md#2-the-metadata-sidecar).

**Back up or move an annotation project:** save and close TinyTouch, then keep the whole
`data/<video>/` folder, its video in `videos/`, and `config.json` for parameter labels and
settings. Keep both project folders if you have a Reliability pass. On another computer,
restore that layout, place `config.json` beside the executable, and launch from the folder
containing `data/` and `videos/` before loading the video again.

**CSV compatibility:** the columns, their order, and cell encoding are unchanged.
Pre-v8 CSVs had a metadata preamble that readers must handle separately; current exports
start with the header. The metadata JSON now also identifies the body template. This
does not make older working projects importable. The full specification and
[Python and R reading examples](docs/DATA_FORMAT.md#5-reading-the-export) explain how to
use the data in your own analysis.

## Analysis

The **Analysis** button saves first, computes per-limb statistics from the export, and
writes an interactive Plotly dashboard to `data/<video>/plots/`, opening it in your browser: touch
counts and durations, percentage of time in contact, touch rate, zone-transition heatmaps
per limb, a click-trajectory plot drawn over the limb diagrams, and duration/onset
histograms. Touches left without an offset are reported separately as open (unterminated)
and excluded from duration statistics.

Open `data/<video>/plots/master_<video>.html` to revisit the dashboard. The same folder
contains `analysis_table_frames.csv` and `analysis_table_seconds.csv` for further analysis.
Share the **whole `plots/` folder**, including `plotly.min.js`, so the charts can load.
Before considering a video finished, check the open-touch count and review any missing
offsets against the video.

## Citing

Please cite the software using [CITATION.cff](CITATION.cff), or GitHub's **Cite this repository**
button for APA and BibTeX entries. Cite the version you used, recorded in your
dataset's metadata sidecar (`Program Version`).

A paper describing TinyTouch is in preparation and will have its own citation
and author list, separate from the software citation.

An example of the kind of analysis this coding scheme supports:

> Khoury, J., Popescu, S. T., Gama, F., Marcel, V. and Hoffmann, M. (2022), Self-touch and
> other spontaneous behavior patterns in early infancy, in *IEEE International Conference
> on Development and Learning (ICDL)*, pp. 148-155.
> [PDF](https://drive.google.com/file/d/1iVgMr-8eJFPH8jU31ksDNmv4xWY_4s5q/view?usp=sharing)

## License

Copyright (c) 2026 Czech Technical University in Prague.

TinyTouch's source code, tests, build scripts, configuration files, documentation,
and original artwork (including body diagrams and zone masks) are licensed under
the GNU General Public License, version 3 only
(`GPL-3.0-only`). See [LICENSE](LICENSE) for the full terms.

You may use, modify, and distribute the software, including commercially, under those
terms. When distributing binaries, provide the corresponding source code as required
by the GPL. Recipients retain the right to modify and redistribute their copies.
The software comes without warranty, to the extent permitted by applicable law.

[REUSE.toml](REUSE.toml) records file-level copyright and license notices.
Third-party components retain their respective licenses. This project license does
not impose a license on users' input videos or annotation datasets.
Earlier releases offered under CC BY 4.0 remain available under those terms.

## Contact

Developed at the Vision for Robotics and Autonomous Systems (VRAS) group, Czech Technical
University in Prague.

Maintainer: Lukáš Navara — navarlu2@fel.cvut.cz

## Reporting a problem

TinyTouch writes one diagnostic log for every session. Open **Settings -> Open Logs
Folder**, then attach the newest `tinytouch_*.log` file to the bug report. The log includes
application details, errors, and the local annotation activity--including note text--needed
to understand what happened. It stays on your computer and is never transmitted
automatically.

If a log file cannot be created, TinyTouch continues running and reports diagnostics in
the terminal window instead.

## Documentation

[Annotation guide](docs/ANNOTATION_GUIDE.md) for annotators, [data format](docs/DATA_FORMAT.md)
for data consumers, [ARCHITECTURE.md](ARCHITECTURE.md) for developers, and a
[full index](docs/README.md) of everything else.

Reading the README from a release ZIP? The guides and images are available in the
[online repository documentation](https://github.com/Humanoids-CTU/tiny-touch/tree/v9.0.0/docs)
and the [online README](https://github.com/Humanoids-CTU/tiny-touch/blob/v9.0.0/README.md).
