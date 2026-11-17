"""Pose behavior only; no Tk, adapters, or real research data."""

from dataclasses import FrozenInstanceError

import pytest

from domain.pose import (
    ZoneEvent, Navigation, POSE_ZONES, PoseLabels, PoseScaleSession,
    ScaleKind, ScaleLabel, ScaleSource,
)


BODY = ScaleKind.BODY
HEAD = ScaleKind.HEAD
MANUAL = ScaleSource.MANUAL
CARRIED = ScaleSource.CARRIED
JOINT = "L"


def edit(session, frame, value, kind=BODY):
    session.edit(frame, kind, value, displayed_frame=frame)


def advance(session, previous, frame, navigation=Navigation.FORWARD_STEP):
    session.arrive(previous, frame, navigation, displayed_frame=frame)


def test_s1_s2_scale_edits_only_label_visited_forward_frames():
    labels = PoseLabels()
    session = PoseScaleSession(labels)
    edit(session, 100, 1.2)
    assert labels.scale(101, BODY) is None
    advance(session, 100, 101)
    advance(session, 101, 102)
    edit(session, 102, 1.15)
    advance(session, 102, 103)
    assert [labels.scale(frame, BODY) for frame in range(100, 105)] == [
        ScaleLabel(1.2, MANUAL), ScaleLabel(1.2, CARRIED),
        ScaleLabel(1.15, MANUAL), ScaleLabel(1.15, CARRIED), None,
    ]


def test_s3_s4_body_and_head_carry_and_reset_are_independent():
    labels = PoseLabels()
    session = PoseScaleSession(labels)
    edit(session, 100, 1.2)
    edit(session, 100, .9, HEAD)
    advance(session, 100, 101)
    assert labels.scale(101, HEAD) == ScaleLabel(.9, CARRIED)
    assert labels.scale(101, BODY) == ScaleLabel(1.2, CARRIED)
    session.reset(104, BODY, displayed_frame=104)
    advance(session, 104, 105)
    assert labels.scale(104, BODY) == ScaleLabel(1.0, MANUAL)
    assert labels.scale(105, BODY) == ScaleLabel(1.0, CARRIED)
    assert labels.scale(105, HEAD) == ScaleLabel(.9, CARRIED)


def test_s5_manual_barrier_is_preserved_and_adopted_per_scale():
    labels = PoseLabels()
    session = PoseScaleSession(labels)
    edit(session, 102, 1.05)
    edit(session, 100, 1.2)
    edit(session, 100, .9, HEAD)
    advance(session, 100, 102)
    advance(session, 102, 103)
    assert labels.scale(102, BODY) == ScaleLabel(1.05, MANUAL)
    assert labels.scale(103, BODY) == ScaleLabel(1.05, CARRIED)
    assert labels.scale(103, HEAD) == ScaleLabel(.9, CARRIED)
    assert labels.scale(101, BODY) is None


def test_s6_existing_carried_value_can_be_replaced():
    labels = PoseLabels()
    session = PoseScaleSession(labels)
    edit(session, 100, 1.05)
    advance(session, 100, 101)
    edit(session, 100, 1.2)
    advance(session, 100, 101)
    assert labels.scale(101, BODY) == ScaleLabel(1.2, CARRIED)


def test_forward_play_carries_onto_each_painted_frame_only():
    labels = PoseLabels()
    session = PoseScaleSession(labels)
    edit(session, 100, 1.2)
    advance(session, 100, 101, Navigation.PLAY)
    advance(session, 101, 103, Navigation.PLAY)   # 102 was skipped by playback
    assert labels.scale(101, BODY) == ScaleLabel(1.2, CARRIED)
    assert labels.scale(102, BODY) is None
    assert labels.scale(103, BODY) == ScaleLabel(1.2, CARRIED)


@pytest.mark.parametrize("navigation", [
    Navigation.BACKWARD, Navigation.JUMP, Navigation.REFRESH,
])
def test_s8_view_only_navigation_neither_writes_nor_changes_carry(navigation):
    labels = PoseLabels()
    session = PoseScaleSession(labels)
    edit(session, 50, 1.05)
    edit(session, 100, 1.2)
    session.arrive(100, 50, navigation, displayed_frame=50)
    session.arrive(50, 51, navigation, displayed_frame=51)
    assert labels.scale(50, BODY) == ScaleLabel(1.05, MANUAL)
    assert labels.scale(51, BODY) is None
    assert session.carried_value(BODY) == 1.2


def test_forward_hold_writes_only_painted_destinations_never_skipped_frames():
    labels = PoseLabels()
    session = PoseScaleSession(labels)
    edit(session, 100, 1.2)
    advance(session, 100, 104, Navigation.FORWARD_HOLD)
    assert all(labels.scale(frame, BODY) is None for frame in range(101, 104))
    assert labels.scale(104, BODY) == ScaleLabel(1.2, CARRIED)


def test_jump_views_manual_value_but_next_forward_step_uses_unchanged_carry():
    labels = PoseLabels()
    session = PoseScaleSession(labels)
    edit(session, 50, .8)
    edit(session, 100, 1.2)
    advance(session, 100, 50, Navigation.JUMP)
    assert labels.scale(50, BODY) == ScaleLabel(.8, MANUAL)
    assert session.carried_value(BODY) == 1.2
    advance(session, 50, 51)
    assert labels.scale(51, BODY) == ScaleLabel(1.2, CARRIED)


def test_new_carry_session_is_inactive_and_does_not_infer_from_prior_labels():
    labels = PoseLabels()
    old_session = PoseScaleSession(labels)
    edit(old_session, 100, 1.2)
    advance(old_session, 100, 101)
    session = PoseScaleSession(labels)
    assert session.carried_value(BODY) is None
    advance(session, 100, 101)
    advance(session, 101, 102)
    assert labels.scale(101, BODY) == ScaleLabel(1.2, CARRIED)
    assert labels.scale(102, BODY) is None
    advance(session, 99, 100)
    assert session.carried_value(BODY) == 1.2


@pytest.mark.parametrize("quality", [0, .3, 1])
def test_quality_is_one_value_per_frame_independent_of_all_zone_events(quality):
    labels = PoseLabels()
    assert labels.quality(10) is None
    labels.set_quality(10, quality, displayed_frame=10)
    assert labels.event(10, JOINT) is None
    for zone in POSE_ZONES:
        for event in (ZoneEvent.ON, ZoneEvent.OFF, None):
            labels.set_event(10, zone, event, displayed_frame=10)
            assert labels.quality(10) == quality
    assert labels.quality(11) is None
    assert labels.scale(10, BODY) is None
    assert labels.scale(10, HEAD) is None
    labels.set_event(10, JOINT, ZoneEvent.ON, displayed_frame=10)
    labels.set_quality(10, None, displayed_frame=10)
    assert labels.event(10, JOINT) is ZoneEvent.ON
    assert labels.quality(10) is None


def test_frame_quality_replaces_only_that_frames_value():
    labels = PoseLabels()
    labels.set_quality(10, .7, displayed_frame=10)
    labels.set_quality(11, .2, displayed_frame=11)
    labels.set_quality(10, .4, displayed_frame=10)
    assert labels.quality(10) == .4
    assert labels.quality(11) == .2
    labels.set_quality(10, None, displayed_frame=10)
    assert labels.quality(10) is None
    assert labels.quality(11) == .2


def test_projection_uses_inclusive_on_exclusive_off_and_recomputes_on_deletion():
    labels = PoseLabels()
    for frame, event in [(1, ZoneEvent.OFF), (2, ZoneEvent.ON),
                         (3, ZoneEvent.ON), (5, ZoneEvent.OFF)]:
        labels.set_event(frame, JOINT, event, displayed_frame=frame)
    labels.set_event(4, "K", ZoneEvent.ON, displayed_frame=4)
    assert labels.active_zones(1) == frozenset()
    assert labels.active_zones(2) == frozenset({JOINT})
    assert labels.active_zones(4) == frozenset({"K"})
    assert labels.active_zones(5) == frozenset()
    labels.set_event(5, JOINT, None, displayed_frame=5)
    assert labels.active_zones(5) == frozenset({"K"})


def test_all_alternate_zone_ids_are_supported_independently():
    labels = PoseLabels()
    assert len(POSE_ZONES) == len(set(POSE_ZONES)) == 30
    for zone in POSE_ZONES:
        labels.set_event(0, zone, ZoneEvent.ON, displayed_frame=0)
    assert labels.active_zones(0) == frozenset(POSE_ZONES)


@pytest.mark.parametrize("displayed", [None, 99, True])
def test_unpainted_edits_and_forward_arrivals_preserve_labels_and_carry(displayed):
    labels = PoseLabels()
    session = PoseScaleSession(labels)
    edit(session, 90, 1.2)
    operations = [
        lambda: labels.set_event(100, JOINT, ZoneEvent.ON, displayed_frame=displayed),
        lambda: labels.set_quality(100, .3, displayed_frame=displayed),
        lambda: session.edit(100, BODY, 1.1, displayed_frame=displayed),
        lambda: session.reset(100, BODY, displayed_frame=displayed),
        lambda: session.arrive(90, 100, Navigation.FORWARD_STEP,
                               displayed_frame=displayed),
        lambda: labels.set_scale(100, HEAD, ScaleLabel(.9, MANUAL),
                                 displayed_frame=displayed),
    ]
    for operation in operations:
        with pytest.raises(ValueError):
            operation()
        assert session.carried_value(BODY) == 1.2
        assert labels.event(100, JOINT) is None
        assert labels.quality(100) is None
        assert labels.scale(100, BODY) is None
        assert labels.scale(100, HEAD) is None


@pytest.mark.parametrize("value", [-.01, 1.01, float("nan"), float("inf"),
                                    float("-inf"), True, "0.5"])
def test_invalid_quality_is_rejected_without_changing_previous_label(value):
    labels = PoseLabels()
    labels.set_quality(0, .2, displayed_frame=0)
    with pytest.raises(ValueError):
        labels.set_quality(0, value, displayed_frame=0)
    assert labels.quality(0) == .2


@pytest.mark.parametrize("value", [.49, 1.51, float("nan"), float("inf"),
                                    float("-inf"), True, "1.0"])
def test_invalid_scale_preserves_label_and_carry(value):
    labels = PoseLabels()
    session = PoseScaleSession(labels)
    edit(session, 0, 1.2)
    with pytest.raises(ValueError):
        edit(session, 0, value)
    assert labels.scale(0, BODY) == ScaleLabel(1.2, MANUAL)
    assert session.carried_value(BODY) == 1.2


@pytest.mark.parametrize("value", [.5, 1.5])
def test_scale_accepts_confirmed_range_endpoints(value):
    labels = PoseLabels()
    edit(PoseScaleSession(labels), 0, value)
    assert labels.scale(0, BODY).value == value


@pytest.mark.parametrize("frame", [-1, 1.5, True, "1"])
def test_invalid_frame_is_rejected(frame):
    with pytest.raises(ValueError):
        PoseLabels().set_quality(frame, .2, displayed_frame=frame)


def test_invalid_zone_event_scale_and_navigation_types_are_rejected():
    labels = PoseLabels()
    session = PoseScaleSession(labels)
    operations = [
        lambda: labels.set_event(0, "unknown", ZoneEvent.ON, displayed_frame=0),
        lambda: labels.set_event(0, JOINT, "ON", displayed_frame=0),
        lambda: session.edit(0, "body", 1.2, displayed_frame=0),
        lambda: labels.set_scale(0, BODY, 1.2, displayed_frame=0),
        lambda: session.arrive(0, 1, "forward_step", displayed_frame=1),
        lambda: session.arrive(1, 0, Navigation.FORWARD_STEP, displayed_frame=0),
        lambda: ScaleLabel(1.0, "manual"),
    ]
    for operation in operations:
        with pytest.raises(ValueError):
            operation()
    assert labels.scale(0, BODY) is None
    assert session.carried_value(BODY) is None


def test_read_scale_cannot_be_mutated_outside_painted_frame_guard():
    labels = PoseLabels()
    edit(PoseScaleSession(labels), 0, 1.2)
    with pytest.raises(FrozenInstanceError):
        labels.scale(0, BODY).value = 1.1
    assert labels.scale(0, BODY) == ScaleLabel(1.2, MANUAL)
