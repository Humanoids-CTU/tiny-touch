"""Configured parameter labels must survive the complete video-loading flow."""

import pytest


pytestmark = pytest.mark.gui


def test_loaded_video_shows_configured_parameter_labels(loaded_app):
    app = loaded_app
    assert [
        app.limb_par1_btn.cget("text"),
        app.limb_par2_btn.cget("text"),
        app.limb_par3_btn.cget("text"),
    ] == ["LP1", "LP2", "LP3"]
    assert [
        app.par1_btn.cget("text"),
        app.par2_btn.cget("text"),
        app.par3_btn.cget("text"),
    ] == ["Looking1", "P2", "P3"]
