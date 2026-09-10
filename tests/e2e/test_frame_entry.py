"""Direct frame navigation through the real editable counter."""
import pytest

from gui_driver import pump

pytestmark = pytest.mark.gui


def test_frame_entry_navigation(loaded_app):
    app = loaded_app
    entry = app.frame_entry
    app.video.frames.setdefault(3, {})["Note"] = "destination note"
    app.play = True
    entry.event_generate("<Button-1>")
    pump(app)
    assert not app.play
    assert entry.selection_present()

    def type_number(text):
        entry.delete(0, "end")
        entry.insert(0, text)

    type_number("3")
    app.update_frame_counter()
    assert entry.get() == "3"  # A repaint must not overwrite a draft.
    entry.event_generate("<Return>")
    pump(app)
    assert app.video.current_frame == 3
    assert app._get_note_entry_text() == "destination note"
    assert app.focus_get() != entry

    entry.event_generate("<Button-1>")
    pump(app)
    for invalid in ("", "abc", "1.5", "-1", str(app.video.total_frames + 1)):
        type_number(invalid)
        entry.event_generate("<Return>")
        pump(app)
        assert app.video.current_frame == 3
        assert app.frame_entry_error.get()
        assert entry.get() == invalid

    entry.event_generate("<Escape>")
    pump(app)
    assert entry.get() == "3"
    assert not app.frame_entry_error.get()

    entry.event_generate("<Button-1>")
    pump(app)
    type_number("2")
    entry.event_generate("<Right>")
    entry.event_generate("<space>")
    pump(app)
    assert app.video.current_frame == 3
    assert not app.play
    app.note_entry.event_generate("<Button-1>")
    pump(app)
    assert entry.get() == "3"

    for target in (0, app.video.total_frames):
        entry.event_generate("<Button-1>")
        pump(app)
        type_number(str(target))
        entry.event_generate("<Return>")
        pump(app)
        assert app.video.current_frame == target
