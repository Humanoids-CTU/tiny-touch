"""Timeline projections and canvas behavior without a Tk window."""
from copy import deepcopy
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from gui.timeline_geometry import TimelineGeometry, timeline_click_frame
from domain.touch_timeline import detail_timeline, overview_timeline
from gui import theme, timeline
from labeling_app import LabelingApp
from video_model import Video


class Canvas:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("create_") or name in ("delete", "coords", "tag_raise"):
            def record(*args, **kwargs):
                self.calls.append((name, args, kwargs))
                return len(self.calls)
            return record
        raise AttributeError(name)

    def winfo_width(self):
        return 403

    def winfo_height(self):
        return 40


def test_detail_coordinates_events_unavailable_and_final_edge_carry():
    frames = {0: {"LH": {"X": [1], "Onset": "ON"}},
              2: {"LH": {"X": [None], "Onset": "OFF"}},
              3: {"LH": {"X": [2], "Onset": "OFF"}}}
    before = deepcopy(frames)
    projection = detail_timeline(frames, "LH", 4, 0, 6)
    assert projection.cells == ("on", "during", "during", "off", "empty", "unavailable")
    assert frames == before
    edge = detail_timeline(frames, "LH", 4, 0, 1)
    assert edge.active is True and edge.carry is False
    assert detail_timeline(frames, "LH", 4, 1, 1, True).carry is True


def test_overview_repeated_on_off_and_open_touches_are_distinct_from_detail():
    frames = {9: {"LH": {"Onset": "ON"}, "Note": "late"},
              1: {"LH": {"Onset": "OFF"}, "Note": "early"},
              2: {"LH": {"Onset": "ON"}}, 3: {"LH": {"Onset": "ON"}},
              7: {"LH": {"Onset": "OFF"}}, 8: {"RH": {"Onset": "ON"}}}
    before = deepcopy(frames)
    projection = overview_timeline(frames, "LH")
    assert projection.onsets == (2, 3, 9)
    assert projection.offsets == (1, 7)
    assert projection.intervals == ((2, 7),)
    assert projection.notes == (9, 1)
    assert detail_timeline(frames, "LH", 10, 0, 10).cells == ("empty",) * 10
    assert frames == before


def test_parameters_notes_and_selected_limb_projection():
    frames = {0: {"Params": {"Par1": "OFF", "Par2": "ON"}, "Note": "  ",
                  "LH": {"LimbParams": {"Par1": "OFF", "Par3": "ON"}},
                  "RH": {"LimbParams": {"Par1": "ON"}}}, 1: {"Note": "a note"}}
    marks = overview_timeline(frames, "LH").marks
    assert marks[0].parameter == "ON"
    assert marks[0].limb_parameters == ("OFF", None, "ON")
    assert not marks[0].note and marks[1].note


def test_detail_canvas_preserves_final_ticks_grid_and_notes(monkeypatch):
    monkeypatch.setattr(timeline, "_round_track_corners", lambda *args: None)
    canvas = Canvas()
    frames = {0: {"Note": "note", "LH": {"LimbParams": {"Par1": "ON"}}}}
    timeline.draw_touch_detail(canvas, TimelineGeometry(403, 40), detail_timeline(frames, "LH", 1, 0, 1), "during")
    ticks = [call for call in canvas.calls if call[0] == "create_line"]
    assert len(ticks) == 2  # original duplicate final-cell limb mark
    assert all(call[2]["dash"] == theme.TL_PARAM_MARK_DASH for call in ticks)
    note = canvas.calls[-1]
    assert note[0] == "create_polygon"
    assert note[2]["tags"] == ("note_marker", "note_frame:0")


def test_overview_draws_closed_fills_before_ticks_and_notes(monkeypatch):
    monkeypatch.setattr(timeline, "_round_track_corners", lambda *args: None)
    canvas = Canvas()
    frames = {0: {"LH": {"Onset": "ON"}, "Params": {"Par1": "OFF"}},
              50: {"LH": {"Onset": "OFF"}, "Note": "note"},
              70: {"LH": {"Onset": "ON"}}}
    timeline.draw_touch_overview(canvas, TimelineGeometry(403, 40), overview_timeline(frames, "LH"), 100)
    rectangles = [call for call in canvas.calls if call[0] == "create_rectangle"]
    assert len(rectangles) == 2  # background plus one closed interval
    assert rectangles[1][1] == (4, 2, 198, 37)
    assert rectangles[1][2]["fill"] == theme.TL_DURING
    assert canvas.calls[-1][2]["tags"] == ("note_marker", "note_frame:50")


def test_geometry_retains_insets_centers_and_canvas_wide_seek():
    g = TimelineGeometry(403, 40)
    assert (g.left, g.right, g.top, g.bottom) == (1, 401, 1, 38)
    assert g.position(0, 100, centered=True) == 3
    assert g.marker_position(0, 100, centered=True) == 5
    assert g.marker_position(100, 100) == 397
    assert timeline_click_frame(403, 403, 100) == 100
    assert timeline_click_frame(201.5, 403, 100, 200) == 250


def app_stub():
    app = SimpleNamespace(
        video=Video("test", 1000), timeline_canvas=Canvas(), timeline2_canvas=Canvas(),
        option_var_1=SimpleNamespace(get=lambda: "LH"), color_during="during",
        _assert_ui_thread=lambda: None, perf=SimpleNamespace(time=lambda name: nullcontext()),
    )
    app._detail_timeline = timeline.TouchTimelineView(app.timeline_canvas)
    app._overview_timeline = timeline.TouchTimelineView(app.timeline2_canvas)
    return app


def test_cached_draw_moves_playhead_without_reprojecting(monkeypatch):
    monkeypatch.setattr(timeline, "_round_track_corners", lambda *args: None)
    monkeypatch.setattr(timeline, "update_playhead", lambda canvas, item, *args: item or 1)
    app = app_stub()
    LabelingApp.draw_timeline(app)
    LabelingApp.draw_timeline2(app)
    initial = (len(app.timeline_canvas.calls), len(app.timeline2_canvas.calls))
    app.video.current_frame = 10
    LabelingApp.draw_timeline(app)
    LabelingApp.draw_timeline2(app)
    assert initial == (len(app.timeline_canvas.calls), len(app.timeline2_canvas.calls))
    app.video.current_frame = 100
    LabelingApp.draw_timeline(app)
    assert len(app.timeline_canvas.calls) > initial[0]


def test_cached_frame_change_moves_both_playheads_over_existing_content(monkeypatch):
    monkeypatch.setattr(timeline, "_round_track_corners", lambda *args: None)
    photo = SimpleNamespace(width=lambda: 10)
    monkeypatch.setattr(timeline, "_playhead_photo", lambda *args: photo)
    app = app_stub()
    for canvas in (app.timeline_canvas, app.timeline2_canvas):
        canvas.itemcget = lambda *args: str(photo)

    LabelingApp.draw_timeline(app)
    LabelingApp.draw_timeline2(app)
    for canvas in (app.timeline_canvas, app.timeline2_canvas):
        canvas.calls.clear()

    app.video.current_frame = 20
    LabelingApp.draw_timeline(app)
    LabelingApp.draw_timeline2(app)

    for canvas, expected_left in ((app.timeline_canvas, 78), (app.timeline2_canvas, 4)):
        assert [call[0] for call in canvas.calls] == ["coords", "tag_raise"]
        assert canvas.calls[0][1][1:] == (expected_left, 1)
        assert canvas.calls[1][1] == (canvas.calls[0][1][0],)


def test_edit_invalidates_both_views_and_reset_discards_cached_content(monkeypatch):
    monkeypatch.setattr(timeline, "_round_track_corners", lambda *args: None)
    monkeypatch.setattr(timeline, "update_playhead", lambda canvas, item, *args: item or 1)
    app = app_stub()
    app.video.frames[0] = {}
    app._refresh_after_annotation_edit = lambda: None
    LabelingApp.draw_timeline(app)
    LabelingApp.draw_timeline2(app)
    app.timeline_canvas.calls.clear()
    app.timeline2_canvas.calls.clear()
    app.video.frames[0]["Note"] = "new note"
    LabelingApp.mark_bundle_changed(app, 0)
    LabelingApp.draw_timeline(app)
    LabelingApp.draw_timeline2(app)
    for canvas in (app.timeline_canvas, app.timeline2_canvas):
        assert any(call[2].get("tags") == ("note_marker", "note_frame:0") for call in canvas.calls)
    app._detail_timeline.reset()
    app.timeline_canvas.calls.clear()
    LabelingApp.draw_timeline(app)
    assert app.timeline_canvas.calls[0] == ("delete", ("all",), {})


def test_limb_and_size_changes_rebuild_cached_views(monkeypatch):
    monkeypatch.setattr(timeline, "_round_track_corners", lambda *args: None)
    monkeypatch.setattr(timeline, "update_playhead", lambda canvas, item, *args: item or 1)
    app = app_stub()
    for change in (lambda: None,
                   lambda: setattr(app.option_var_1, "get", lambda: "RH"),
                   lambda: setattr(app.timeline2_canvas, "winfo_width", lambda: 500)):
        change()
        app.timeline2_canvas.calls.clear()
        LabelingApp.draw_timeline2(app)
        assert app.timeline2_canvas.calls[0] == ("delete", ("all",), {})


@pytest.mark.parametrize("method", ["on_timeline_click", "on_timeline2_click"])
def test_note_navigation_precedes_approximate_seek(method):
    calls = []
    app = app_stub()
    app.stop_video = lambda: calls.append("stop")
    app.display_first_frame = lambda: calls.append("display")
    app.draw_timeline = lambda: calls.append("detail")
    app.draw_timeline2 = lambda: calls.append("overview")
    app.focus_set = lambda: calls.append("focus")
    app._open_timeline_note = lambda event: LabelingApp._open_timeline_note(app, event)
    event = SimpleNamespace(x=0, widget=SimpleNamespace(gettags=lambda tag: ("note_marker", "note_frame:237")))
    assert getattr(LabelingApp, method)(app, event) == "break"
    assert app.video.current_frame == 237 and app.video.current_frame_zone == 2
    assert calls == ["stop", "display", "detail", "overview", "focus"]


@pytest.mark.parametrize("method, expected", [("on_timeline_click", 250), ("on_timeline2_click", 500)])
def test_click_navigation_pauses_paints_and_refreshes_both_views(method, expected):
    app = app_stub()
    calls = []
    app.video.current_frame_zone = 2
    app._open_timeline_note = lambda event: False
    app.stop_video = lambda: calls.append("stop")
    app.display_first_frame = lambda: calls.append("display")
    app.draw_timeline = lambda: calls.append("detail")
    app.draw_timeline2 = lambda: calls.append("overview")
    getattr(LabelingApp, method)(app, SimpleNamespace(x=201.5))
    assert app.video.current_frame == expected
    assert calls == ["stop", "display", "detail", "overview"]
