# TinyTouch architecture

**TinyTouch** is a desktop annotation tool for behavioral researchers studying how infants learn to understand their own body through self-touch. It provides **Touch Labeling**: frame-by-frame annotation of which limb (LH / RH / LL / RL) touches which body zone, including onset/offset marking, gaze tracking, and customizable global / per-limb parameters.

This is the developer-facing document. See also:

| Document | Audience |
| --- | --- |
| [README.md](README.md) | Users — install and quick start |
| [docs/ANNOTATION_GUIDE.md](docs/ANNOTATION_GUIDE.md) | Annotators — the coding manual |
| [docs/DATA_FORMAT.md](docs/DATA_FORMAT.md) | Data consumers — the frozen export specification |

## Purpose

Researchers record videos of infants and use TinyTouch to produce structured CSV datasets describing every self-contact event. These datasets feed downstream analyses of how babies develop body awareness.

## Tech Stack

- **Python 3.12** with **Tkinter** (desktop GUI; built-in, no separate install)
- **OpenCV** (`opencv-contrib-python`) -- video probing, fallback frame extraction, mask reads
- **imageio-ffmpeg** -- bundles a static `ffmpeg` binary used as the primary frame extractor (much faster than OpenCV)
- **Pillow** -- image / diagram rendering on Tk canvases
- **PySDL2 + SDL2** -- optional-at-runtime GPU video drawing in a Tk-owned child window, with the existing Pillow/Tk display as fallback
- **Pandas** -- CSV / JSON I/O and tabular handling
- **Plotly** -- interactive analysis dashboards (rendered to HTML and opened in the default browser)
- **keyboard** -- global hotkey support
- **PyInstaller** -- packaging into standalone Windows / Linux executables (see [TinyTouch.spec](TinyTouch.spec))

The full pinned list lives in [requirements.txt](requirements.txt).

## Project Structure

```
tiny-touch/
├── src/                          # Application source
│   ├── main.py                   # Entry point: builds and runs LabelingApp.mainloop()
│   ├── labeling_app.py           # Main controller (~2.3k LOC): video, annotation, persistence,
│   │                             # frame buffer + playback wiring, save/export orchestration
│   ├── app_info.py               # Application version metadata
│   ├── video_model.py            # Video entity (LimbView wrappers over frames)
│   ├── perf_utils.py             # Optional perf timer + periodic summary logging
│   ├── log_setup.py              # Session handlers, retention and exception hooks
│   ├── generate_zone_masks.py    # Offline tool: build per-zone PNG masks from a diagram
│   ├── domain/                   # PURE rules: no I/O, no Tk, no plotting, no config
│   │   ├── model.py              # FrameRecord / FrameBundle shapes, LIMBS, LimbView
│   │   ├── project.py            # ProjectPaths -- the only place on-disk layout is built
│   │   ├── touch.py              # Touch-annotation rules (zone hit test, open-onset scan)
│   │   ├── touch_stats.py        # Episode reconstruction + touch statistics (Analysis core)
│   │   └── playback.py           # Pure play-step rule (boundary stop + clamped advance)
│   ├── adapters/                 # I/O edges: files, cv2/ffmpeg, plotly, config.json
│   │   ├── sqlite_repo.py        # Working-state DB per video (SOURCE OF TRUTH)
│   │   ├── export_writer.py      # Versioned channel CSV + metadata snapshot (write)
│   │   ├── export_reader.py      # Export CSV read, incl. legacy 6-line preamble
│   │   ├── plotting.py           # Every plotly figure / CSV table (ReportFigure factory)
│   │   ├── report_page.py        # master_<name>.html layout/CSS (inlines the figures)
│   │   ├── config.py             # config.json read / write, AppConfig snapshot
│   │   ├── zone_masks.py         # Zone-mask PNG loading + zone-name listing
│   │   ├── frame_extractor.py    # Frame extraction (ffmpeg → OpenCV fallback) + integrity
│   │   ├── frame_buffer.py       # Sliding JPEG buffer: buffering thread + decode pool
│   │   ├── video_probe.py        # cv2 frame-count / fps probe
│   │   ├── timer_resolution.py   # 1 ms Windows timer resolution while frames are paced
│   │   └── atomic_io.py          # Write-temp-then-replace helper
│   ├── service_layer/            # Use cases: orchestration only
│   │   ├── save_service.py       # The save Unit of Work
│   │   ├── project_service.py    # Video load / project preparation, labeling timer
│   │   ├── annotation_service.py # Click / parameter mutations on the frames dict
│   │   └── analysis_service.py   # Analysis: read -> validate -> compute -> write
│   ├── gui/                      # Tkinter only
│   │   ├── ui_components.py      # Layout, widgets, key/mouse bindings
│   │   ├── diagram_highlight.py  # Hover highlight, zone tag and click flash on the diagram
│   │   ├── diagram_resize.py     # Corner grip: drag to rescale the diagram (aspect kept)
│   │   ├── theme.py              # Colors / fonts / widget styling
│   │   ├── native_title_bar.py   # Windows title-bar colors; no-op on Linux
│   │   ├── special_zones_app.py  # Special-zone selector + note dialog (Toplevel)
│   │   └── resource_utils.py     # PyInstaller-aware asset path resolution
│   └── resources/                # RUNTIME assets -- everything here ships in the exe
│       └── icons/                # Body diagrams, limb images, zone masks
│           ├── diagram0.png      # Default touch diagram (rendered on canvas)
│           ├── zones3/           # Touch-mode zone masks (one PNG per zone)
│           └── zones3_new_template/  # Alternate zone set (project: alternate)
├── data/                         # Output (gitignored) -- one folder per video
├── videos/                       # Local source videos (gitignored; not distributed)
├── tests/                        # pytest suite: unit/ + integration/ + e2e/ (see "Testing")
├── assets/, docs/, .github/      # REPO-ONLY static assets, docs, CI workflow
├── config.json                   # User-configurable settings (see "Configuration")
├── pytest.ini                    # testpaths, the `gui` marker, default deselection
├── requirements.txt              # Pinned Python dependencies
└── TinyTouch.spec                # PyInstaller build spec
```

## Architecture

The codebase follows the layering of *Architecture Patterns with Python*: four layers with a
one-way dependency rule.

| Layer | May import | Holds | Must never |
| --- | --- | --- | --- |
| `domain/` | stdlib, pandas (as a data container only) | Data shapes and pure rules: `FrameRecord` / `FrameBundle`, `ProjectPaths`, zone hit test, episode reconstruction and statistics | Touch the filesystem, Tk, plotly, cv2, adapters or services |
| `adapters/` | `domain`, third-party I/O libraries | The I/O edges: SQLite, CSV/JSON writers and readers, cv2/ffmpeg, plotly figures, config file, atomic writes | Contain a rule that could live in `domain` |
| `service_layer/` | `domain`, `adapters` | Use cases: the save Unit of Work, project open, annotation mutations, analysis run | Import Tk or build a figure |
| `gui/` + `labeling_app.py` | everything below | Tkinter only: widgets, bindings, canvases, dialogs, threads | Reimplement a rule or a file format |

The domain rule is enforced mechanically: `tests/unit/test_touch_stats.py`
(`test_domain_layer_imports_nothing_from_the_outer_layers`) AST-parses every file under
`src/domain/` and fails on a banned import. Two conventions ride on top of it: the services
never read `config.json` (the GUI passes its `AppConfig` snapshot down as arguments), and
`adapters.plotting` never computes a statistic — it receives finished domain objects, so
the numbers are reproducible without plotly.

TinyTouch is a single-process Tkinter app organized around one controller (`LabelingApp`, a `tk.Tk` subclass) that owns:

- the `Video` model (raw video info + per-frame data dict),
- the UI built by `ui_components.build_ui(app)` (frames, canvases, buttons, key bindings),
- a `FrameBuffer` (`adapters.frame_buffer`) owning the read-ahead thread and decode pool,
- the working-state repository (`adapters.sqlite_repo`) plus the save / project
  services that orchestrate it.

### High-level data flow

```
User input (clicks / keys)
   └─► LabelingApp callbacks
         ├─► mutates Video.frames[frame] (the in-memory FrameBundle)
         ├─► marks bundle "Changed" = True
         └─► repaints diagram canvas + timelines
                                              ┌─► persist_state  (dirty frames -> state DB,
                                              │                   ONE transaction, Tk thread)
On Save / Close ─► LabelingApp.save_data ─────┼─► export_from_unified  (version 2 channel schema)
                                              ├─► write_export_metadata (JSON sidecar)
```

The state write happens on the Tk thread; the three export writes run on a worker
thread against a `deepcopy` snapshot taken beforehand. The SQLite connection
never leaves the Tk thread (`SqliteRepository` raises if it does).

### In-memory data model

Touch-mode state for a frame is a **`FrameBundle`** (see [src/domain/model.py](src/domain/model.py)):

```python
FrameBundle = {
    "LH": FrameRecord,  # left hand
    "RH": FrameRecord,  # right hand
    "LL": FrameRecord,  # left leg
    "RL": FrameRecord,  # right leg
    "Note": str | None,
    "Params": {"Par1": "ON"|"OFF"|None, "Par2": ..., "Par3": ...},  # global per-frame
    "Changed": bool,   # dirty flag, cleared after save
}
```

Each `FrameRecord` holds aligned `X` / `Y` click lists, `Onset` (`"ON"`/`"OFF"`/`""`), `Bodypart`, `Zones` (one bucket per click), `Touch`, and a `LimbParams` dict (`Par1..3`). Gaze is captured by global `Params["Par1"]`, whose user-facing label is configurable (currently `Looking1`).

`Video` exposes `dataLH / dataRH / dataLL / dataRL` as lightweight `LimbView` wrappers around the same shared `frames` dict, so legacy code that indexes a single limb still works.

### Background processes

[`adapters.frame_buffer.FrameBuffer`](src/adapters/frame_buffer.py) owns one daemon loop plus
an adaptive decode pool (`max(3, min(8, cpu_count // 2))` workers — PIL releases the GIL
during decode/resize, so the parallelism is real); the loop starts lazily after a video is loaded.
No worker ever touches a Tk widget — the buffering loop reads a `BufferContext` snapshot
instead of calling `winfo_width()`. The buffering thread and the decode pool also never
*call* into Tk, not even `after()`: from another thread that call is a synchronous
round-trip that waits for the Tk thread, so every slow repaint used to stall buffering.
Instead the Tk thread polls: `LabelingApp._display_pump` runs every `DISPLAY_PUMP_MS = 10`
and paints the current frame when its buffered image is not the one on screen (a frame
that finished decoding, or the buffer rebuilt after a resize); frames already buffered
are painted immediately by the navigation handlers. No worker thread calls Tk at all.
Painting pastes the frame into the `PhotoImage` already on the video label when the size
matches (`_show_frame_image`) instead of creating a new photo per frame — 12-22 % less
UI-thread time per paint; a resize still gets a new photo.
A resize of the video panel rebuilds the buffer (all frames are stored at display size),
so `LabelingApp.on_resize` ignores `<Configure>` events that keep the size and applies a
real change only after `RESIZE_SETTLE_MS = 100` without a newer one — a window-edge drag
costs one rebuild instead of one per event. The old frame stays on screen meanwhile.

- **Decode pipeline** -- each frame load computes its target size from the JPEG header
  (`compute_target_size`: fit the source into `display / downscale` aspect-preserving,
  upscaling low-res sources to fill big monitors), asks libjpeg via `Image.draft` to decode
  at a reduced DCT scale when the source is larger, then does one BILINEAR resize (skipped
  when draft lands exactly on target). Frames are buffered at final display size, so the UI
  thread never resizes at paint time.
- **Buffering loop** -- keeps decoded JPEG frames around the current frame, with an
  asymmetric, velocity-aware window: base read-ahead 50 / look-back 30, widened in the
  direction of the last navigation step (at least `2 × jump_frame_count`) and halved on the
  other side. The window is additionally capped at ~half the byte budget (using the running
  average frame size) so huge upscaled frames can't make eviction fight the submission loop.
  On a jump, queued-but-not-started decodes outside the new window are cancelled via their
  `Future`s so the jump target doesn't wait behind stale work. Eviction keeps at least ±200
  frames and scales with the window; the byte budget is `BUFFER_MAX_BYTES = 1 GB`. The
  current frame is loaded synchronously ahead of the pool; if the pool already holds a
  decode of it, that decode is cancelled (queued) or awaited (running), never repeated.
  The on-screen `Buffer: Loaded` / `Buffer: Loading` chip is set by the display pump.
- **Playback** -- not a thread: Play and arrow-hold playback are a chain of `after()`
  callbacks on the Tk thread (`LabelingApp._play_tick`), paced against a running deadline
  (`_next_playback_deadline`). Small callback delays remain on the clock so later steps
  can recover the elapsed time. Each callback paints at most one frame and yields for at
  least 1 ms; lag beyond 250 ms starts a new clock rather than an unbounded catch-up.
  Wheel navigation retains its separate `_next_deadline` policy. A step happens only once the current frame
  and the next `PLAYBACK_BUFFER_AHEAD = 3` frames in the play direction are buffered; until
  then it re-checks every `PLAYBACK_STALL_POLL_MS = 20` ms, so playback stalls briefly
  rather than stutters. Every write to `current_frame` is therefore on the Tk thread.
  Video presentation runs at source FPS while annotation controls and both timelines
  refresh at most 25 times per second. The timelines retain their existing cached static
  content and move their cursor between rebuilds. Unchanged semantic button styles do
  not request another widget repaint. Stop, release, boundaries, exact navigation and
  annotation actions synchronize deferred controls immediately. Focusing Notes pauses
  before editing. `displayed_frame` still advances only after successful video painting;
  an unpainted requested frame remains ineligible for annotation.
  Arrow key-down steps once and arms a 150 ms hold timer. Releasing before it fires
  preserves single-frame taps; otherwise playback starts without waiting for OS repeat.
  Playback stops on release or focus loss. A release is
  deferred with `after_idle`, then cancelled by a same-direction repeat press, so X11
  release/press repeat pairs do not interrupt playback. OS repeat timing does not pace
  playback. Toolbar `<` / `>` retain exact single-frame stepping.
  Two Windows timing details make this precise: deadlines use `time.perf_counter()`
  (`time.monotonic()` there is `GetTickCount64`, 15.6 ms steps), and while playback or
  wheel scrolling runs, `adapters.timer_resolution.PreciseTimers` holds a 1 ms timer
  resolution (`timeBeginPeriod`), without which Tk's `after()` is rounded to the 15.6 ms
  system tick. Both are no-ops for correctness elsewhere.

Frame extraction (`adapters.frame_extractor.create_frames`) runs synchronously inside a small Tk progress window the first time a video is opened:

1. **Reliability mode** -- if frames already exist for the *non-reliability* original of the same video, copy them over instead of re-extracting.
2. **ffmpeg path** -- bundled via `imageio-ffmpeg`, called as `ffmpeg -i video -q:v 2 -start_number 0 frames/frame%d.jpg` (fast).
3. **OpenCV fallback** -- sequential `cv2.VideoCapture` decode + `cv2.imwrite`, used if ffmpeg is unavailable or fails.

Frame counts are sanity-checked against `cv2.CAP_PROP_FRAME_COUNT` with a 0.1% tolerance (`FRAME_COUNT_TOLERANCE_PCT`).

Both extraction backends fit newly generated JPEGs into a 1920x1080 box without
upscaling or cropping. FFmpeg evaluates the scale after autorotation; OpenCV uses
the actual decoded pixel dimensions. Neither changes the frame numbering or
adds an FPS conversion. Existing frame caches and Reliability copies are retained.

`gui.video_surface.GpuVideoSurface` embeds SDL's accelerated renderer in a
Tk-owned native child window, using PySDL2's stable SDL2 bindings. The controller
attempts it after a video loads when `video_renderer=auto` (the default). Missing
libraries, unsupported embedding and drawing errors retain or restore the existing
PhotoImage path. Settings offers Automatic/CPU and shows the active renderer.

The worker's `BufferContext.resize_in_worker` flag selects its output: CPU mode
keeps the existing draft-decode-and-resize path; GPU mode retains draft-decoded
RGB pixels and lets SDL scale them. GPU initialization, upload, expose/resize
redraw and cleanup all stay on Tk's thread. A mode switch resets the buffer
generation and pauses playback. Native texture/renderer/window resources are
released before Tk destroys the child, including direct `LabelingApp.destroy()`.
SDL wraps the native handle without owning the Tk window; it does not run a second
navigation loop. The PyInstaller spec collects both the lazy Python binding and
the bundled SDL binaries explicitly.

`displayed_frame` advances only after a successful GPU or CPU paint. Frame-bound
annotation actions wait until it matches the requested frame; decoding a frame
into the buffer alone does not authorize an annotation. Switching renderers
preserves an unsaved note through the asynchronous repaint. The SQLite/CSV and
diagram-coordinate contracts are unchanged. See [manual acceptance](docs/VIDEO_RENDERING.md).

## Labeling Modes

### Video library and frozen coding setups

`Load Video` opens a themed project library. New videos go through a setup wizard
before copying/extraction: choose a mode and diagram or shared configuration,
review zone aliases, four channel labels and six parameter labels, then prepare.
Existing prepared projects resume directly. The library inspects project metadata
without creating databases. Filenames alone are not proof of video identity:
ambiguous same-name sources must be rejected rather than silently reusing frames.

`domain.coding_setup.CodingSetup` is the immutable coding definition. Its portable
JSON representation uses `Channel1` through `Channel4`; working-state adapters
retain the established `RH`, `LH`, `RL`, `LL` keys in that order. This avoids
reinterpreting existing annotation rows. Diagram geometry and zone IDs remain
unchanged. New selectors use Channel 1–4 with user-supplied labels.

`adapters.coding_configs.CodingConfigStore` reads and writes named JSON files in
`config/` beside the application's `config.json`. The GUI supplies this directory,
so source, frozen builds and isolated tests resolve the same writable location.
These files are reusable starting points, not live references. Each project keeps
its own complete snapshot in SQLite metadata. Application appearance/playback
preferences remain in `config.json` and cannot redefine a prepared project.

Preparation state (`draft`, `preparing`, `ready`, `needs_review`) distinguishes a
usable video from an interrupted preparation. After frames have been verified,
the repository marks the setup ready and locks its definition. Repository methods
enforce the lock, including legacy template/zone-name setters. Annotation values,
notes, Special Zones marks and visibility preferences remain editable.

Supported older databases without a snapshot can adopt their recorded template,
zone aliases and export parameter labels. Missing historical label provenance
requires review; mutable global preferences are not historical evidence. A new
Reliability pass inherits the full prepared setup, with separate annotations.
This adoption does not restore retired pre-SQLite project formats.

### Diagram registry and compatibility

`domain.templates.TEMPLATES` remains the registry for diagram labels, image/mask
paths, native dimensions and historical anatomical display names. The GUI and
adapters resolve assets through `asset_path`; all diagram and mask consumers use
the active project's template. Switching a draft template clears its mask cache.

General uses eight square zones (`1`-`8`). Portable channel order is Channel1 (`RH`),
Channel2 (`LH`), Channel3 (`RL`), Channel4 (`LL`), independently of historical CSV
column order. New exports use these generic channel identifiers for every diagram.
The squares carry no printed IDs; enabling "Show zone names" in Settings draws the
zone IDs or project zone names on them. The footer boxes 1-4 are zones of their own,
`Channel1`-`Channel4` in portable order, so a channel can be the target of a touch the
way a hand or leg can on the anatomical diagrams: a click on a box records a dot and
that zone for the *selected* channel and never changes the selection (the radio
buttons do that). `general_<key>.png` fills the selected channel's box. The box
geometry lives in `domain.templates` (`general_footer_box`), shared by
`generate_general_template.py`, which draws the boxes and writes their masks.

The existing template-only lock is retained for historical projects and becomes
locked when a full setup is prepared. Deleting annotations never unlocks it.
`ZoneDisplaySettings` still owns aliases and the show-names preference; prepared
aliases must match the setup snapshot, but visibility can change independently.
`adapters.zone_masks.zone_label_positions` finds an interior point for each label;
`gui.zone_labels` draws the same aliases in annotation and Special Zones views.
`LINE` and `NN` cannot be renamed. Zone IDs, mask geometry and native coordinates
remain stable; names belong in metadata and presentation only.

### Touch Annotation

- Navigate frame-by-frame: `←` / `→`, mouse wheel, `<<` / `<` / `>` / `>>` buttons, `Space` or Play / Stop, click on either timeline. `Shift`+arrow and `<<` / `>>` jump by `jump_seconds` worth of frames. All key bindings live in `gui.ui_components._bind_navigation` and are suppressed while the note entry has focus (`_guard_key`). Wheel notches are queued and consumed one frame per video frame interval (`LabelingApp._wheel_tick`), so a fast flick moves at playback speed rather than racing the redraw; the queue is capped at `WHEEL_BACKLOG_S` so motion stops shortly after the wheel does.
- **Select Frame**, between `<` and `>`, pauses playback and cancels queued wheel/arrow movement before opening a modal integer dialog. OK/Enter validates the range and jumps through `next_frame`; Cancel/Escape leaves the frame unchanged. Wheel navigation and queued playback advances are suppressed while the dialog is open. The frame counter is read-only; Notes is only for annotations.
- Pick Channel 1–4 via radio buttons; each selector includes its configured name and the diagram re-renders with that channel's overlays.
- **Left-click** on the diagram = touch-onset (green dot), **right-click** = touch-offset (red dot), **middle-click** or `d` = remove the dot nearest the pointer (within ~20 display px).
- **Hover feedback** (`gui.diagram_highlight.DiagramHighlighter`, toggled by `diagram_hover_effects`): the zone under the pointer fades in with an amber tint, glow and outline, a tag next to the pointer names it (renamed zones as `Name (ID)`), and a click flashes the zone in the dot's colour. The zone comes from `domain.touch.zone_label_map`, the per-pixel form of `zones_at`, so it is always the zone the click would record. The overlay is a canvas item of its own (`hover`, below the zone labels and dots), repainted on one `after` loop that exists only while a fade is in progress, so an idle or steadily hovered diagram costs nothing during playback. The dots-only repaint leaves it alone; a full repaint deletes it and the next motion recreates it. The Special Zones window (`gui.special_zones_app`) runs a second instance on its own canvas with the same masks, so its green dots land on the zone that was lit.
- Zones under each click are auto-detected from per-zone PNG masks under [src/resources/icons/zones3/](src/resources/icons/zones3/) (or [src/resources/icons/zones3_new_template/](src/resources/icons/zones3_new_template/) when the project uses `alternate`). Both directories are loaded by directory scan (`adapters.zone_masks.load_zone_masks`), so *every* PNG in them is live -- adding a file adds a zone. Masks are black-on-white; a hit is pixel `== 0` and a miss yields the `NN` sentinel (`domain.touch.zones_at`). The masks OVERLAP on 1.4% / 2.2% of the diagram (almost all of it the `LINE` mask lying over the zones it separates), so overlaps resolve by **precedence, not filename order**: real anatomical zone > `BOX1..BOX6` > `OUTSIDE` > `LINE` > `NN`. `LINE` means "the click is exactly between two zones", so it is only recorded when nothing else claims the pixel; sorted filename order is just the tie-break inside one tier (in practice only box-vs-box borders). The real/catch-all split is one predicate, `domain.touch.is_catch_all_zone`, shared with `touch_stats.zone_sort_key`. A click that resolves to `NN` is logged with a `WARN` naming the frame, limb and coordinates.
- Track infant gaze and up to 3 global + 3 per-channel parameters. Each button is a three-state toggle (`unset → ON → OFF → unset`, `domain.touch.cycle_param_state`); gaze can use global `Par1` by study convention. Button labels come from the frozen project coding setup and are included in export metadata.
- Six "boxes" on the diagram act as catch-all zones (ground, prop, etc).
- Two timelines visualize all touch events; the upper, slimmer one is the global scrub bar and the taller one is the 100-frame detail view for the selected limb.

The annotator-facing version of all of this is [docs/ANNOTATION_GUIDE.md](docs/ANNOTATION_GUIDE.md).

## Data Layout on Disk

Each labeled video produces a self-contained folder:

```
data/<video_name>/
├── state/                            # Working state (load/save round-trips here)
│   └── <video>.db                    # SQLite — THE source of truth (see below)
├── export/                           # Final, "publication-ready" artifacts
│   ├── <video>_export.csv            # Flat schema (see below) -- the file analysis reads
│   ├── <video>_metadata.json         # Program version, FPS, mode, special zones + note, param labels,
│   │                                 # total labeling time (hours)
├── frames/                           # frame0.jpg ... frameN.jpg (one per video frame)
└── plots/                            # Plotly HTMLs from "Analysis"
```

Every one of these paths is derived from the `ProjectPaths` dataclass in
[src/domain/project.py](src/domain/project.py) -- no other module hand-builds
them.

### Supported data layout (no migration path)

The app resumes supported schema 3 databases with recorded template IDs and
adopts their coding labels as described above. Other working-state formats are
not imported or converted.
Project loading rejects existing exports with no working database, preventing them
from being opened as an empty project and overwritten on Save. Use a fresh data
folder for new work and keep older project folders as archives.

New saves use the versioned channel export contract in `docs/DATA_FORMAT.md`.
Historical export pairs are archived before the first format replacement.
The app's Analysis workflow requires the template recorded in the accompanying metadata.

### Working state: `state/<video>.db`

One SQLite database per video ([src/adapters/sqlite_repo.py](src/adapters/sqlite_repo.py))
holds everything the app used to spread over six files: the frames store, notes,
per-frame and per-limb parameters, special zone dots and note, resume position and the
labeling-time accumulator.

| Table | Holds |
| --- | --- |
| `meta` | `video_name`, `fps`, `last_frame`, `total_frames`, `labeling_time_seconds`, `special_zones_diagram_scale`, `special_zones_note`, `template`, `template_locked`, optional `zone_display:<template>` |
| `frames` | one row per frame present in the store (its EXISTENCE is data) + `note` |
| `frame_params` | global `Par1..3`; absent row = key absent, `state IS NULL` = key present but None |
| `limb_records` | per-limb `onset` + a `has_limb_params` flag; a limb with nothing to store has NO row and is rebuilt as `empty_record(limb)` |
| `clicks` | `click_index` IS the `X`/`Y`/`Zones` alignment; `x`/`y` NULL = zone bucket with no click, `zones` NULL = click with no bucket |
| `limb_params` | per-limb `Par1..3`, same NULL semantics as `frame_params` |
| `special_zone_dots` | dot id, x, y, comma-joined zone string (frozen sidecar tokenization) |

Databases created during 9.0 development may also carry two now-unused tables,
`legacy_notes` and `legacy_limb_params`, plus `migrated_at` / `migrated_sources`
rows in `meta`. Nothing reads or writes them; `CREATE TABLE IF NOT EXISTS` simply
no longer lists them, so they are inert leftovers rather than schema.

Operational choices, all deliberate:

- **Saves are transactional and idempotent.** Each dirty frame (`Changed` is still the tracker) is deleted and re-inserted inside one `BEGIN IMMEDIATE`. Saving twice changes nothing; a crash leaves either the old or the new state. This retired the journal's duplicate-row resolution, load-time compaction and torn-tail repair.
- **`journal_mode=DELETE`, not WAL.** Single-writer desktop app, and WAL's `-wal`/`-shm` sidecars confuse OneDrive / Dropbox sync clients (these folders often live in synced trees). Plus `synchronous=FULL`, `foreign_keys=ON`, `busy_timeout=5000`.
- **One connection per open project, pinned to the Tk thread.** Every method asserts the owning thread; the export worker only ever sees the `deepcopy` snapshot.
- **`PRAGMA user_version`** carries the schema version. A DB from a newer TinyTouch is refused rather than silently down-converted.
- **Not persisted, by decision:** `Bodypart` (reconstructed from the limb key — every writer set it to exactly that and nothing reads it), `Touch` (no writer, no reader, no export column), the retired per-limb `Look`, and `Changed` (a runtime flag no backend ever serialized).

The split between the state DB and `export/<video>_export.csv` stays deliberate:

- **State DB** is the source of truth for round-trips, written incrementally.
- **Export CSV** is rewritten from scratch each save with one row per frame in the canonical legacy column order. Downstream consumers (Analysis, external tooling) read this file.

### Opening a project

`project_service.open_state` constructs `SqliteRepository(paths.state_db)`,
which creates the schema when the file is new, so the same call is both the
create path for a brand-new project and the open path for an existing one. It
then re-stamps the provenance meta (`video_name`, `fps`,
`created_by_version`) on every open, which is cheap and keeps an orphaned DB
self-describing. `repo.load_frames()` stays a separate step so the GUI can start
its labeling timer between the two.

`SCHEMA_VERSION` is 3. Existing databases must match exactly; the version is checked
before changing database settings or writing state. There is no migration or backup
path for older projects. The template metadata uses the existing `meta` table, and
older app builds cannot open these databases and bypass the template lock.

### Touch export schema

The full, normative specification — every column, every cell encoding, the metadata
sidecar, and the semantic conventions downstream analysis must follow — is
**[docs/DATA_FORMAT.md](docs/DATA_FORMAT.md)**. Summary for orientation only:

`<video>_export.csv` columns (from `export_from_unified` in [src/adapters/export_writer.py](src/adapters/export_writer.py)), one row per frame `0..total_frames` inclusive:

```
Frame, Time_ms,
Channel1_XY, Channel1_Onset, Channel1_Zones,
Channel2_XY, Channel2_Onset, Channel2_Zones,
Channel3_XY, Channel3_Onset, Channel3_Zones,
Channel4_XY, Channel4_Onset, Channel4_Zones,
Parameter_1, Parameter_2, Parameter_3,
Channel1_Parameter_1..3, Channel2_Parameter_1..3, Channel3_Parameter_1..3, Channel4_Parameter_1..3,
Note
```

Each `ChannelN_XY` cell contains JSON coordinate pairs; `ChannelN_Zones` contains
the matching zone groups. Both multiple points and multiple zones per point are
preserved. Misaligned data is rejected before publication. `Time_ms` uses source
FPS precision and three decimal places; unusable FPS gives an empty time cell.
Metadata records `Export Format Version: 2`, the full coding setup and coordinate
conventions. The reader normalizes both versions into the existing internal
calculation vocabulary. Older export pairs are archived before replacement.

**Version 2 is the current export contract.** Three test files pin it:
`tests/unit/test_export_schema.py` (column set + order),
`tests/unit/test_export_golden_master.py` (a checked-in fixture compared byte for byte) and
`tests/unit/test_export_metadata.py` (sidecar keys, order and formatting). Changing any of
them means breaking published research datasets, and requires coordinating with the
downstream pipeline first.

## Configuration

[config.json](config.json) is read on startup and after every Settings dialog "Apply". It is
parsed once into an `AppConfig` snapshot ([src/adapters/config.py](src/adapters/config.py))
that the GUI holds and passes down; nothing below the GUI re-reads the file. Unknown keys
survive a Settings round-trip (`AppConfig.raw` keeps the full parsed dict). Keys:

| Key | Settings UI | Purpose |
| --- | --- | --- |
| `diagram_scale` | no (corner grip) | Diagram render scale (1.0 = native), set by dragging the grip in the diagram's bottom-left corner (`gui.diagram_resize`, committed by `LabelingApp.commit_diagram_scale`). A value too tall for the screen is shown clamped until the next drag stores a new one. Display only — stored click coordinates are always at native scale. |
| `appearance` | yes | `light` (default) or `dark`. Applied immediately and remembered across restarts; body diagrams stay white. |
| `dot_size` | yes | Click-marker radius on the diagram. |
| `minimal_touch_length` | no | Visualization threshold (ms) shown as the "Minimal Touch Length" readout, converted to frames. **Filters nothing**, in the app or in Analysis. |
| `parameter1..3` | only without prepared video | Legacy machine defaults; a prepared video's global labels come from its coding snapshot. |
| `limb_parameter1..3` | only without prepared video | Legacy machine defaults; a prepared video's channel labels come from its coding snapshot. |
| `video_downscale` | yes | Display-only video downscale factor (1 = full, 2 = half). Affects rendering speed only. |
| `jump_seconds` | yes | Fast-jump distance in seconds for `<<` / `>>` and Shift+Arrow; multiplied by the frame rate at load time into `jump_frame_count`. |
| `diagram_hover_effects` | yes | Default `true`. Hovering the diagram tints the zone under the pointer and shows its name next to the pointer; a click flashes the zone in the dot's colour. Visual only (`gui.diagram_highlight`); the highlighted zone is the one `zones_at` would record. |
| `realtime_arrow_hold` | yes | Arrow key-down steps once; holding for 150 ms starts playback. Key-up or focus loss cancels the hold timer and stops arrow playback. Targets source FPS without skipping frames. Disabled: step per keyboard repeat. Toolbar `<` / `>` always step one frame. |
| `perf_enabled` / `perf_log_every_s` / `perf_log_top_n` | no | Optional `PerfLogger` (see [src/perf_utils.py](src/perf_utils.py)). When on, prints rolling averages of timed code blocks (buffer loop, click handlers, etc.). |
| `log_level_console` | no | Console threshold (`INFO` by default); `TINYTOUCH_LOG_LEVEL` overrides it for development. The session file always records `DEBUG`. |
| `log_keep_files` | no | Number of newest session log files retained (default 20). |
| `max_display_width` / `max_display_height` | no | Optional hard caps on the rendered video size (`0` = unlimited). |
| `last_labeling_mode` | no | Last-chosen `Normal` / `Reliability`; written by the mode dialog. |

Defaults for every key live in `adapters.config.CONFIG_DEFAULTS`, so a missing or corrupt
`config.json` degrades to defaults with a WARN instead of failing. When the app is run from
a PyInstaller bundle, `adapters.config._ensure_config_file()` copies the bundled default to
the install directory the first time so users get a writable copy.

## Observability

[`src/log_setup.py`](src/log_setup.py) configures stdlib `logging` once at the
application composition root. Runtime modules use `logging.getLogger(__name__)`;
annotation activity uses the dedicated `annot` logger and performance summaries use
`perf`. The root logger accepts `DEBUG`, while handler levels decide where records go:

- The console defaults to `INFO`. It shows lifecycle messages and deliberate annotation
  actions (clicks, deletions, limb/parameter selections, notes, special zones, mode and settings),
  so an annotator can see that input was registered. Automatic frame movement and buffer
  detail stay at `DEBUG`.
- A UTF-8 session file always receives `DEBUG` and above. Source runs write under
  `logs/`; frozen Windows builds prefer `%LOCALAPPDATA%/TinyTouch/logs`, and Linux builds
  prefer `$XDG_STATE_HOME/tinytouch/logs` or `~/.local/state/tinytouch/logs`. Settings ->
  **Open Logs Folder** opens the active location.
- `sys.excepthook`, `threading.excepthook` and Tk's `report_callback_exception` route
  unhandled failures to the file. Caught exceptions use `logger.exception` at their
  handling boundary.

Log records are diagnostics, not a recovery format: the state DB remains the only source
of truth. Annotation records intentionally include locally entered note text, but no log
data leaves the machine. The domain layer remains independent of outer packages; its
statistics module may emit diagnostics through stdlib logging as the one narrow side-effect
exception to otherwise pure computation.

## Application Workflow

1. **Load Video** -- browse the library and resume a prepared project or select a
   new file and finish the coding setup wizard. Choices are gathered before the
   current project is detached. Save failure prevents switching. The new session
   is published only after its state is loaded and frames exist; successful
   preparation locks its setup. Frame extraction failure leaves a retryable project
   and a clean unloaded controller. Unloading retains the order: save current
   data/position/time, drop the active video, reset the frame buffer, close SQLite.
2. **Special Zones** -- mark a project-wide set of body zones (e.g. covered with clothes) and describe them in a note; stored in the state DB's `special_zone_dots` and `meta.special_zones_note` and surfaced in the export metadata as `Special Zones` / `Special Zones Note`.
3. **Annotate** -- pick a limb, click onsets/offsets, set gaze and parameters, type notes. Edits stay in memory until Save.
4. **Save** -- `Save` button (or auto on Close / before Load) writes the dirty frames to the state DB (one transaction), then the export CSV (full) and the metadata sidecar. The `Changed` flags are cleared.
5. **Analysis** -- runs `analysis_service.run_analysis` over the export CSV: per-limb summary stats, transition heatmaps, touch-trajectory plots, histograms, and a master HTML. Output lands in `plots/`; the service returns the master HTML path and `LabelingApp.analysis` opens it in the browser. See "Analysis conventions" below.
6. **Close** -- final save, persists labeling-time accumulator and last frame position.

### Analysis conventions

The Analysis pipeline is three layers, in this order, with all computation
finished before the first file is written (so a failure can never leave a
half-populated `plots/`):

```
adapters.export_reader.read_export_df   read export/<name>_export.csv
        │                               (tolerates the legacy 6-line preamble)
        ▼
domain.touch_stats.parse_export         validate schema, rebuild Episodes
        │  summarize / transitions      per-limb stats + zone transitions
        ▼
adapters.plotting.write_*               heatmaps, trajectory, tables, histograms —
        │                               each returns a `ReportFigure` fragment
        ▼
adapters.report_page.write_master_html  arranges the fragments into
        │                               master_<name>.html (layout/CSS only)
        ▼
service_layer.analysis_service          orchestrates the above, returns the path
                                        (LabelingApp opens the browser)
```

Rules that downstream research depends on -- documented at length in
[src/domain/touch_stats.py](src/domain/touch_stats.py):

| Rule | Meaning |
| --- | --- |
| **Half-open `[ON, OFF)`** | A touch's duration is `OFF - ON`: active on the onset frame, offset frame excluded. Shortest closed touch = 1 frame. Matches what the labeler's timeline shades. |
| **Open touches are censored** | An `ON` with no `OFF` is `Episode.closed=False`: no duration, excluded from totals / percentages / means / stdev / transitions / histograms, but counted and reported as "open (unterminated)" in the tables, the master page and a `WARN` log. The GUI runs `domain.touch.find_open_touches` on the in-memory frames before analysis and shows `gui/open_touches_dialog.py`: jump to the onset, or analyze with the touches left open. |
| **Transitions are pairwise** | A touch with 2 start zones and 2 end zones contributes 4 heatmap counts, so heatmap totals exceed the touch count. Stated in the heatmap subtitle. |
| **`minimal_touch_length` is not a filter** | It is a GUI display threshold only; analysis counts every closed touch, 1-frame ones included. |
| **Frame rate may be unusable** | `None` / `0` / negative fps (some containers report 0) never crashes: frame-based results are produced in full, every seconds-based value is empty, and the duration histogram switches to frame buckets. |
| **Zoneless ends fall back to `NN`** | Only for transitions, so a touch with no zone on an edge still appears in the matrix. `zone_touch_count` never gets the sentinel — it counts observed zones only. |
| **fps provenance** | An explicitly passed, usable frame rate wins; otherwise `"Frame Rate"` from `export/<name>_metadata.json`; otherwise frame-only mode. The winning source is logged. |

These rules are also stated for external readers in
[docs/DATA_FORMAT.md](docs/DATA_FORMAT.md#3-semantic-conventions); keep the two in step.

The written artifacts and their file names are a contract too (the master page links
them and users bookmark them): `heatmap_ChannelN.html` for version 2 (legacy
exports retain `heatmap_<LIMB>.html`), `touch_trajectory.html`,
`analysis_table_frames.csv`, `analysis_table_seconds.csv`, `table.html`, `histogram.html`,
`histogram_2.html`, `master_<name>.html`. The additional `zone_table.html` shows zone
touch counts with readable names and separate stable IDs.

Analysis resolves `domain.report_labels.ReportLabels` from export metadata before
creating the output directory. New metadata validates its single `Coding Setup` snapshot;
older metadata validates optional `Zone Labels` and `Channel Labels`;
older exports fall back to zone IDs and template channel names. Labels affect only
presentation: renamed zones display as `Name (ID)` so duplicate names remain distinct.
Heatmap ticks and hover data, trajectory hovers, summary/zone tables, and histogram
legends use the same labels. User text is escaped before entering Plotly text fields.
Calculations, matrix axes, existing file names, and both analysis CSVs keep their IDs.

General channel images include a footer highlighting the owning channel in annotation
and report trajectory panels. `generate_general_template.py` rebuilds the neutral and
four highlighted images and the masks; the footer geometry comes from
`domain.templates` so the drawn boxes and the clickable boxes stay aligned.

The master page inlines every figure `<div>` into ONE scrolling document and loads a
single shared `plots/plotly.min.js` (written by plotly via `include_plotlyjs="directory"`).
The standalone figure files reference the same bundle, so a `plots/` folder must travel
as a whole when shared. Wheel-zoom is disabled on every figure (`scrollZoom: false`) —
the mouse wheel scrolls the page; zooming is an explicit drag-select.

## Testing

Coding setup tests cover portable-file validation, full project snapshots,
preparation locking, legacy label adoption and Reliability inheritance. Export
tests cover the versioned Channel1–4 schema, aligned paired coordinates and zone
groups, multiple points/multiple zones, timestamp rounding, and reading historical
exports for analysis. GUI tests must isolate both the project roots and the
`config/` directory; they must never modify real research projects.

```bash
uv run pytest                 # complete non-GUI suite
uv run pytest -m gui          # the excluded end-to-end GUI tests (needs a display)
```

[pytest.ini](pytest.ini) sets `testpaths = tests` and `addopts = -m "not gui"`, so the
default run is headless. The suite is a pyramid:

| Directory | Scope |
| --- | --- |
| `tests/unit/` | Pure rules and single adapters: export encoding, config, SQLite repository, touch statistics, zone detection, thread-boundary guards, theme. |
| `tests/integration/` | Several layers together: the analysis pipeline end to end, the load/save lifecycle. |
| `tests/e2e/` | A real Tk root driven through `tests/e2e/gui_driver.py` — smoke test, annotate/save/export, loading a second video mid-session, close during extraction. Marked `gui` and deselected by default. |

`test_zone_names.py` exercises all three templates through Settings, annotation,
save, reopen, and Analysis, then checks inherited names and reports in Reliability
without changing the original export. The startup smoke test also exercises delete
input with no video loaded; the shared handler treats this as a no-op.

The export schema and golden-master tests pin the published format. Version 2
round-trip tests also reconstruct paired coordinates, zone memberships and touch
episodes through the reader. The shared-configuration integration test proves that
editing a preset after preparation cannot change an older video's exported labels.

## Local Build

```bash
uv run pyinstaller TinyTouch.spec
```

Produces a standalone executable in `dist/`. The spec bundles two `datas` entries, and their destinations must stay in step with [src/gui/resource_utils.py](src/gui/resource_utils.py):

| Spec `datas` | Bundled at | Read via |
| --- | --- | --- |
| `config.json` | `<_MEIPASS>/config.json` | `resource_path("config.json")` |
| `src/resources` | `<_MEIPASS>/resources/…` | `asset_path("icons/…")` |

`resource_path` resolves distribution-root files; `asset_path` resolves the bundled runtime-asset tree (`src/resources/` from source, `<_MEIPASS>/resources/` when frozen). Change one and you must change the other.

## Releasing a New Version

A GitHub Actions workflow ([.github/workflows/build.yml](.github/workflows/build.yml)) builds and publishes Windows x64 and Linux x64 (Ubuntu 24.04 / Python 3.12) artifacts on every non-legacy `v*` tag push, then creates a GitHub Release with the zips attached.

Quick reference:

Update `PROGRAM_VERSION` in `src/app_info.py`, `version` in `CITATION.cff`, and the
README version badge, executable examples, and versioned documentation links together.

```bash
# Bump PROGRAM_VERSION in src/app_info.py, commit, push to master, then:
git tag v9.0.0
git push origin v9.0.0
```

### Labeled export diagram and compact metadata

Metadata revision 2 retains one `Coding Setup` snapshot. `adapters.export_diagram`
renders the selected template with CSV zone IDs and a saved-name legend to
`<video>_diagram.png` without Tk. `save_service` stages and publishes CSV, JSON, and
PNG together, rolling back ordinary replacement failures. The JSON references
the PNG by relative filename and SHA-256. CSV format remains version 2; analysis
accepts both metadata revisions. Older export revisions are archived before
replacement. See `docs/DATA_FORMAT.md` for field paths and coordinate conventions.
