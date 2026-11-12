"""Regression test for closing the Tk root from frame-extraction progress."""

import pytest
from threading import Event

from adapters.frame_extractor import FrameExtractionCancelled
from gui_driver import dismiss_dialog, find_toplevel, find_widget
from tkinter import ttk
from service_layer import project_service


pytestmark = pytest.mark.gui


def test_close_during_frame_extraction_is_clean(
    app,
    workspace,
    monkeypatch,
):
    observed = {}
    extraction_started = Event()

    def fake_extract_frames(
        _video_path,
        _paths,
        _labeling_mode,
        progress_cb=None,
        cancel_event=None,
    ):
        observed["cancel_event"] = cancel_event
        progress_cb(1, 10, "Generating frames", 0.1)
        extraction_started.set()
        assert cancel_event.wait(5), "Tk did not cancel the extraction worker"
        observed["cancelled"] = cancel_event.is_set()
        raise FrameExtractionCancelled("Frame extraction cancelled.")

    monkeypatch.setattr(project_service, "extract_frames", fake_extract_frames)
    workspace.chosen_video = str(workspace.video)

    library_dialog = dismiss_dialog(app, "Video library", "Load new video")
    mode_dialog = dismiss_dialog(app, "Select Mode", "Continue")
    prepared = {"clicked": False}
    def advance_setup():
        window = find_toplevel(app, "Prepare video")
        if window is not None:
            button = find_widget(window, cls=ttk.Button, text="Next")
            if button is not None:
                button.invoke()
            else:
                button = find_widget(window, cls=ttk.Button, text="Prepare video")
                if button is not None:
                    prepared["clicked"] = True
                    button.invoke()
                    return
        app.after(20, advance_setup)
    app.after(20, advance_setup)
    close_dialog = dismiss_dialog(app, "Close Application", "OK")
    def close_when_extracting():
        if extraction_started.is_set():
            app.on_close()
        else:
            app.after(20, close_when_extracting)
    app.after(20, close_when_extracting)
    app.load_video_btn.invoke()

    assert mode_dialog["clicked"] is True
    assert library_dialog["clicked"] is True
    assert prepared["clicked"] is True
    assert close_dialog["clicked"] is True
    assert observed["cancel_event"] is not None
    assert observed["cancelled"] is True
    assert not [message for message in workspace.messages if message[0] == "showerror"]
