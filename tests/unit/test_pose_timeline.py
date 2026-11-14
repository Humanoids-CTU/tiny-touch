"""Pose timeline semantics, sparse updates and rendering without a Tk window."""
from types import SimpleNamespace

import pytest

from domain.pose import ZoneEvent, PoseLabels, PoseSnapshot, ScaleKind, ScaleLabel, ScaleSource
from domain.pose_timeline import PoseTimelineIndex
from gui import pose_timeline, timeline
from labeling_app import LabelingApp


def scale(labels, frame, value=1.0, kind=ScaleKind.BODY):
    labels.set_scale(frame, kind, ScaleLabel(value, ScaleSource.MANUAL), displayed_frame=frame)


def event(labels, frame, value, zone="I"):
    labels.set_event(frame, zone, value, displayed_frame=frame)


def test_numeric_points_preserve_neutral_zero_endpoints_and_unset_gaps():
    labels = PoseLabels()
    scale(labels, 1)
    scale(labels, 2, .5)
    scale(labels, 2, 1.5, ScaleKind.HEAD)
    labels.set_quality(1, 0, displayed_frame=1)
    labels.set_quality(2, 1, displayed_frame=2)
    index = PoseTimelineIndex(labels, {})
    assert index.column(0, 1).body is None
    assert index.column(1, 2).body == (1, 1)
    assert index.column(1, 2).head is None
    assert index.column(1, 2).quality == (0, 0)
    assert index.column(2, 3).head == (1.5, 1.5)
    assert index.column(1, 3).quality == (0, 1)
    assert index.column(3, 4).body is None
    assert index.column(3, 4).quality is None


def test_event_edits_revise_subsequent_intervals_and_keep_numeric_labels():
    labels = PoseLabels()
    event(labels, 2, ZoneEvent.ON)
    event(labels, 4, ZoneEvent.ON)
    event(labels, 7, ZoneEvent.OFF)
    event(labels, 1, ZoneEvent.OFF, "L")
    scale(labels, 4)
    labels.set_quality(4, .5, displayed_frame=4)
    index = PoseTimelineIndex(labels, {})
    assert [index.active_count(i) for i in range(9)] == [0, 0, 1, 1, 1, 1, 1, 0, 0]
    event(labels, 7, None)
    assert index.update(7, {})
    assert index.active_count(100) == 1
    event(labels, 4, ZoneEvent.OFF)
    index.update(4, {})
    assert index.active_count(4) == 0
    assert index.column(4, 5).offset
    assert index.column(4, 5).body == (1, 1)
    assert index.column(4, 5).quality == (.5, .5)
    assert not index.update(4, {})


def test_pixel_bins_preserve_numeric_extrema_both_edges_and_shared_marks():
    labels = PoseLabels()
    scale(labels, 2, .5)
    scale(labels, 5, 1.5)
    event(labels, 2, ZoneEvent.ON)
    event(labels, 3, ZoneEvent.OFF)
    frames = {5: {"Note": "late", "Params": {"Par1": "OFF"}},
              2: {"Note": "early", "Params": {"Par2": "ON"}}}
    index = PoseTimelineIndex(labels, frames)
    column = index.column(0, 10)
    assert column.body == (.5, 1.5)
    assert column.onset and column.offset
    assert column.parameter == "ON" and column.note_frame == 2
    index.update(2, {})
    assert index.column(0, 10).note_frame == 5
    assert index.column(0, 10).parameter == "OFF"


class Canvas:
    def __init__(self, width=203):
        self.width = width
        self.items = {}
        self.calls = []
        self.serial = 0

    def winfo_width(self):
        return self.width

    def winfo_height(self):
        return 128

    def delete(self, tag):
        self.calls.append(("delete", tag))
        for key, (_, _, kwargs) in list(self.items.items()):
            tags = kwargs.get("tags", ())
            if isinstance(tags, str):
                tags = (tags,)
            if tag == "all" or tag in tags:
                del self.items[key]

    def tag_raise(self, *args):
        pass

    def __getattr__(self, name):
        if name.startswith("create_"):
            def create(*args, **kwargs):
                self.serial += 1
                self.items[self.serial] = (name, args, kwargs)
                self.calls.append((name, args, kwargs))
                return self.serial
            return create
        raise AttributeError(name)


@pytest.fixture(autouse=True)
def no_tk_images(monkeypatch):
    monkeypatch.setattr(timeline, "update_playhead", lambda *args: 1)
    monkeypatch.setattr(timeline, "_round_track_corners", lambda *args: None)


def test_cached_playback_only_moves_playhead_without_label_reads(monkeypatch):
    labels = PoseLabels()
    index = PoseTimelineIndex(labels, {})
    canvas = Canvas()
    view = pose_timeline.PoseTimelineView(canvas)
    view.draw(index, 10000, 0)
    canvas.calls.clear()
    monkeypatch.setattr(index, "column", lambda *args: pytest.fail("reprojected during playback"))
    monkeypatch.setattr(labels, "snapshot", lambda: pytest.fail("snapshot during playback"))
    for frame in range(100):
        view.draw(index, 10000, frame)
    assert not canvas.calls


def test_scale_carry_redraws_one_pixel_bin_and_keeps_item_count_bounded(monkeypatch):
    labels = PoseLabels.from_snapshot(PoseSnapshot(scales=tuple(
        (i, ScaleKind.BODY, ScaleLabel(1.1, ScaleSource.CARRIED)) for i in range(20000))))
    index = PoseTimelineIndex(labels, {})
    canvas = Canvas()
    view = pose_timeline.PoseTimelineView(canvas)
    view.draw(index, 100000, 0)
    monkeypatch.setattr(labels, "snapshot", lambda: pytest.fail("snapshot on dirty update"))
    real_column = index.column
    reads = []
    def column(*args):
        reads.append(args)
        return real_column(*args)
    monkeypatch.setattr(index, "column", column)
    for frame in range(20000, 20200):
        scale(labels, frame, 1.2)
        view.changed(frame, index.update(frame, {}))
        canvas.calls.clear()
        view.draw(index, 100000, frame)
        assert ("delete", "all") not in canvas.calls
        assert len(canvas.calls) <= 8
        assert len(canvas.items) < canvas.width * 8
    assert len(reads) == 200


def test_zone_edit_reprojects_classic_overview_intervals():
    labels = PoseLabels()
    event(labels, 2, ZoneEvent.ON)
    event(labels, 800, ZoneEvent.OFF)
    index = PoseTimelineIndex(labels, {})
    assert index.overview().intervals == ((2, 800),)
    canvas = Canvas()
    view = pose_timeline.PoseTimelineView(canvas)
    view.draw(index, 1000, 0)
    event(labels, 800, None)
    view.changed(800, index.update(800, {}))
    view.draw(index, 1000, 0)
    assert index.overview().intervals == ()  # Touch only fills closed intervals.


def test_detail_shows_notes_global_parameters_and_deletes_old_note_hit_target():
    labels = PoseLabels()
    scale(labels, 1)
    frames = {1: {"Note": "note", "Params": {"Par1": "ON"}}}
    index = PoseTimelineIndex(labels, frames)
    canvas = Canvas()
    view = pose_timeline.PoseTimelineView(canvas)
    view.draw(index, 1000, 1, offset=0, count=100)
    assert any("note_frame:1" in value[2].get("tags", ()) for value in canvas.items.values())
    assert any(value[2].get("fill") == pose_timeline.BODY_COLOR and value[0] == "create_rectangle"
               for value in canvas.items.values())
    frames[1] = {}
    view.changed(1, index.update(1, {}))
    view.draw(index, 1000, 1, offset=0, count=100)
    assert not any("note_frame:1" in value[2].get("tags", ()) for value in canvas.items.values())


def app_stub():
    app = SimpleNamespace(video=SimpleNamespace(total_frames=1000, current_frame=0,
                            current_frame_zone=0, number_frames_in_zone=100, frames={}),
                          timeline_canvas=Canvas(), timeline2_canvas=Canvas(),
                          pose_session=SimpleNamespace(labels=PoseLabels()), _pose_panel=object())
    for name in ("_get_pose_timeline_index", "_pose_annotation_changed", "draw_timeline", "draw_timeline2"):
        setattr(app, name, lambda *args, _name=name: getattr(LabelingApp, _name)(app, *args))
    return app


def test_controller_dispatches_pose_label_and_shared_edits_and_new_session():
    app = app_stub()
    app.draw_timeline()
    app.draw_timeline2()
    old_index = app._pose_timeline_index
    scale(app.pose_session.labels, 0, 1.2)
    app._pose_annotation_changed(0)
    assert app._pose_timeline_index.column(0, 1).body == (1.2, 1.2)
    app.video.frames[0] = {"Note": "new"}
    app._refresh_after_annotation_edit = lambda: None
    LabelingApp.mark_bundle_changed(app, 0)
    assert app._pose_timeline_index.column(0, 1).note_frame == 0
    app.pose_session = SimpleNamespace(labels=PoseLabels())
    app.video.frames = {}
    app.draw_timeline2()
    assert app._pose_timeline_index is not old_index
    assert app._pose_timeline_index.column(0, 1).body is None


def test_detail_zone_changes_and_resize_rebuild_but_jump_keeps_annotations():
    app = app_stub()
    scale(app.pose_session.labels, 1)
    before = app.pose_session.labels.snapshot()
    app.draw_timeline()
    app.timeline_canvas.calls.clear()
    app.video.current_frame = 500
    app.draw_timeline()
    assert ("delete", "all") in app.timeline_canvas.calls
    assert app.video.current_frame_zone == 5
    app.timeline_canvas.calls.clear()
    app.timeline_canvas.width = 400
    app.draw_timeline()
    assert ("delete", "all") in app.timeline_canvas.calls
    assert app.pose_session.labels.snapshot() == before


def test_single_frame_video_uses_valid_overview_geometry(monkeypatch):
    # Exercise real shared geometry while replacing only its image operation.
    positions = []
    monkeypatch.setattr(timeline, "update_playhead", lambda _c, _i, x, *_args: positions.append(x))
    app = app_stub()
    app.video.total_frames = 0
    scale(app.pose_session.labels, 0)
    app.draw_timeline()
    app.draw_timeline2()
    assert len(positions) == 2 and all(position >= 1 for position in positions)
    assert any(value[2].get("fill") == pose_timeline.BODY_COLOR and value[0] == "create_rectangle"
               for value in app.timeline2_canvas.items.values())


def test_event_edit_never_extends_active_strip_into_unavailable_detail_frames():
    labels = PoseLabels()
    index = PoseTimelineIndex(labels, {})
    canvas = Canvas()
    view = pose_timeline.PoseTimelineView(canvas)
    view.draw(index, 12, 10, offset=10, count=100)
    event(labels, 11, ZoneEvent.ON)
    view.changed(11, index.update(11, {}))
    view.draw(index, 12, 11, offset=10, count=100)
    projection = index.detail(12, 10, 100)
    assert projection.cells[:4] == ("empty", "on", "during", "unavailable")
    assert all(cell == "unavailable" for cell in projection.cells[3:])


def test_classic_onset_offset_shading_and_scale_only_captions():
    labels = PoseLabels()
    event(labels, 1, ZoneEvent.ON)
    event(labels, 3, ZoneEvent.OFF)
    labels.set_quality(2, .7, displayed_frame=2)
    canvas = Canvas()
    view = pose_timeline.PoseTimelineView(canvas)
    view.draw(PoseTimelineIndex(labels, {}), 4, 2, count=5)
    captions = [kw["text"] for _, _, kw in canvas.items.values() if "text" in kw]
    assert captions == []
    cells = [kw["fill"] for kind, _, kw in canvas.items.values()
             if kind == "create_rectangle" and kw.get("fill")]
    assert cells == [pose_timeline.theme.TL_EMPTY, pose_timeline.theme.TL_ON,
                     pose_timeline.theme.TL_DURING, pose_timeline.theme.TL_OFF,
                     pose_timeline.theme.TL_EMPTY]


def test_head_scale_line_is_above_body():
    labels = PoseLabels()
    scale(labels, 1, 1, ScaleKind.BODY)
    scale(labels, 1, 1, ScaleKind.HEAD)
    canvas = Canvas()
    pose_timeline.PoseTimelineView(canvas).draw(PoseTimelineIndex(labels, {}), 4, 1, count=5)
    heights = {kw["fill"]: args[1] for kind, args, kw in canvas.items.values()
               if kind == "create_rectangle" and kw.get("fill") in (pose_timeline.HEAD_COLOR, pose_timeline.BODY_COLOR)}
    assert heights[pose_timeline.HEAD_COLOR] < heights[pose_timeline.BODY_COLOR]


def test_offset_in_another_zone_ends_global_pose_interval():
    labels = PoseLabels()
    event(labels, 2, ZoneEvent.ON, "I")
    event(labels, 5, ZoneEvent.OFF, "A")
    index = PoseTimelineIndex(labels, {})
    assert index.detail(9, 0, 10).cells[6:] == ("empty",) * 4
    assert index.overview().intervals == ((2, 5),)
    assert labels.active_zones(6) == frozenset()
