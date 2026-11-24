"""Pose controls and deferred arrivals without opening a Tk window."""
from types import SimpleNamespace

import pytest

from domain.pose import ZoneEvent, Navigation, PoseLabels, PoseScaleSession, ScaleKind, ScaleSource
from domain.pose_geometry import POSE_SIZE
from adapters.pose_diagram import zone_positions, hit_zone
from domain.templates import get_template, TEMPLATES, validate_template
from gui.pose_panel import PosePanel
from labeling_app import LabelingApp
from adapters.pose_diagram import render_pose_diagram


def panel_at(frame=10):
    labels = PoseLabels()
    session = SimpleNamespace(labels=labels, scales=PoseScaleSession(labels))
    app = SimpleNamespace(annotation_type="Pose", pose_session=session,
                          video=SimpleNamespace(current_frame=frame), displayed_frame=frame,
                          frame_paint_listeners=[], diagram_scale=.7, state_repo=None,
                          play=False, _play_ui_pending=False)
    app._lock_before_annotation = lambda **kw: LabelingApp._lock_before_annotation(app, **kw)
    app.stop_video = lambda: setattr(app, "play", False)
    panel = PosePanel(app)
    panel.draw = lambda: None
    changes = []
    app._pose_annotation_changed = changes.append
    return panel, app, labels, changes


def arrive(panel, app, destination, navigation=Navigation.FORWARD_STEP):
    panel.request_navigation(app.video.current_frame, destination, navigation)
    app.video.current_frame = destination
    app.displayed_frame = destination
    panel.painted(destination, (640, 480))


def test_scale_controls_reset_independently_and_quality_is_global():
    panel, app, labels, changes = panel_at()
    panel.edit_scale(ScaleKind.BODY, "1.2")
    panel.edit_scale(ScaleKind.HEAD, ".9")
    panel.edit_quality("0")
    panel.edit_scale(ScaleKind.BODY, "1")
    assert labels.scale(10, ScaleKind.BODY).value == 1
    assert labels.scale(10, ScaleKind.HEAD).value == .9
    assert labels.quality(10) == 0
    assert labels.snapshot().events == ()
    panel.edit_quality("1")
    assert labels.quality(10) == 1
    panel.edit_quality(None)
    assert labels.quality(10) is None
    assert changes == [10] * 6


def test_zone_hits_follow_scaled_drawing_and_delete_preserves_quality():
    panel, app, labels, _ = panel_at()
    panel.edit_scale(ScaleKind.BODY, 1.5)
    panel.edit_quality(.6)
    x, y = zone_positions(1.5)["A"]
    panel.click(x * .7, y * .7, ZoneEvent.ON)
    assert labels.event(10, "A") is ZoneEvent.ON
    panel.click(x * .7, y * .7, ZoneEvent.OFF)
    assert labels.event(10, "A") is ZoneEvent.OFF
    panel.click(x * .7, y * .7, None)
    assert labels.event(10, "A") is None
    assert labels.quality(10) == .6
    panel.click(0, 0, ZoneEvent.ON)
    assert not labels.snapshot().events


def test_manual_edits_reject_an_unpainted_destination():
    panel, app, labels, changes = panel_at()
    app.displayed_frame = 9
    panel.edit_scale(ScaleKind.BODY, 1.2)
    panel.edit_quality(.5)
    x, y = zone_positions()["I"]
    panel.click(x * .7, y * .7, ZoneEvent.ON)
    assert labels.snapshot().scales == labels.snapshot().quality == labels.snapshot().events == ()
    assert changes == []


def test_carry_waits_for_paint_and_never_fills_skipped_frames():
    panel, app, labels, changes = panel_at()
    panel.edit_scale(ScaleKind.BODY, 1.2)
    panel.request_navigation(10, 13, Navigation.FORWARD_HOLD)
    app.video.current_frame = 13
    assert labels.scale(13, ScaleKind.BODY) is None
    app.play = True
    app.displayed_frame = 13
    panel.painted(13, (1, 1))
    assert app.play  # carry must not stop arrow holding
    assert labels.scale(13, ScaleKind.BODY).source is ScaleSource.CARRIED
    assert labels.scale(11, ScaleKind.BODY) is None
    assert labels.scale(12, ScaleKind.BODY) is None
    assert changes == [10, 13]
    panel.painted(13, (1, 1))
    assert changes == [10, 13]


@pytest.mark.parametrize("navigation", [Navigation.BACKWARD, Navigation.JUMP, Navigation.REFRESH])
def test_view_only_navigation_and_refresh_never_change_carry(navigation):
    panel, app, labels, changes = panel_at()
    panel.edit_scale(ScaleKind.BODY, 1.2)
    labels.set_scale(11, ScaleKind.BODY,
                     type(labels.scale(10, ScaleKind.BODY))(.8, ScaleSource.MANUAL), displayed_frame=11)
    arrive(panel, app, 11, navigation)
    panel.refresh()
    assert panel.display_scales() == (.8, 1)
    assert panel.session.scales.carried_value(ScaleKind.BODY) == 1.2
    arrive(panel, app, 12)
    assert labels.scale(12, ScaleKind.BODY).value == 1.2
    assert changes == [10, 12]


def test_manual_barrier_adopted_and_identical_carry_does_not_invalidate():
    panel, app, labels, changes = panel_at()
    panel.edit_scale(ScaleKind.BODY, 1.2)
    panel.session.scales.edit(11, ScaleKind.BODY, .8, displayed_frame=11)
    arrive(panel, app, 11)
    arrive(panel, app, 12)
    assert labels.scale(12, ScaleKind.BODY).value == .8
    arrive(panel, app, 11, Navigation.JUMP)
    arrive(panel, app, 12)
    assert changes == [10, 12]


@pytest.mark.parametrize("stale", ["session", "video", "requested", "displayed"])
def test_stale_paint_cannot_apply_pending_carry(stale):
    panel, app, labels, changes = panel_at()
    panel.edit_scale(ScaleKind.BODY, 1.2)
    panel.request_navigation(10, 11, Navigation.FORWARD_STEP)
    app.video.current_frame = app.displayed_frame = 11
    if stale == "session":
        app.pose_session = object()
    elif stale == "video":
        app.video = SimpleNamespace(current_frame=11)
    elif stale == "requested":
        app.video.current_frame = 12
    else:
        app.displayed_frame = 10
    panel.painted(11, (1, 1))
    assert labels.scale(11, ScaleKind.BODY) is None
    assert changes == [10]


def test_replaced_navigation_and_detach_cancel_pending_arrival():
    panel, app, labels, _ = panel_at()
    panel.edit_scale(ScaleKind.BODY, 1.2)
    panel.request_navigation(10, 11, Navigation.FORWARD_STEP)
    panel.request_navigation(10, 11, Navigation.JUMP)
    app.video.current_frame = app.displayed_frame = 11
    panel.painted(11, (1, 1))
    assert labels.scale(11, ScaleKind.BODY) is None
    panel.detach()
    assert app.frame_paint_listeners == []


def test_pose_geometry_uses_alternate_masks_and_scale_transforms():
    assert get_template("alternate").native_size == (450, 696)
    assert "pose" not in TEMPLATES
    with pytest.raises(ValueError):
        validate_template("pose")
    for body in (.5, 1, 1.5):
        for head in (.5, 1, 1.5):
            positions = zone_positions(body, head)
            assert len(positions) == 30
            for zone, (x, y) in positions.items():
                assert 0 < x < POSE_SIZE[0] and 0 < y < POSE_SIZE[1]
                assert hit_zone(x, y, body, head) == zone
    assert zone_positions(1, .5) == zone_positions(1.5, 1.5)
    assert render_pose_diagram(1.5, .5).size == POSE_SIZE


def test_refresh_synchronizes_unset_and_zero_without_writing_labels():
    panel, app, labels, changes = panel_at()
    values, readouts = {}, {}
    for key in (*ScaleKind, "quality"):
        panel.values[key] = SimpleNamespace(set=lambda value, k=key: values.update({k: value}),
                                            get=lambda k=key: values.get(k))
        panel.readouts[key] = SimpleNamespace(config=lambda text, k=key: readouts.update({k: text}))
    panel.refresh()
    assert "unset" in readouts["quality"]
    assert "unset" in readouts[ScaleKind.BODY]
    assert not changes and not labels.snapshot().quality and not labels.snapshot().scales
    panel.edit_quality(.003)
    panel.refresh()
    assert labels.quality(10) == 0
    assert readouts["quality"] == "Quality · 0.00"
    panel.syncing = True
    panel.edit_quality(.9)
    panel.edit_scale(ScaleKind.BODY, 1.2)
    assert labels.quality(10) == 0 and labels.scale(10, ScaleKind.BODY) is None


@pytest.mark.parametrize("held, expected", [(False, 1.2), (True, 1.2)])
def test_controller_play_and_forward_arrow_hold_both_carry(held, expected):
    panel, app, labels, _ = panel_at()
    app._pose_panel = panel
    panel.edit_scale(ScaleKind.BODY, 1.2)
    app._hold_play_active = held
    def display(**kwargs):
        app.displayed_frame = app.video.current_frame
        panel.painted(app.displayed_frame, (1, 1))
    app.display_first_frame = display
    app._refresh_playback_ui = lambda: None
    LabelingApp._apply_play_advance(app, 11, 1)
    label = labels.scale(11, ScaleKind.BODY)
    assert (label.value if label else None) == expected


@pytest.mark.parametrize("intent, expected", [(None, 1.2), (Navigation.JUMP, None)])
def test_controller_explicit_one_frame_jump_does_not_carry(intent, expected):
    panel, app, labels, _ = panel_at()
    app._pose_panel = panel
    panel.edit_scale(ScaleKind.BODY, 1.2)
    app.video.total_frames = 20
    app.frame_buffer = {11: object()}
    app.draw_timeline = app.draw_timeline2 = lambda: None
    def display():
        app.displayed_frame = app.video.current_frame
        panel.painted(app.displayed_frame, (1, 1))
    app.display_first_frame = display
    LabelingApp.next_frame(app, 1, navigation=intent)
    label = labels.scale(11, ScaleKind.BODY)
    assert (label.value if label else None) == expected


def test_neutral_pose_preserves_exact_alternate_artwork():
    from PIL import Image, ImageChops
    from resource_utils import asset_path
    from domain.pose_geometry import ORIGINAL_OFFSET
    with Image.open(asset_path(get_template("alternate").diagram)) as original:
        x, y = ORIGINAL_OFFSET
        cropped = render_pose_diagram().crop((x, y, x + original.width, y + original.height))
        assert ImageChops.difference(cropped, original.convert("RGB")).getbbox() is None


def test_space_on_pose_control_toggles_play_without_activating_control():
    panel, app, _, _ = panel_at()
    calls = []
    app.toggle_play = lambda event: calls.append(event)
    bindings = {}
    widget = SimpleNamespace(bind=lambda key, handler: bindings.update({key: handler}))
    panel._bind_playback(widget)
    event = object()
    assert bindings["<space>"](event) == "break"
    assert calls == [event]


def test_pose_click_flashes_the_clicked_zone():
    panel, app, labels, _ = panel_at()
    flashes = []
    app._highlighter = SimpleNamespace(flash=lambda *args: flashes.append(args))
    x, y = zone_positions()["A"]
    panel.click(x * app.diagram_scale, y * app.diagram_scale, ZoneEvent.ON)
    assert flashes == [("A", __import__("gui.theme", fromlist=["DOT_ONSET"]).DOT_ONSET)]
    assert labels.event(10, "A") is ZoneEvent.ON


def test_back_head_does_not_resize_with_head_scale():
    from PIL import ImageChops
    from domain.pose_geometry import ORIGINAL_OFFSET
    x, y = ORIGINAL_OFFSET
    # The back-head region beyond the maximum front-head extent stays unchanged.
    crop = (x + 390, y + 20, x + 440, y + 220)
    assert ImageChops.difference(render_pose_diagram(1, .5).crop(crop),
                                render_pose_diagram(1, 1.2).crop(crop)).getbbox() is None
