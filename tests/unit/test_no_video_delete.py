"""Delete input is harmless before loading a video or during a project swap."""
import tkinter as tk
from types import SimpleNamespace

import pytest

from labeling_app import LabelingApp


@pytest.mark.parametrize("event", [None, tk.Event(), SimpleNamespace(x=10, y=20)])
def test_delete_without_a_video_is_a_noop(event):
    app = SimpleNamespace(video=None, last_mouse_x=10, last_mouse_y=20)
    LabelingApp.on_middle_click(app, event)
    assert app.video is None
