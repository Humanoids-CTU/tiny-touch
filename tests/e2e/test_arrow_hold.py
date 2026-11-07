"""Arrow navigation through real Tk bindings and the playback timer."""
import pytest

from gui_driver import click, pump, wait_until

pytestmark = pytest.mark.gui


def test_arrow_taps_step_once_and_holds_play_until_release(loaded_app):
    app = loaded_app
    app.realtime_arrow_hold = True
    wait_until(app, lambda: all(i in app.frame_buffer for i in range(10)))
    app.focus_force()
    pump(app)

    app.event_generate('<KeyPress-Right>', when='now')
    assert not app.play
    app.event_generate('<KeyRelease-Right>', when='now')
    pump(app, 0.2)
    assert app.video.current_frame == 1
    assert not app.play

    app.event_generate('<KeyPress-Right>', when='now')
    wait_until(app, lambda: app.play, timeout=1, what='hold playback')
    assert app.video.current_frame >= 3
    app.event_generate('<KeyRelease-Right>', when='now')
    pump(app)
    stopped = app.video.current_frame
    pump(app, 0.12)
    assert app.video.current_frame == stopped
    assert not app.play

    # X11 may emit release/press pairs on auto-repeat; they must not add
    # extra steps or stop the running playback chain.
    app.event_generate('<KeyPress-Left>', when='now')
    wait_until(app, lambda: app.play, timeout=1, what='reverse hold playback')
    frame = app.video.current_frame
    app.event_generate('<KeyRelease-Left>', when='now')
    app.event_generate('<KeyPress-Left>', when='now')
    app.update_idletasks()
    assert app.play
    assert app.video.current_frame == frame
    app.event_generate('<KeyRelease-Left>', when='now')
    pump(app)
    assert not app.play

    # Changing direction ignores the old key's later release.
    app.event_generate('<KeyPress-Right>', when='now')
    app.event_generate('<KeyPress-Left>', when='now')
    app.event_generate('<KeyRelease-Right>', when='now')
    wait_until(app, lambda: app.play, timeout=1, what='changed hold direction')
    assert app.play
    assert app.play_dir == -1
    app.event_generate('<KeyRelease-Left>', when='now')
    pump(app)

    # Losing focus must stop playback even if release goes to another app.
    app.event_generate('<KeyPress-Right>', when='now')
    app.event_generate('<FocusOut>', when='now')
    pump(app)
    assert not app.play

    # Exact toolbar stepping and the setting's disabled behavior survive.
    app.video.current_frame = 3
    app.display_first_frame()
    click(app, '>')
    pump(app, 0.12)
    assert app.video.current_frame == 4
    app.realtime_arrow_hold = False
    app.event_generate('<KeyPress-Right>', when='now')
    pump(app, 0.12)
    assert app.video.current_frame == 5
    assert not app.play
    app.event_generate('<KeyRelease-Right>', when='now')

    # An arrow released in the note box still stops an existing hold;
    # arrows pressed there must remain text-editing keys.
    app.realtime_arrow_hold = True
    app.event_generate('<KeyPress-Left>', when='now')
    app.note_entry.focus_force()
    pump(app)
    app.note_entry.event_generate('<KeyRelease-Left>', when='now')
    pump(app)
    frame = app.video.current_frame
    app.note_entry.event_generate('<KeyPress-Right>', when='now')
    pump(app, 0.12)
    assert app.video.current_frame == frame
    assert not app.play
