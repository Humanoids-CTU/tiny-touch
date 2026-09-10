"""Frame selection through the real toolbar button and modal dialog."""
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

import pytest

from gui_driver import pump, walk

pytestmark = pytest.mark.gui


def test_frame_selection_dialog(loaded_app, workspace):
    app = loaded_app
    button = app.select_frame_button
    labels = [child.cget("text") for child in button.master.winfo_children()]
    assert labels[:5] == ["<<", "<", "Select Frame", ">", ">>"]
    app.video.frames.setdefault(3, {})["Note"] = "destination note"

    def open_dialog(interact):
        errors = []
        visited = []

        def respond():
            dialog = next(
                (w for w in app.winfo_children()
                 if isinstance(w, tk.Toplevel) and w.title() == "Select Frame"),
                None,
            )
            if dialog is None:
                errors.append(AssertionError("Select Frame dialog did not open"))
                return
            visited.append(True)
            try:
                entry = next(w for w in walk(dialog) if isinstance(w, ttk.Entry))
                buttons = {
                    w.cget("text"): w for w in walk(dialog) if isinstance(w, ttk.Button)
                }
                assert entry.get() == str(app.video.current_frame)
                assert not app.play
                interact(dialog, entry, buttons)
            except Exception as exc:
                errors.append(exc)
            finally:
                if dialog.winfo_exists():
                    dialog.destroy()

        app.after(150, respond)
        button.invoke()
        pump(app)
        assert visited
        if errors:
            raise errors[0]

    def enter(entry, text):
        entry.delete(0, "end")
        entry.insert(0, str(text))

    def accept(target):
        def interact(dialog, entry, buttons):
            enter(entry, target)
            buttons["OK"].invoke()
        return interact

    app.play = True
    open_dialog(accept(3))
    assert app.video.current_frame == 3
    assert app._get_note_entry_text() == "destination note"
    assert app.frame_counter_label.cget("text") == f"3 / {app.video.total_frames}"

    def reject_then_cancel(dialog, entry, buttons):
        for invalid in ("", "abc", "1.5", "-1", str(app.video.total_frames + 1)):
            enter(entry, invalid)
            count = len(workspace.messages)
            buttons["OK"].invoke()
            assert len(workspace.messages) == count + 1
            assert workspace.messages[-1][0] == "showwarning"
            assert dialog.winfo_exists()
            assert app.video.current_frame == 3
        # Global wheel bindings and pending playback cannot move behind the dialog.
        app.on_mouse_wheel(SimpleNamespace(delta=-120, num=None))
        app._apply_play_advance(4, 1)
        assert app.video.current_frame == 3
        enter(entry, 2)
        buttons["Cancel"].invoke()

    open_dialog(reject_then_cancel)
    assert app.video.current_frame == 3
    assert app._get_note_entry_text() == "destination note"

    for target in (0, app.video.total_frames):
        open_dialog(accept(target))
        assert app.video.current_frame == target
