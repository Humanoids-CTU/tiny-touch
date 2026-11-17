"""Pending-change tracking in PoseLabels; pure domain, no storage."""

import pytest

from domain.pose import (
    Navigation, PoseChanges, PoseLabels, PoseScaleSession, PoseSnapshot,
    ScaleKind, ScaleLabel, ScaleSource, ZoneEvent,
)

BODY, HEAD = ScaleKind.BODY, ScaleKind.HEAD
MANUAL, CARRIED = ScaleSource.MANUAL, ScaleSource.CARRIED


def test_new_and_rehydrated_labels_have_no_tracking_token():
    assert PoseLabels().tracking_token is None
    labels = PoseLabels.from_snapshot(PoseSnapshot(quality=((1, .5),)))
    assert labels.tracking_token is None
    assert labels.pending_changes().is_empty


def test_start_tracking_issues_a_fresh_token_and_clears_pending():
    labels = PoseLabels()
    labels.set_quality(1, .5, displayed_frame=1)
    first = labels.start_tracking()
    assert labels.tracking_token is first
    assert labels.pending_changes().is_empty
    second = labels.start_tracking()
    assert second is not first and labels.tracking_token is second


def test_pending_changes_report_current_values_and_deletions():
    labels = PoseLabels.from_snapshot(PoseSnapshot(
        events=((2, "L", ZoneEvent.ON),), quality=((2, .1),),
        scales=((2, BODY, ScaleLabel(1.2, MANUAL)),)))
    labels.start_tracking()
    labels.set_event(2, "L", None, displayed_frame=2)
    labels.set_quality(3, .4, displayed_frame=3)
    labels.set_quality(3, .6, displayed_frame=3)
    labels.set_quality(2, None, displayed_frame=2)
    labels.set_scale(5, HEAD, ScaleLabel(.9, CARRIED), displayed_frame=5)
    labels.set_scale(6, HEAD, ScaleLabel(.9, CARRIED), displayed_frame=6)
    labels.set_scale(6, HEAD, None, displayed_frame=6)
    changes = labels.pending_changes()
    assert changes.upserts == PoseSnapshot(
        quality=((3, .6),), scales=((5, HEAD, ScaleLabel(.9, CARRIED)),))
    assert changes.deleted_events == ((2, "L"),)
    assert changes.deleted_quality == (2,)
    # Added then removed before a save: deleting a missing row is harmless.
    assert changes.deleted_scales == ((6, HEAD),)


def test_newest_click_on_a_frame_marks_every_rewritten_target():
    labels = PoseLabels()
    labels.set_event(4, "L", ZoneEvent.ON, displayed_frame=4)
    labels.set_event(4, "K", ZoneEvent.ON, displayed_frame=4)
    labels.start_tracking()
    labels.set_event(4, "M", ZoneEvent.OFF, displayed_frame=4)
    assert labels.pending_changes().upserts.events == (
        (4, "K", ZoneEvent.OFF), (4, "L", ZoneEvent.OFF), (4, "M", ZoneEvent.OFF))


def test_carry_marks_only_the_frames_it_writes():
    labels = PoseLabels()
    labels.start_tracking()
    session = PoseScaleSession(labels)
    session.edit(10, BODY, 1.2, displayed_frame=10)
    for frame in range(11, 14):
        session.arrive(frame - 1, frame, Navigation.FORWARD_STEP, displayed_frame=frame)
    session.arrive(13, 50, Navigation.JUMP, displayed_frame=50)
    assert [key[:2] for key in labels.pending_changes().upserts.scales] == [
        (10, BODY), (11, BODY), (12, BODY), (13, BODY)]


def test_mark_saved_keeps_edits_made_after_the_captured_changes():
    labels = PoseLabels()
    labels.start_tracking()
    labels.set_quality(1, .5, displayed_frame=1)
    changes = labels.pending_changes()
    labels.set_quality(1, .7, displayed_frame=1)
    labels.set_quality(2, .2, displayed_frame=2)
    labels.mark_saved(changes)
    assert labels.pending_changes().upserts.quality == ((1, .7), (2, .2))
    labels.mark_saved(labels.pending_changes())
    assert labels.pending_changes().is_empty


def test_changes_validate_their_rows():
    with pytest.raises(ValueError):
        PoseChanges(deleted_events=((-1, "L"),))
    with pytest.raises(ValueError):
        PoseChanges(deleted_scales=((1, "body"),))
    with pytest.raises(ValueError):
        PoseChanges(upserts=PoseSnapshot(quality=((1, .5),)), deleted_quality=(1,))
