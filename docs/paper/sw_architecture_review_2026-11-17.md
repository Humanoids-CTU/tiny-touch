# Review of the software architecture draft (2026-11-17)

Checks [sw_architecture_draft.md](sw_architecture_draft.md) (written 2026-11-03,
v9.1.0) and [figures/sw_architecture.png](figures/sw_architecture.png) against the
code at v9.4.0.

## Still accurate

- Components: Python 3.12, Tkinter, ffmpeg with OpenCV fallback, Pillow, SQLite,
  pandas, Plotly.
- Runs fully offline: nothing in `src/` imports networking code.
- Domain layer has no file, GUI or plotting code. Its only outside import is pandas
  in `domain/touch_stats.py`, used for calculations.
- Click-to-zone assignment is in the domain layer (`domain.touch.zones_at`).
- One folder per video, `data/<video>/`, with `frames/`, `state/`, `export/`,
  `plots/`.
- A background buffer decodes frames around the current position
  (`adapters/frame_buffer.py`).
- Each SQLite save is one transaction (`service_layer/save_service.persist_state`).
- Analysis reads only the export CSV and metadata JSON
  (`service_layer/analysis_service.py`).
- The CSV is pinned byte for byte by `tests/unit/test_export_golden_master.py`
  (line endings normalised, since they differ between Windows and Linux).

## Needs editing

### 1. "Every save also writes the export" is no longer exact

Every save rewrites the metadata JSON and the diagram image, but the CSV is
rewritten only when the annotations changed. An export failure is reported
separately; the annotations are safe because the state database is the source of
truth. The JSON list in the draft is also incomplete: since 9.3.0 it records zone
and channel labels, and a labeled diagram image is exported too.

Suggested wording:

> Every save also brings the export up to date: a CSV file with one row per video
> frame (rewritten only when the annotations changed), a JSON file recording the
> frame rate, annotation template, zone and channel labels, parameter labels, and
> labeling time, and an image of the labeled diagram. If the export fails, the saved
> annotations are unaffected and the failure is reported separately.

### 2. "Dependencies point in one direction only" does not fully hold

Six adapters import `gui.resource_utils`: `config`, `zone_masks`, `plotting`,
`export_diagram`, `channel_diagram`, `pose_diagram`. The module only locates
bundled files (it imports just `os` and `sys`), so it contains no GUI code, but it
lives in the GUI package. Three of these imports already existed when the draft
was written.

Options:

- [ ] Move `gui/resource_utils.py` out of `gui/` (for example to
  `src/resource_utils.py`). Then the text and figure are exactly true.
  Recommended; a small change.
- [ ] Or soften the sentence, for example "apart from a shared helper that
  locates bundled files".

### 3. Pose mode is not mentioned

If the paper covers only Touch, leave it out. Otherwise one sentence:

> A second annotation type, 3D Pose, records body-zone events and body and head
> size per frame; it uses the same video handling but stores its labels in a
> separate database, and its export is not yet available.

Without it, the export statements are only true for Touch.

## Optional updates

- "When a video is first opened, all its frames are extracted" → "When a video is
  prepared". Preparation is now a guided step, frames are scaled down to fit
  1920×1080, and interrupted preparation resumes.
- Video is drawn on the GPU with SDL2 when available, falling back to the CPU
  (`gui/video_surface.py`). SDL2 could join the list of components.

## Figure

Still matches the code apart from the dependency issue in point 2. If the text
changes:

- [ ] Add "diagram PNG" to `export/`.
- [ ] Show that `state/` holds separate Touch and Pose databases (only if Pose is
  mentioned).
- [ ] Optionally add "Prepare video" to Services.
