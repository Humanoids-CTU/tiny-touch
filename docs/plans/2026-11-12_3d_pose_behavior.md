# 3D pose mode: intended behavior and acceptance criteria

Date: 2026-11-12
Status: behavior specification; implementation not started.

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
  100% size / 0% adjustment. The physical interpretation of that factor still
  needs confirmation (see open decisions).
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

### Navigation cases not yet agreed

The old code wrote carry values during paused forward navigation, not playback.
A jump could label the destination while leaving skipped frames unset. Backward
navigation did not fill frames, but visiting a saved value could change the
value subsequently carried. These are historical facts, not accepted edge-case
requirements. Decide playback, arrow holding with skipped painted frames, seeks,
backward navigation, and carry initialization after reopening before implementing
those paths. Do not silently substitute whole-interval filling.

## 3. Joint annotation and quality

- Keep clickable joint targets, onset/offset annotation, and a simple quality
  slider ranging from 0 to 1. Quality is required, not an optional later feature.
- Historical target set: left/right shoulders, elbows, wrists, hips, knees,
  ankles, plus neck (13 joints). This is the initial restoration baseline.
- Historical interaction: left click creates ON, right click creates OFF;
  middle click or `d` deletes a nearby current-frame event.
- The intended baseline is ON starts a joint-problem interval and OFF ends it.
  Confirm the precise research meaning before finalizing labels/export wording.
- The quality control must clearly identify which joint it edits. Editing one
  joint's quality must not modify other joints, body scale, or head scale.
- Do not infer scale-style carry behavior for quality: its association and
  carry rules are still open.
- Historical quality changed marker opacity for the last-clicked current-frame
  event, including OFF events. This is context, not a settled semantic contract.

Acceptance checks once the remaining semantics are settled:

- J1: ON and OFF affect only the targeted joint and produce the agreed interval.
- J2: Quality accepts both endpoints (0 and 1); invalid values cannot enter saved
  state. The selected joint/value remain understandable even at quality 0.
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

1. Scale range: user proposed +/-50%; historical range was +/-30%. Confirm range
   and step size (historically 0.01 factor).
2. Meaning of scale: observed estimated pose size relative to the subject, or
   correction factor needed to make it fit?
3. Forward carry during playback, arrow holding, jumps, backward visits, and
   reopening; treatment of skipped frames and uninitialized carry state.
4. Quality meaning at 0 and 1, default value, event/frame/interval ownership,
   treatment of OFF events, and whether it carries at all.
5. Exact joint-problem semantics and handling of repeated ON, unmatched OFF,
   and deletion of interval boundaries.
6. Head/body overlay appearance and joint interval presentation.
7. Normal/Reliability setup and scope, including source association and exports.
8. Exact representation/export of unset scale and quality values.

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
