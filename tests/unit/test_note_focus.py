"""Saving a note returns keyboard navigation to the application."""

from types import SimpleNamespace

import keyboard
import pytest

from labeling_app import LabelingApp


@pytest.mark.parametrize("original,text", [(None, "a note"), ("a note", "a note"), ("a note", "")])
def test_save_note_leaves_editor_after_add_unchanged_or_clear(monkeypatch, original, text):
    editor = object()
    window = object()
    focus = [editor]
    app = SimpleNamespace(
        video=SimpleNamespace(current_frame=2, frames={2: {"Note": original}}),
        _get_note_entry_text=lambda: text,
        mark_bundle_changed=lambda *_: None,
        focus_set=lambda: focus.__setitem__(0, window),
    )
    monkeypatch.setattr(keyboard, "press_and_release", lambda *_: None)

    LabelingApp.save_note(app)

    assert app.video.frames[2]["Note"] == (text or None)
    assert focus[0] is window
