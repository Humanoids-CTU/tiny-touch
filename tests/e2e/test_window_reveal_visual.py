"""Screen check of the window reveal (gui.window_reveal): no half-built dialog frame is presented.

Opens real dialogs (one process each) through demos/dialog_reveal_lab.py and
records every frame the desktop compositor presents (DXGI Desktop
Duplication). Every frame inside the dialog's area must be either the frame
before the open or the settled dialog: zero dirty frames, and zero Tk geometry
changes after the reveal. The video load (demos/video_load_lab.py) is held to
the same rule for the main window after its last dialog closes. Windows only;
the windows appear on screen for a few seconds each, over a neutral
full-screen backdrop.
"""
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.gui, pytest.mark.skipif(sys.platform != "win32", reason="DXGI capture is Windows-only")]

DEMOS = Path(__file__).resolve().parents[2] / "demos"
# Content-sized, image-heavy and card-heavy dialogs: the ones that used to
# show cards growing and the window jumping to its centre.
VISUAL_DIALOGS = ("template", "open_touches", "special_zones", "library", "wizard")


@pytest.fixture(scope="module")
def reveal_lab():
    sys.path.insert(0, str(DEMOS))
    import dialog_reveal_lab
    try:
        capture = dialog_reveal_lab.lab.DesktopCapture()
    except OSError as exc:
        pytest.skip(f"desktop capture unavailable: {exc}")
    return dialog_reveal_lab, capture


@pytest.mark.parametrize("dialog", VISUAL_DIALOGS)
def test_dialog_never_presents_a_half_built_frame(reveal_lab, dialog):
    lab, capture = reveal_lab
    with lab.CaptureLock():
        outcome = lab.run_case(capture, dialog, "hooked", 0)
    assert "error" not in outcome, outcome.get("error")
    assert outcome["frames_total"] > 0, "no frames captured (screen locked or off?)"
    (segment,) = outcome["segments"]
    assert segment["visible_ms"] is not None, "the dialog never appeared"
    assert segment["dirty"] == 0, f"{segment['dirty']} half-built frame(s)"
    assert segment["tk_changes_after_reveal"] == 0


@pytest.fixture(scope="module")
def video_load_lab():
    sys.path.insert(0, str(DEMOS))
    import video_load_lab
    try:
        capture = video_load_lab.lab.DesktopCapture()
    except OSError as exc:
        pytest.skip(f"desktop capture unavailable: {exc}")
    return video_load_lab, capture


def test_video_load_switches_to_the_loaded_video_in_one_step(video_load_lab):
    """New video and resume from the library: after the last dialog closes, the
    main window goes from the old picture straight to the first frame (gui.content_swap)."""
    lab, capture = video_load_lab
    with lab.CaptureLock():
        outcome = lab.run_case(capture, "app", "gpu", 0, play=False)
    assert "error" not in outcome, outcome.get("error")
    assert outcome["frames_total"] > 0, "no frames captured (screen locked or off?)"
    new, _ = outcome["loads"]
    assert new["frames"] > 0, "nothing changed after the new video's last dialog closed"
    for load in outcome["loads"]:
        assert load["painted"], f"{load['load']}: the first frame was never painted"
        assert load["dirty"] == 0, f"{load['load']}: {load['dirty']} half-built frame(s) ({load['kinds']})"
