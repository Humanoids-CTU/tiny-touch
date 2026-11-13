# 3D pose mode: intended behavior and acceptance criteria

Date: 2026-11-12
Status: behavior refined 2026-11-13; pure Pose domain/editing rules implemented.
GUI, project setup, persistence/export, and application integration are pending.

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
- Proposed setup order remains annotation type (Touch/Pose), then
  Normal/Reliability. Exact setup and Reliability details remain to be finalized.

## 2. Body and head scale

### Confirmed interaction

- Provide separate body and head sliders, each with its own reset button.
- Display size clearly: +20% means a stored size factor of 1.20; neutral is
  100% size / 0% adjustment. The requested +/-50% range is adopted: factors
  0.5 through 1.5 inclusive; neutral is 1.0. UI step size remains undecided.
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

- Forward single-frame stepping and forward arrow holding apply scale carry on
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
  **Restart proposal:** initialize a new session with both carries inactive;
  viewing saved labels does not initialize them. A new manual edit/reset or an
  eligible forward arrival at a manual value activates the corresponding carry.
  This is the pure model's conservative default; reopen integration is pending.

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
- Historical timelines aggregated active joint counts. Whether to retain that
  strip or expose individual joint intervals is a presentation decision still open.
- Preserve the smooth Touch playback/arrow-navigation behavior already manually
  accepted by the user. Pose rendering needs its own performance verification.

## 5. Persistence, lifecycle, and shared behavior

- Backward compatibility/import/migration for existing labeled data is not
  required. The user permits a new folder/data format and considers current
  labels disposable. This planning work does not delete any data; any later
  cleanup must identify its concrete targets.
- Save/reopen must preserve joint events, quality, both scales, manual/carried
  provenance, notes, global parameters, Special Zones, and project type.
- Exports must reflect the same recorded values and agreed missing-value rules
  as the UI; do not export slider previews as confirmed labels.
- All edits, including carry writes, must target the correct actually displayed
  frame. Preserve the painted-frame annotation guard.
- Canceling project setup must leave the current project and controls intact.
- A failed save must not silently discard the active project.
- Keep Touch and Pose rules/state separate while sharing playback and navigation.
  No compatibility requirement does not mean permission to regress Touch behavior.

## 6. Decisions required before dependent implementation

1. UI scale/quality step size (the domain accepts continuous finite values).
2. Confirm the inactive-carry restart proposal during reopen integration.
3. Review the explicit repeated-ON/unmatched-OFF boundary rules above.
4. Head/body overlay appearance and joint interval presentation.
5. Normal/Reliability setup and scope, including source association and exports.
   Review current independent Reliability setup rather than copying the older
   restoration plan's source-inheritance proposal.
6. Exact representation/export of unset scale and quality values. Scientific
   meaning remains a user choice, not an implementation prerequisite.

## 6a. Implemented domain boundary and acceptance coverage (2026-11-13)

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
targeting and visible controls remain GUI work. S7 and J5 remain deferred until
storage exists. No persistence/export, project type/setup, notes, parameters,
Special Zones, GUI, Linux or packaged-build acceptance is claimed.

Independent review validation after the frame-quality correction: 96 tests passed
across `test_pose.py` (42 tests),
`test_touch_timeline.py`, `test_touch_stats.py`, and
`test_annotation_frame_ready.py`. A separate interaction check confirmed that
jumps preserve carry, skipped frames stay unset, event deletion preserves quality,
and rejected stale-frame edits leave labels and carry unchanged. No GUI was run.
The frame-wide quality regression failed against the former joint-required API
before the correction and passed afterward. Replacement/deletion is also checked
to preserve neighboring frames' quality values.

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
