"""Notes appear on both timelines and their markers navigate to exact frames."""

import pytest

from gui_driver import click_canvas, goto_frame, pump, select_radio, wait_until

pytestmark = pytest.mark.gui


def test_save_navigate_and_clear_note(loaded_app):
    app = loaded_app
    goto_frame(app, 2)
    app.note_entry.insert("1.0", "Look here")
    app.note_entry.focus_set()
    app.save_note_button.invoke()
    pump(app)
    assert str(app.tk.call("focus", "-lastfor", app._w)) == app._w

    for canvas in (app.timeline_canvas, app.timeline2_canvas):
        assert len(canvas.find_withtag("note_marker")) == 1

    select_radio(app, "Right Hand")
    for canvas in (app.timeline_canvas, app.timeline2_canvas):
        goto_frame(app, 5)
        approximate_jumps = []
        binding = canvas.bind("<Button-1>", lambda _event: approximate_jumps.append(True), add="+")
        marker, = canvas.find_withtag("note_marker")
        coords = canvas.coords(marker)
        x = round(sum(coords[::2]) / (len(coords) // 2))
        y = round(sum(coords[1::2]) / (len(coords) // 2))
        click_canvas(canvas, "<Button-1>", x, y)
        wait_until(app, lambda: app.displayed_frame == 2, what="note frame painted")
        assert app.video.current_frame == 2
        assert approximate_jumps == []
        assert app.note_entry.get("1.0", "end-1c") == "Look here"
        canvas.unbind("<Button-1>", binding)

    app.note_entry.delete("1.0", "end")
    app.save_note_button.invoke()
    pump(app)
    assert not app.timeline_canvas.find_withtag("note_marker")
    assert not app.timeline2_canvas.find_withtag("note_marker")
