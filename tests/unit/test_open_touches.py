"""Open-touch detection before analysis and the Analysis-button decision.

`find_open_touches` must agree with the analysis episode builder about what
counts as open; the handler must jump, proceed or stop exactly as the (stubbed)
dialog says, without touching the data.
"""

from types import SimpleNamespace

import labeling_app
from domain.touch import OpenTouch, find_open_touches
from gui.open_touches_dialog import ANALYZE_ANYWAY, GO_TO_ONSET, describe_open_touch
from labeling_app import LabelingApp

LIMBS = ["LH", "RH", "LL", "RL"]


def _rec(onset, x=None, zones=None):
    rec = {"X": [], "Y": [], "Onset": onset, "Bodypart": "RH", "Zones": [], "Touch": None}
    if x is not None:
        rec["X"], rec["Y"], rec["Zones"] = [x], [x + 1], [zones or ["A"]]
    return rec


def test_no_annotations_means_nothing_open():
    assert find_open_touches({}, LIMBS) == []
    assert find_open_touches({3: {"RH": _rec("OFF", 1)}}, LIMBS) == []  # stray OFF


def test_closed_touch_is_not_reported():
    frames = {2: {"RH": _rec("ON", 1)}, 9: {"RH": _rec("OFF", 2)}}
    assert find_open_touches(frames, LIMBS) == []


def test_open_touch_reports_onset_and_last_click():
    frames = {
        2: {"RH": _rec("ON", 1)},
        5: {"RH": _rec("", 4, ["B"])},          # mid click
        7: {"RH": _rec("ON")},                  # extra onset without a point
        8: {"LH": _rec("ON", 3)},
    }
    assert find_open_touches(frames, LIMBS) == [
        OpenTouch("RH", 2, 5, extra_onsets=1),
        OpenTouch("LH", 8, 8),
    ]


def test_reopened_touch_after_close_is_reported_once():
    frames = {1: {"RH": _rec("ON", 1)}, 2: {"RH": _rec("OFF", 1)}, 6: {"RH": _rec("ON", 2)}}
    assert find_open_touches(frames, LIMBS) == [OpenTouch("RH", 6, 6)]


def test_description_is_channel_and_frame_only():
    assert describe_open_touch(OpenTouch("RH", 120, 125), "Right hand") == "Right hand: onset at frame 120"


# --- the Analysis-button decision, with the Tk dialog replaced by a stub --------

def _app(frames, events, *, current_frame=0):
    app = SimpleNamespace()
    app.video = SimpleNamespace(frames=frames, total_frames=30, current_frame=current_frame)
    app.coding_setup = None
    app.stop_video = lambda: events.append("stop")
    app._cancel_arrow_hold_state = lambda: None
    app._cancel_wheel_scroll = lambda: None
    app.focus_set = lambda: None
    app.next_frame = lambda delta: events.append(("next_frame", delta))
    app._channel_display_label = lambda key: LabelingApp._channel_display_label(app, key)
    app._resolve_open_touches = lambda touches, **kwargs: LabelingApp._resolve_open_touches(app, touches, **kwargs)
    return app


def _stub_dialog(monkeypatch, result, seen):
    class Dialog:
        def __init__(self, parent, touches, channel_label, *, closing=False):
            seen.append(list(touches))
            self.result = result
    monkeypatch.setattr(labeling_app, "OpenTouchesDialog", Dialog)


def test_nothing_open_runs_analysis_without_a_prompt(monkeypatch):
    events, seen = [], []
    _stub_dialog(monkeypatch, None, seen)
    app = _app({2: {"RH": _rec("ON", 1)}, 4: {"RH": _rec("OFF", 1)}}, events)
    assert LabelingApp._resolve_open_touches_before_analysis(app) is True
    assert seen == [] and events == []


def test_cancel_blocks_analysis(monkeypatch):
    events, seen = [], []
    _stub_dialog(monkeypatch, None, seen)
    app = _app({2: {"RH": _rec("ON", 1)}}, events)
    assert LabelingApp._resolve_open_touches_before_analysis(app) is False
    assert seen == [[OpenTouch("RH", 2, 2)]]
    assert events == ["stop"]


def test_go_to_onset_jumps_to_the_selected_touch_and_blocks(monkeypatch):
    events, seen = [], []
    _stub_dialog(monkeypatch, (GO_TO_ONSET, 1), seen)
    frames = {2: {"RH": _rec("ON", 1)}, 9: {"LL": _rec("ON", 1)}}
    app = _app(frames, events, current_frame=4)
    assert LabelingApp._resolve_open_touches_before_analysis(app) is False
    assert events == ["stop", ("next_frame", 5)]
    assert find_open_touches(frames, LIMBS) != []  # data untouched


def test_skip_leaves_data_alone_and_proceeds(monkeypatch):
    events, seen = [], []
    _stub_dialog(monkeypatch, (ANALYZE_ANYWAY, 0), seen)
    frames = {2: {"RH": _rec("ON", 1)}}
    app = _app(frames, events)
    assert LabelingApp._resolve_open_touches_before_analysis(app) is True
    assert find_open_touches(frames, LIMBS) == [OpenTouch("RH", 2, 2)]
    assert events == ["stop"]


def test_channel_label_prefers_the_coding_setup_name():
    app = SimpleNamespace(coding_setup=SimpleNamespace(channel_labels={"RH": "Right hand"}))
    assert LabelingApp._channel_display_label(app, "RH") == "Right hand"
    assert LabelingApp._channel_display_label(app, "LL") == "LL"
    assert LabelingApp._channel_display_label(SimpleNamespace(coding_setup=None), "LH") == "LH"
