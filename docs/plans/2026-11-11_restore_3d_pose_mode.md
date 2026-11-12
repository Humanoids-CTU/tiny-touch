# Restore 3D pose-quality annotation mode

Date: 2026-11-11
Status: proposed; investigation complete; first Touch timeline extraction implemented.

## Behavior specification update (2026-11-12)

See [the intended behavior and acceptance criteria](2026-11-12_3d_pose_behavior.md)
before implementation. That specification takes precedence where this earlier
proposal differs: scale labels carry forward as the user labels frames, rather
than immediately filling all future frames; joint quality and separate body/head
sliders are required; current Special Zones behavior is requested; and historical
data compatibility/migration is no longer required. Open decisions are explicitly
listed there. No data deletion is part of this documentation change.

## Implementation progress (2026-11-12)

The first bounded refactor extracts pure Touch timeline projections, canvas
drawing and shared geometry/click mapping. Touch display behavior is retained,
including notes, parameter marks, existing zone carry and cached playhead updates.
The Touch timeline view owns per-canvas cache keys and playhead state; the
controller requests invalidation/reset and retains session navigation.
Focused tests use recording canvases without opening a GUI; this does not establish
visual acceptance or Windows/Linux packaged-build compatibility.

Independent review validation: 132 focused tests passed, with one pre-existing
expected failure for dark-palette contrast. An independent baseline comparison
matched 720 canvas outputs across 60 seeded datasets, covering cached movement,
segment boundaries, channel changes, resizing and invalidation, with annotation
data unchanged. Two GUI test consumers were updated and collection checked;
their windows were not launched. A separate recording-canvas comparison matched
another 200 outputs. Its Python-only rebuild measurement was 3.145 ms before
and 2.732 ms after; this excludes real Tk rendering and is not a playback FPS
claim. Manual visual acceptance remains with the user.

This is partial preparation for milestone 2, not completion of that milestone.
Project type metadata, separate Touch/Pose session and panel ownership, lifecycle
changes and all Pose functionality remain pending. The open semantic decisions
below are unchanged.

## Goal and scope

Restore the useful behavior of the former 3D pose-quality labeling mode with a
clean integration into the current TinyTouch architecture. Recover requirements
from the historical implementation, rather than restoring its controller branches
or reproducing accidental behavior. Preserve existing Touch projects and exports.

This mode evaluates pose-estimation quality. The old version did **not** provide
a 3D viewer, model inference, skeleton import, or editable XYZ coordinates. Those
features are outside this restoration proposal.

The user agreed with placing annotation type before Normal/Reliability in the
Load Video setup. Detailed pose semantics below remain proposals pending review.
The historical findings below come from read-only agent inspection. The progress
section records the subsequently authorized Touch refactor and its validation;
Pose implementation still requires the open decisions below.

## Historical evidence

- Removal: [`c55c1bd78715da3199ac88911a302bcf77193c0d`](https://github.com/Humanoids-CTU/tiny-touch/commit/c55c1bd78715da3199ac88911a302bcf77193c0d),
  **Remove 3D pose mode**, 14 August 2026 at 10:50 CEST.
- Exact final pre-removal snapshot: `c085d5224eeb2e2393f3b00bbfb5e293a7c512f5`
  (the removal commit's parent).
- Recovery tag: `v8.0.0`, resolving during inspection to
  `2ff7013f096144c7a800620e1c9825d2434b4f67`. The intervening commit reorganized
  tests; the final snapshot is the preferred source for reconstruction.
- Principal historical files: `src/labeling_app.py`, `src/ui_components.py`,
  `src/pose_mismatch_data.py`, `src/pose_timeline.py`, and `PROJECT.md`.
  Read these with `git show <revision>:<path>` without changing the checkout.

The removal message explains that the mode was rarely used, bug-prone, and
duplicated storage, export, and timeline concepts. The restoration should avoid
recreating those maintenance costs.

## Recovered behavior

| Area | Last implemented behavior |
| --- | --- |
| Setup | Independent Touch/3D Mismatch and Normal/Reliability choices; remembered defaults. |
| Joints | Thirteen joints: bilateral ankle, knee, hip, wrist, elbow, shoulder, plus NECK. |
| Events | Left click writes ON (problematic/missing joint); right click writes OFF (ends issue). One event per joint per frame; repeated clicks overwrite it. |
| Coordinates | Stored native diagram XY, not video coordinates. PNG-mask hit detection followed by nearest joint centroid within 28 native pixels. |
| Deletion | Middle click or `d` deletes nearest current-frame event dot within 20 display pixels; keyboard deletion uses last pointer position. |
| Diagram | Static diagram and translucent outline; green ON/red OFF markers for current-frame event records. Body scale resizes the outline around a fixed anchor. |
| Body/head scale | Separate horizontal sliders, 0.70–1.30 in 0.01 steps, with reset to 1.00; per-frame values and explicit-set flags. |
| Quality | Value 0–1 in 0.01 steps for the last-clicked current-frame joint event, including OFF events. Controls marker fill opacity; colored border remains opaque. Reset to 1.00. |
| Timelines | Detailed segment and full-video overview, joint events, cumulative active-joint counts, body/head scale traces, global parameters, playhead, and click navigation. |
| Shared tools | Playback/navigation, notes, three global parameters, resume position, labeling timer, saving and metadata. |
| Unavailable tools | Touch analysis, clothing, and per-limb parameters. Pose controls replace limb selection. |
| Reliability | Separate `_3d_reliability` annotations with frame reuse; no pose-specific agreement analysis. |
| Working data | `_3d` project naming and journal-style unified CSV; notes, parameters, scale state, and JSON joints containing XY/opacity. |
| Export | Per-frame Frame, Time_ms, ScaleFactor, HeadScaleFactor, Parameter_1..3, Event/Opacity for each joint, and Note. Joint XY was not exported. |

### Historical quirks to resolve, not copy blindly

1. **Navigation changed annotations.** After a slider edit, paused forward
   navigation wrote the scale into visited unset frames. Skipping frames left
   gaps, backward navigation did not write, and playback did not fill values.
   Timelines/export used 1.0 for unset frames even when the diagram displayed a
   carried value.
2. **Carry provenance disappeared on reload.** `ScaleAutoCarry` and
   `HeadScaleAutoCarry` were in-memory flags omitted from serialization. Reopened
   carried values appeared manual.
3. **Head scale did not change outline geometry.** It was saved and plotted, but
   rendering used body scale only.
4. **Selection and editing were coupled.** Enabling quality after reopening
   required clicking a joint, which also wrote an ON/OFF event. Selection was
   transient and frame-specific.
5. **Quality had no documented scientific meaning.** It was implemented as
   opacity, including on OFF events. Its meaning and interval behavior must be
   decided explicitly.
6. Diagram markers showed current-frame events while timelines showed cumulative
   active problems. Decide how the new UI distinguishes events from active state.
7. Slider input allowed thumb dragging and reset buttons but suppressed trough,
   keyboard, and wheel edits. This is historical behavior, not an accessibility
   requirement for the restoration.
8. Historical documentation lagged implementation: it omitted head scale and
   quality and described a vertical slider. Its claim about disabled Sort had no
   corresponding control in the final source.
9. Pose lacked Touch's export-based recovery path. Do not assume old data can be
   recovered or opened by the current application without an explicit importer.
10. Mode/control changes could happen before file selection completed. Canceling
    could leave an existing video under the newly chosen mode.

## Proposed user flow

For a new project:

1. Select video from the Load Video flow.
2. Choose **Touch** or **3D Pose Quality**.
3. Choose **Normal** or **Reliability** in the same setup flow.
4. Complete the relevant setup, then prepare/open the project.

Existing projects reopen directly using their saved annotation type. Show the
type in the project library. A Reliability pass inherits the source project's
type and frozen setup, with separate annotations. Where source selection is
ambiguous, require the actual source project rather than guessing by filename.

Annotation type is fixed for a prepared project, not a live switch over existing
data. Support separate Touch and Pose projects for the same video. Reuse the
existing fresh-copy mechanism where practical, with saved source association and
type validation; a wholesale project-ID redesign is not a prerequisite.

## Architecture proposal

Read `ARCHITECTURE.md` and the frozen `docs/DATA_FORMAT.md` before implementation.
Reinspect live code: this map reflects the 2026-11-11 checkout.

Keep the existing layers and extract a bounded set of Touch responsibilities
from `LabelingApp`. Share video/session lifecycle, while using distinct Touch and
Pose annotation models, services, panels, and export adapters. Avoid both a large
plugin framework and scattered `if pose` branches throughout the controller.

| Concern | Current seam | Proposed direction |
| --- | --- | --- |
| Setup/open | `LabelingApp._load_video_flow`, `gui/coding_setup_wizard.py` | Collect choices before publishing the active project; dispatch to type-specific setup. |
| Frozen setup | `domain/coding_setup.py:CodingSetup` | Existing setup is Touch-specific (four channels, parameters, masks/templates). Add a separate Pose setup and a small typed project descriptor. |
| Session/video | `video_model.py:Video` | Reuse video metadata, transport and frame handling. Separate Touch `FrameBundle`/`LimbView` assumptions from mode-specific annotation state. |
| Editing | `service_layer/annotation_service.py` | Preserve Touch rules; implement Pose operations against its own model. Share notes/parameters only where behavior matches. |
| Controls/diagram | `gui/ui_components.py`, `LabelingApp.rebuild_annotation_controls` | Mount a Touch or Pose panel in the shared application shell. |
| Refresh | `_refresh_frame_controls`, `_refresh_after_annotation_edit`, `mark_bundle_changed` | Delegate annotation refresh/dirty state explicitly; keep shared playback refresh. |
| Timelines | `draw_timeline`, `draw_timeline2` | Share navigation, playhead and useful layout/cache code; compute mode-specific display data in pure functions. |
| Save/load | `save_data`, `_unload_current_video`, `service_layer/project_service.py` | Dispatch persistence/export at the service boundary, retaining lifecycle guarantees. |
| Library | `adapters/project_catalog.py`, `gui/video_library.py` | Read/display saved type and use suitable previews instead of assuming Touch templates. |
| Tool availability | `_set_mode_button_states`, analysis and Special Zones entry points | Enable tools from supported mode capabilities; never send Pose data to Touch analysis. |

Existing portable `CodingSetup` files reject unknown fields and versions. Do not
insert an annotation-type field casually into that schema. Specify an explicit
versioned wrapper/adoption rule. Existing untyped current projects resolve to
Touch; an explicit malformed or unknown type must fail clearly.

Retain compatibility accessors during any `Video`/Touch extraction until all
callers have been migrated. Do not combine this work with the experimental web
frontend or version-manager proposal; production remains Tk-based.

### Proposed pose semantics

- Store explicit scale changes. A scale applies from its frame until the next
  explicit change, with 1.0 before the first change.
- Resolve the same effective values for diagram, timeline, and export.
- Navigation and playback never write annotations.
- Selecting an existing joint is separate from creating/modifying an event.
- Validate joint IDs and numeric ranges in the domain/service layer.
- Document event versus active-interval display and quality semantics before
  finalizing the model. These proposals intentionally differ from old quirks.

### Persistence and compatibility

Use the current SQLite approach with pose-specific records and a versioned pose
format. Do not add pose keys to Touch `FrameBundle` or change Touch export columns.
Choose the exact tables/migration strategy after a focused review of the current
repository implementation; that detailed schema design was not completed in this
investigation.

Document Pose export separately and test its column order, values, frame coverage,
and reload consistency. Decide whether historical export compatibility is needed
before promising identical output.

Historical CSV import is an optional, separate work package. If required, import
into a new project, preserve source files, validate ambiguous/missing state, and
report semantic changes. Do not silently reinterpret historical pose CSV as
current Touch or Pose data.

### Shared safety requirements

- Route every Pose mutation, including sliders and keyboard edits, through
  `_annotation_frame_ready`: the painted `displayed_frame` must match the target.
- Preserve successful-paint handling in `_show_frame_image` and
  `display_first_frame`; decoding alone does not permit annotation.
- Save the current project before unloading and retain it if saving fails.
- Publish the new session/type/panel together only after preparation succeeds.
  Cancellation must not change the active project's mode or controls.
- Preserve frame-buffer generation invalidation and stale-result protection.
- Keep SQLite operations on the owning Tk thread and background export on copied
  snapshots, matching the existing design.
- Retain Windows/Linux compatibility and verify packaging of recovered assets.

## Implementation milestones

### 1. Specify behavior and contracts

- Resolve the open decisions below and write mode-specific acceptance examples.
- Record useful historical assets/data fixtures without restoring old application
  code. Treat old tests as evidence, not a suite to copy unchanged.
- Review persistence and export contracts before selecting a schema.

Exit: an agreed model of joint events, quality, scales, setup and compatibility.

### 2. Add project type and isolate Touch behavior

- Add versioned type metadata, adoption of existing Touch projects, library
  display and same-type Reliability validation.
- Extend project-copy/path behavior for distinct projects sharing source media.
- Extract the minimal Touch panel/session operations needed by a second mode.
- Keep existing Touch behavior and exports unchanged; do not expose an incomplete
  Pose creation path as usable.

Exit: existing Touch projects work through the new boundary without data changes.

### 3. Implement Pose domain, storage and export

- Implement joint editing, selection, scale change points and decided quality
  semantics without a GUI dependency.
- Add pure timeline/display projections and shared-value resolution.
- Add repository round trips and a documented, versioned export.

Exit: pose state can be created, edited, saved, reopened and exported in focused
non-GUI tests, independent of navigation order.

### 4. Connect Pose UI and setup

- Add pose-specific setup, assets, joint controls, sliders and timeline content.
- Connect input through the painted-frame guard and shared project lifecycle.
- Expose supported capabilities and correct library previews.

Exit: a complete new Pose project and Reliability workflow is available.

### 5. Validate integration and release

- Test cancellation, failed saves, switching types and same-source projects.
- Verify existing Touch exports and project adoption remain compatible.
- Perform isolated GUI acceptance and Windows/Linux/packaged-build checks.
- Add historical import only if explicitly included in scope.

Exit: acceptance evidence distinguishes tested behavior from remaining platform
or packaging limitations; user documentation describes the final semantics.

## Validation plan

Use focused tests for each milestone, via `uv run pytest <relevant paths>`. Do not
run the full suite for a planning document or small refactor. Follow project
release rules for broader testing. Avoid launching GUI tests on the active
desktop; use an isolated display/environment when GUI acceptance is scheduled.

Relevant existing coverage to inspect/extend:

- `tests/unit/test_annotation_frame_ready.py`, `test_displayed_frame.py`,
  `test_playback_refresh.py`, `test_video_reload.py`.
- `tests/unit/test_project_library.py`, `test_project_copy.py`,
  `test_project_paths.py`, `test_project_templates.py`, `test_coding_setup.py`.
- `tests/integration/test_coding_setup_export.py`.
- Later GUI acceptance: `tests/e2e/test_video_library_wizard.py`,
  `test_duplicate_video.py`, `test_reload_video.py`, `test_playback_ui_sync.py`.

New behavior checks should include scale consistency after forward/backward
navigation, direct seeks and reload; ON/OFF interval boundaries; quality edits
without event creation; deletion; invalid types/joints/values; pose export
consistency; and prevention of cross-type Reliability inheritance.

## Open decisions for resuming work

1. What does **quality** measure, which direction is better, and is it attached to
   an event, a frame, or a problem interval? Should OFF events have quality?
2. What should **head scale** visibly change? Is a separate head outline/geometry
   needed, or is it an annotation-only value?
3. Approve deterministic scale change points in place of navigation-driven carry.
4. Should the diagram show active problems, current-frame events, or both?
5. Are historical 3D CSV import and historical export compatibility required?
6. Confirm the initial scope of pose Reliability: separate annotations only, with
   agreement analysis deferred unless requested.

Start the next implementation session by reviewing these decisions and the live
working tree, then implementing one milestone at a time. Do not restore the old
controller wholesale.
