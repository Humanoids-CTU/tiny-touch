"""Cross-mode contract: Pose is one channel, not one channel per zone."""
from itertools import product

import pytest

from domain.annotation_channel import AnnotationChannel
from domain.pose import PoseLabels, ZoneEvent
from domain.pose_timeline import PoseTimelineIndex
from domain.touch_timeline import detail_timeline, overview_timeline
from service_layer.annotation_service import add_click, remove_nearest_click


def test_touch_pose_parity_for_all_short_boundary_sequences():
    for sequence in product((None, "ON", "OFF"), repeat=5):
        frames, labels = {}, PoseLabels()
        for frame, event in enumerate(sequence):
            if event is not None:
                zone = "A" if frame % 2 else "B"
                add_click(frames, frame, "RH", 10, 20, event, [zone])
                labels.set_event(frame, zone, ZoneEvent(event), displayed_frame=frame)
        index = PoseTimelineIndex(labels, {})
        touch = overview_timeline(frames, "RH")
        pose = index.overview()
        assert (pose.intervals, pose.onsets, pose.offsets) == (touch.intervals, touch.onsets, touch.offsets)
        for offset in range(6):
            prefix = detail_timeline(frames, "RH", 4, 0, offset)
            touch = detail_timeline(frames, "RH", 4, offset, 3, prefix.active)
            pose = index.detail(4, offset, 3)
            assert (pose.cells, pose.active, pose.carry) == (touch.cells, touch.active, touch.carry)


@pytest.mark.parametrize("first,last", [("ON", "OFF"), ("OFF", "ON")])
def test_latest_click_sets_whole_frame_boundary_and_deletion_keeps_it(first, last):
    frames, labels = {}, PoseLabels()
    for x, zone, event in ((10, "A", first), (30, "B", last)):
        add_click(frames, 2, "RH", x, 20, event, [zone])
        labels.set_event(2, zone, ZoneEvent(event), displayed_frame=2)
    assert labels.event(2, "A").value == frames[2]["RH"]["Onset"] == last
    assert labels.event(2, "B").value == last
    remove_nearest_click(frames, 2, "RH", 30, 20, 2)
    labels.set_event(2, "B", None, displayed_frame=2)
    assert labels.event(2, "A").value == frames[2]["RH"]["Onset"] == last
    assert PoseTimelineIndex(labels, {}).detail(4, 0, 5).cells == detail_timeline(frames, "RH", 4, 0, 5).cells


def test_editing_past_boundary_recomputes_single_channel_without_losing_other_labels():
    labels = PoseLabels()
    labels.set_quality(3, .6, displayed_frame=3)
    labels.set_event(1, "A", ZoneEvent.ON, displayed_frame=1)
    labels.set_event(3, "B", ZoneEvent.OFF, displayed_frame=3)
    index = PoseTimelineIndex(labels, {})
    assert index.channel.latest(4) == (3, "OFF")
    labels.set_event(3, "B", None, displayed_frame=3)
    index.update(3, {})
    assert index.active_zones(4) == frozenset({"A"})
    assert index.overview().intervals == ()
    assert labels.quality(3) == .6


def test_sparse_channel_handles_large_gaps_and_replacement():
    channel = AnnotationChannel(((2, "ON"), (10000000, "OFF")))
    assert channel.active_before(10000000)
    assert not channel.active_before(10000001)
    channel.set(10000000, None)
    assert channel.latest(20000000) == (2, "ON")
    channel.set(2, "OFF")
    assert channel.overview((), ()).intervals == ()
