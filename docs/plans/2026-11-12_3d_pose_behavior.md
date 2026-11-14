# 3D pose mode: intended behavior and acceptance criteria

## Current behavior correction — 2026-11-14

This correction supersedes conflicting joint/template/timeline details in the
2026-11-13 implementation record below. Unchanged carry, quality, save and
painted-frame safety rules still apply.

- The annotation chooser uses the Normal/Reliability dialog's segmented-control
  style, with **Touch** and **3d Pose**, followed by Continue.
- Pose uses **Alternate**. Default and General are disabled, without Coming soon suffixes. Its saved setup uses `template=alternate`; Pose still has no channels.
- Clicks label Alternate **body zones**, not the former 13 joint targets.
  Supported IDs are A–T, QB/RB/SB/TB and BOX1–BOX6. Left click sets ON, right
  click OFF, and middle click / `d` clears the event in the clicked zone on the
  current painted frame. Background/outline-only clicks do not create events.
- Pose has one global ON-inclusive/OFF-exclusive interval. An OFF in any zone
  closes it, including an ON placed in another zone. Repeated ON keeps it active;
  unmatched OFF keeps it inactive. Quality remains one optional
  global value per frame, independent of all zone events.
- The wizard shares Touch's template previews, zone editor with highlighting,
  global parameter fields and review. Channel fields are absent. Alternate is
  enabled; Default and General stay disabled. Reuse, import and optional saving
  of coding configurations are available. Alternate Touch configurations reuse
  zone aliases and global parameters without their channels. Zone aliases are saved in Pose setup,
  without changing annotation IDs; prepared setup remains locked.
- The diagram preserves the exact Alternate artwork and original zone layout.
  At non-neutral scale, the original is slightly gray and only the exterior
  body/front-head outlines grow or shrink; the back-head outline stays fixed. Original zones remain clickable at all sizes.
  A padded viewport keeps enlarged outlines visible; the corner grip zooms the
  entire view. Head is above Body in the controls. Changes render immediately. Hover tint,
  zone-name tooltip and click flash use the same highlighter as Touch.
- Pose uses the existing Touch detail/overview renderers, including the frame
  grid, colors, notes, parameter ticks, corners and playhead. Only two horizontal
  scale traces are added: Head above Body. No numbers, quality or count track.
  The overview follows Touch's closed-interval shading; detail shows open activity.
- Event dots use Touch's marker sprites and configured dot size; active zones
  show hollow markers between their ON/OFF events. Space on Pose sliders and
  Reset/Clear buttons toggles playback instead of activating the focused button.
- Analysis is disabled in Pose, including its direct action handler. Pose export
  and Analysis remain deferred; Touch behavior and export format are unchanged.
- Pose storage is now schema 3, using `zone_events(frame, zone, event)`. Earlier
  experimental joint-based Pose databases are rejected and left intact; create
  a fresh Pose copy to test the zone workflow. No migration or deletion occurs.

Acceptance: check Alternate selection/disabled choices; click, replace and delete
zone events at small/neutral/large body and head sizes; verify faint reference
outlines, positional scale traces and no quality/count/numeric timeline labels;
save/reopen events and independent quality; confirm Analysis remains disabled.
Existing carry tests and failed-save protections remain required.

Validation on 2026-11-14: 419 affected regression tests passed, followed by 11
lifecycle tests including new Analysis-button checks. Headless artwork was
visually inspected at maximum body/head scale. All 30 zone targets were checked
at every combination of minimum/neutral/maximum body and head scale. Actual Tk
layout and slider/playback responsiveness still need manual acceptance.

## Previous implementation record — 2026-11-13

Date: 2026-11-12
Status: 2026-11-13 implementation includes typed setup, controls, sparse timelines,
shared annotations and complete workspace save/reopen/lifecycle routing.
Automated checks are headless; manual GUI acceptance remains open. Pose
CSV/export and Analysis are explicitly deferred by agreement.

Correction (2026-11-13): quality is one global value per frame, not per joint.
The initial per-joint implementation was a misunderstanding and has been removed.
Joint onset/offset annotations remain independent of this frame-wide value.

This document records the user's intended workflow. Use it during implementation
and review, alongside [the restoration plan](2026-11-11_restore_3d_pose_mode.md).
Where they conflict, this specification takes precedence. In particular, the
earlier proposal to apply a scale change immediately to every future frame is
superseded by the forward-labeling workflow below. Historical behavior is evidence,
not automatically a requirement.

## 1. Scope and setup

- Restore pose-quality annotation alongside Touch. This is not a 3D viewer,
  pose inference engine, or XYZ editor.
- Pose has no Touch channels or limb selector. Body/head scale controls occupy
  the relevant control area instead.
- Pose supports one dedicated template. Other template choices are visibly
  disabled and cannot be selected for Pose.
- Notes retain the current shared notes workflow.
- Special Zones should retain the current application's behavior in Pose too.
  This is a new requirement: historical Pose clicks did not record special-zone
  events despite extra mask assets being present. Special Zones must not be
  silently converted into joint events.
- Parameter buttons are global only; there are no per-channel parameters.
- Setup order is annotation type (Touch/Pose), then Normal/Reliability.
  Reliability is an independent pass with its own setup; it does not inherit
  Normal labels or require an existing Normal project.

## 2. Body and head scale

### Confirmed interaction

- Provide separate body and head sliders, each with its own reset button.
- Display size clearly: +20% means a stored size factor of 1.20; neutral is
  100% size / 0% adjustment. The requested +/-50% range is adopted: factors
  0.5 through 1.5 inclusive; neutral is 1.0. UI edits round to steps of 0.01.
  These are user-defined numeric labels; no scientific interpretation is imposed.
- A manual slider edit records a manual value on the current annotation frame
  and makes it the value to carry forward for that scale.
- Moving forward to the next eligible frame transfers and records that value,
  reducing repeated slider work. Continuing forward repeats this until the
  value changes.
- A reset records neutral size on the current frame and makes neutral the
  value carried forward.
- Body and head values and carry state are independent.
- Editing frame 100 must not immediately label every unvisited future frame.
  This is assisted forward labeling, not automatic whole-future-interval fill.

### Intended protection of existing labels

The following rules were recovered from the old implementation and explained
during planning. Retain them unless explicitly revised:

- On forward arrival at an existing manual value, preserve it and adopt it as
  the value to carry next.
- An automatically carried value may be replaced by the current carried value
  when moving forward.
- Persist whether a value was manual or automatically carried. Saving/reopening
  must not turn automatically carried values into manual barriers.
- Merely displaying or synchronizing a slider must not create a manual edit.

### Acceptance examples

| ID | Action | Expected result |
| --- | --- | --- |
| S1 | Set body +20% at frame 100; advance to 101, then 102 | 100 is manual +20%; 101 and 102 are carried +20%. Unvisited later frames are not filled immediately. |
| S2 | After S1, set body +15% at 102; advance to 103 | 100 and 101 stay +20%; 102 is manual +15%; 103 is carried +15%. |
| S3 | Set head -10% while body carry is +20%; advance one frame | Head carries -10%; body still carries +20%. |
| S4 | Reset body at 104; advance to 105 | Both frames have neutral body size; 104 is manual and 105 carried. Head is unchanged. |
| S5 | Arrive forward at a frame already manually labeled +5%, carrying +20% | Preserve +5%; subsequent eligible frames carry +5%. |
| S6 | Arrive forward at a previously carried +5% frame, carrying +20% | Replace that carried value with +20%; do not change unrelated manual values. |
| S7 | Save and reopen records from S1/S2 | Values and manual/carried distinctions survive exactly. |
| S8 | Refresh controls or redraw the timeline without a user edit/navigation action | No annotation is created or changed. |

### Confirmed navigation rules (2026-11-13)

- Forward single-frame stepping (including a single forward mouse-wheel step)
  and forward arrow holding apply scale carry on
  each actually displayed frame. A skipped/unvisited frame is never filled.
- Ordinary Play, backward navigation, timeline jumps/seeks and refreshes only
  view recorded labels. They do not write labels or change session carry, even
  when displaying a manual value different from the current carry.
- A manual value reached by eligible forward navigation is protected and adopted
  for that scale. An existing carried value may be overwritten by active carry.
- A navigation request or decoded image alone does not permit a write: the
  destination must be the actually painted frame.
- Example: carry is +20%; jump to a manually labeled -20% frame. The slider
  displays that saved -20% label, while carry remains +20%. The next eligible
  forward step records +20% unless its destination has its own manual barrier.
  Displayed saved value and session carry are distinct.
- Carry is transient session state, separate from per-frame recorded values.
  **Current conservative restart policy:** initialize a new session with both carries inactive;
  viewing saved labels does not initialize them. A new manual edit/reset or an
  eligible forward arrival at a manual value activates the corresponding carry.
  This is implemented in the reopen service and application lifecycle.

## 3. Joint annotation and quality

- Keep clickable joint targets, onset/offset annotation, and a simple quality
  slider ranging from 0 to 1. Quality is required, not an optional later feature.
- Historical target set: left/right shoulders, elbows, wrists, hips, knees,
  ankles, plus neck (13 joints). This is the initial restoration baseline.
- Historical interaction: left click creates ON, right click creates OFF;
  middle click or `d` deletes a nearby current-frame event.
- ON starts an active joint interval; OFF ends it. No scientific meaning is
  imposed on this state. Intervals include the ON frame and exclude the OFF
  frame. Repeated ON leaves an already active joint active; unmatched OFF leaves
  it inactive. These deterministic boundary rules are explicit implementation
  choices for review, rather than recovered research requirements.
- Quality is one optional global value per frame from 0 through 1 inclusive.
  It requires no joint selection and does not modify joint events, body scale,
  or head scale. A new quality value replaces the previous value on that frame.
  Its research meaning and direction are user-defined. Unset is distinct from
  zero and one. There is no automatic default or carry.
- Quality can exist without ON/OFF. Writing/replacing/deleting an event preserves
  quality; writing/deleting quality preserves events. Quality does not affect
  the derived active-joint intervals.
- Historical quality changed marker opacity for the last-clicked current-frame
  event, including OFF events. This is context, not a settled semantic contract.

Acceptance checks:

- J1: ON and OFF affect only the targeted joint and produce the agreed interval.
- J2: Quality accepts both endpoints (0 and 1); invalid values cannot enter saved
  state. The frame quality remains readable even at 0; joints stay visible.
- J3: Quality can be inspected/edited without accidentally creating an unrelated
  ON/OFF event. Selection and event creation must be deliberately distinguishable.
- J4: Deletion removes the intended event and updates derived interval displays.
- J5: Joint events and quality survive save/reopen with their meaning intact.

## 4. Diagram and timelines

- Match the current main application's widgets and theme. Prioritize working
  annotation behavior; artwork polish can follow.

- Redesign the old pose diagram for visual quality and readability; do not treat
  the old artwork as a required appearance.
- Keep joint hit targets accurate relative to the displayed diagram. Scaled
  overlays must not silently change which joint a click labels.
- Show body and head scale as distinct, identifiable horizontal traces/marks
  over time, with a clear neutral baseline and larger/smaller direction.
- Retain detail and overview timelines, playheads, click navigation, notes,
  global parameter indicators, and joint onset/offset information.
- Show recorded scale values consistently with saved data/export. Distinguish
  an unset frame from an explicitly labeled neutral frame. A carried slider
  preview must not falsely appear as a saved label.
- Body and head visual feedback must be designed explicitly. The old head
  slider did not resize head geometry; do not accidentally preserve that omission.
- Timelines retain an aggregated active-joint strip and ON/OFF marks. Detail
  shows each recorded numeric point and gaps; overview pixel bins retain numeric
  extrema, both boundary kinds and the earliest note. The active count samples
  the last frame in each bin and can omit a shorter sub-pixel active interval.
- Preserve the smooth Touch playback/arrow-navigation behavior already manually
  accepted by the user. Pose rendering needs its own performance verification.

## 5. Persistence, lifecycle, and shared behavior

- Backward compatibility/import/migration for existing labeled data is not
  required. The user permits a new folder/data format and considers current
  labels disposable. This planning work does not delete any data; any later
  cleanup must identify its concrete targets.
- Save/reopen must preserve joint events, quality, both scales, manual/carried
  provenance, notes, global parameters, Special Zones, and project type.
- Future Pose exports must reflect recorded values and agreed missing-value
  rules; do not export slider previews as confirmed labels. CSV/export and
  Analysis are outside this implementation. Touch export remains unchanged.
- All edits, including carry writes, must target the correct actually displayed
  frame. Preserve the painted-frame annotation guard.
- Canceling project setup must leave the current project and controls intact.
- A failed save must not silently discard the active project.
- Keep Touch and Pose rules/state separate while sharing playback and navigation.
  No compatibility requirement does not mean permission to regress Touch behavior.

## 6. Selected implementation decisions and deferred work

1. Body/head and quality controls use 0.01 steps; the domain accepts continuous
   finite values. Quality remains optional and frame-wide, with no default/carry.
2. Reopen starts both carries inactive. Repeated ON/unmatched OFF follow the
   explicit deterministic interval rules above.
3. Separate body/head geometry responds to recorded values; unset uses a clearly
   labeled neutral preview. Joint targets follow the displayed body geometry.
4. Joint timelines use aggregated counts and boundary marks, with the sampling
   limit above. Manual GUI review can inform later presentation refinements.
5. Normal/Reliability are independent typed projects. Source identity protection
   checks shared frame folders across both Touch and Pose.
6. Pose export format, missing-value representation and Analysis remain deferred.
   Scientific quality meaning is a user choice.

## 6a. Earlier domain/storage checkpoints (2026-11-13)

This section records bounded earlier checks. The application coverage in 6b
supersedes their then-pending GUI/setup/shared-state scope.

`src/domain/pose.py` contains only stdlib code. `PoseLabels` owns independent sparse
joint events, quality and body/head scale labels. Reads return immutable values;
unset labels are `None`, never inferred neutral/default labels. `ScaleLabel`
retains manual/carried provenance. `PoseScaleSession` holds transient independent
carry values and explicit navigation intent; it never fills an interval.
All label writes require an explicit target/painted-frame match. The caller is
responsible for reporting successful painting honestly; no GUI is connected yet.

`PoseLabels.active_joints(frame)` is a reference pure projection that recomputes
after boundary edits. It is not yet a per-playback-frame rendering strategy.

Focused tests in `tests/unit/test_pose.py` cover S1-S6, S8, forward holding with
skipped frames, view-only navigation, inactive new-session carry, independent
quality/event deletion and editing, active-joint boundaries, all 13 IDs, finite
numeric ranges/types, immutable reads and rejected unpainted mutations.
J1-J4 have pure domain coverage only: selection, pointer hit testing, deletion
targeting and visible controls remain GUI work.

S7 and J5 now have headless storage coverage in
`tests/integration/test_pose_persistence.py`. `PoseSnapshot` is an immutable,
validated restoration boundary; `PoseSqliteRepository` saves/reopens only sparse
joint events, global frame quality and body/head scale labels with provenance.
`PoseProjectSession` opens the separate `state/<video>_pose.db` path and constructs
fresh inactive carry. Tests cover unset versus 0/neutral, independent deletion,
sparse gaps, continued manual/carried rules, transaction rollback and save retry,
unsupported-file preservation, corrupt-row rejection, owning-thread checks and
Touch coexistence. See [the bounded format](../POSE_STORAGE.md).
No export, project type/setup, notes, parameters, Special Zones, GUI lifecycle,
Linux or packaged-build acceptance is claimed.

Independent storage-stage review: 168 focused tests passed across
`test_pose_persistence.py` (32 tests), `test_pose.py`, `test_project_paths.py`,
`test_sqlite_repo.py`, and `test_touch_stats.py`. Review added checks for a
competing file during database creation, real Touch/Pose coexistence, and
repeated saves with multiple joints and both scales. A failed save is checked
through a separate database connection before retry. `git diff --check` passed;
no GUI was launched.

Independent review validation after the frame-quality correction: 96 tests passed
across `test_pose.py` (42 tests),
`test_touch_timeline.py`, `test_touch_stats.py`, and
`test_annotation_frame_ready.py`. A separate interaction check confirmed that
jumps preserve carry, skipped frames stay unset, event deletion preserves quality,
and rejected stale-frame edits leave labels and carry unchanged. No GUI was run.
The frame-wide quality regression failed against the former joint-required API
before the correction and passed afterward. Replacement/deletion is also checked
to preserve neighboring frames' quality values.

## 6b. Application coverage and manual acceptance

`tests/unit/test_pose_setup.py` covers typed setup, locked global parameter
labels, independent Reliability and cross-type source protection.
`tests/unit/test_pose_panel.py` covers S1-S6/S8 and J1-J4 at the interaction
adapter boundary: resets, quality 0/1/unset, geometry-aware hit testing, deletion,
painted-frame rejection, view-only navigation and deferred carry arrivals.
`tests/unit/test_pose_timeline.py` covers sparse gaps, extrema/boundaries/notes,
active counts, detail-zone changes, single-frame overview geometry and bounded
dirty redraws using fake canvases. Timeline clicks reuse the shared mapping
covered by existing Touch timeline tests.
These tests do not prove real widget appearance or responsiveness.

`tests/integration/test_pose_persistence.py` covers S7/J5 and storage validation.
`tests/integration/test_pose_workspace.py` adds full atomic saves of labels,
notes, parameters, Special Zones, timer and position, including rollback/retry
and the UI Save route with an open Special Zones dialog.
`tests/integration/test_pose_load_flow.py` runs the actual load and publication
methods with real repositories and fake widgets through Pose -> Touch -> Pose,
both Normal and independent Reliability, reopened carried provenance/inactive
carry, and canceled setup preserving the active project.
`tests/unit/test_pose_lifecycle.py` checks save/close failure retention, no Touch
record creation, no independent Pose timer checkpoint, disabled Touch-only
actions and listener detachment. Extraction, Tk widgets and actual workers remain
outside these headless tests. Existing Touch GUI fixtures explicitly default the
annotation-type picker to Touch; collecting those tests does not mean they ran.

Manual acceptance for Lucas (not yet performed):

1. Create Pose Normal and independent Reliability projects. Confirm only the
   dedicated template/global labels are available. Cancel each setup dialog
   while another project is active; confirm its video, controls and labels stay.
2. Edit body/head independently, reset each, and test quality unset/0/1 without
   joint edits. Left/right/middle-click and `d` should affect the intended joint.
   Confirm diagrams, readouts and both timelines remain readable at your window
   size and display scaling; inspect head/body feedback and unset numeric gaps.
3. Step and hold Right after a scale edit: only painted destinations acquire
   carried labels. Check manual barriers; Play, Left and timeline seeks must
   only view labels. Recheck smooth playback/holding in Touch after switching.
4. Save/reopen notes, parameters, joint events, quality, both scales and Special
   Zones with its note. Confirm carried provenance survives and carry restarts
   inactive. A new scale edit should replace later carried values on eligible
   forward arrivals and preserve existing manual barriers.
5. Switch Pose -> Touch -> Pose; inspect mode badges, channel/quality controls,
   notes, hover effects and timelines. Open/apply Settings in each mode. Pose
   Analysis must stay disabled and saving must not produce Touch CSV exports.
6. Where practical, provoke a save failure and confirm close/switch retains the
   project and permits retry. Reopen after successful retry to inspect all data.

No actual GUI, Linux runtime or packaged-build acceptance is claimed. The earlier
20,000-label/803-pixel fake-canvas benchmark measured Python projection/update
work (1,000 edits: median 0.118 ms, p95 0.209 ms), not actual Tk painting or video
performance. Manual responsiveness remains an acceptance gate.

Final independent review on 2026-11-13: 461 focused tests passed across Pose,
project setup/lifecycle, Touch exports, timeline rendering, painted-frame guards,
arrow/wheel navigation and playback. The 71 GUI tests were collected only.
`git diff --check` passed. No GUI or packaged build was run.

Stage 5 verification: 357 focused Pose/Touch project, annotation, save, navigation
and timeline tests passed, followed by 78 layer/export/configuration guards
(435 total). The 71 existing GUI tests were collected only. This is a targeted
feature check, not the complete non-GUI release suite.

## 7. Implementation review checklist

- Map each completed acceptance ID to a focused automated test or documented
  manual check. Do not mark an unresolved behavior as implemented by assumption.
- Test scale carry independently of the GUI, including manual-value protection
  and persistence round trips.
- Test project cancellation, save failure, displayed-frame safety, and switching
  between Touch and Pose.
- Verify notes, Special Zones, global parameters, and export consistency.
- Manually review the diagram, playback, arrow holding, scale feedback, timeline
  traces, joint selection, and quality editing with the user.
- Report Windows/Linux or packaged-build checks that remain unverified.

Historical reference: final pre-removal snapshot
`c085d5224eeb2e2393f3b00bbfb5e293a7c512f5`, especially
`src/labeling_app.py` (`_apply_pose_scale_carry_for_kind`,
`_apply_pose_scale_from_widget`, `_reset_pose_scale_kind`),
`src/pose_mismatch_data.py`, and `src/pose_timeline.py`.

## Fixed-channel refactor acceptance ? 2026-11-14

- Pose has exactly one internal annotation channel, with no channel chooser.
- Touch and Pose use `AnnotationChannel` for detail and overview ON/OFF rules.
- On a single frame, the newest click's ON/OFF kind applies to all its targets,
  just like Touch. Deleting one target retains the kind for remaining targets.
- OFF closes the channel regardless of the clicked zone. Hollow dots refer only
  to the latest still-open ON's targets. Repeated ON does not split an interval.
- Body/head scale, quality, notes and global parameters remain independent of
  channel transitions. Carry rules are unchanged.
- Existing saved mixed-kind experimental frames use OFF precedence until edited;
  opening a project does not migrate or rewrite its saved annotations.
- Cross-mode tests cover all 243 combinations of five ON/OFF/empty frames,
  same-frame edits and deletions, historical edits, and large sparse gaps.
