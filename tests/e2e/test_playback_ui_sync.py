"""Playback may refresh controls less often, but paused annotation stays exact."""
import pytest

from domain.model import empty_bundle
from adapters import config
from gui_driver import click, pump, wait_until

pytestmark = pytest.mark.gui


def _seed_frames(app):
    limb = app.option_var_1.get()
    for frame in range(app.video.total_frames + 1):
        bundle = empty_bundle()
        bundle['Note'] = f'Note on frame {frame}'
        bundle['Params']['Par1'] = 'ON' if frame % 2 == 0 else 'OFF'
        bundle[limb]['LimbParams'] = {'Par1': 'OFF' if frame % 2 == 0 else 'ON'}
        app.video.frames[frame] = bundle
    app.display_first_frame()
    return limb


def _assert_controls_match_current_frame(app):
    frame = app.video.current_frame
    assert app.displayed_frame == frame
    assert app.frame_counter_label.cget('text') == f'{frame} / {app.video.total_frames}'
    assert app._get_note_entry_text() == f'Note on frame {frame}'
    state = 'ON' if frame % 2 == 0 else 'OFF'
    assert app.par1_btn.cget('style') == ('StateOn.TButton' if state == 'ON' else 'StateOff.TButton')
    assert app.limb_par1_btn.cget('style') == ('StateOff.TButton' if state == 'ON' else 'StateOn.TButton')


def test_stop_boundary_and_arrow_release_synchronize_annotation_controls(loaded_app):
    app = loaded_app
    _seed_frames(app)
    wait_until(app, lambda: all(i in app.frame_buffer for i in range(10)))
    click(app, 'Play')
    wait_until(app, lambda: app.video.current_frame >= 2)
    click(app, 'Stop')
    _assert_controls_match_current_frame(app)

    click(app, 'Play')
    wait_until(app, lambda: not app.play)
    assert app.video.current_frame == app.video.total_frames
    _assert_controls_match_current_frame(app)

    app.realtime_arrow_hold = True
    app.navigate_left(None)
    wait_until(app, lambda: app.play)
    app._on_arrow_release(-1)
    pump(app)
    assert not app.play
    _assert_controls_match_current_frame(app)

    app.navigate_left(None)
    wait_until(app, lambda: app.video.current_frame == 0 and not app.play)
    _assert_controls_match_current_frame(app)


def test_annotation_during_playback_pauses_on_the_painted_frame(loaded_app):
    app = loaded_app
    _seed_frames(app)
    click(app, 'Play')
    wait_until(app, lambda: app.video.current_frame >= 2)
    frame = app.displayed_frame
    previous = app.video.frames[frame]['Params']['Par1']
    app.par1_btn.invoke()
    assert not app.play
    assert app.video.current_frame == frame
    assert app.video.frames[frame]['Params']['Par1'] != previous
    assert app.frame_counter_label.cget('text') == f'{frame} / {app.video.total_frames}'
    pump(app, .15)
    assert app.video.current_frame == frame


def test_focusing_notes_pauses_before_editing_and_keeps_draft(loaded_app):
    app = loaded_app
    _seed_frames(app)
    app.focus_force()
    pump(app)
    click(app, 'Play')
    wait_until(app, lambda: app.video.current_frame >= 2)
    app.note_entry.focus_force()
    pump(app)
    assert not app.play
    frame = app.video.current_frame
    assert app._get_note_entry_text() == f'Note on frame {frame}'
    app._set_note_entry_text('unsaved draft')
    app.stop_video()
    assert app._get_note_entry_text() == 'unsaved draft'
    pump(app, .1)
    assert app.video.current_frame == frame


def test_display_setting_change_preserves_the_current_frames_note(loaded_app):
    app = loaded_app
    _seed_frames(app)
    wait_until(app, lambda: all(i in app.frame_buffer for i in range(10)))
    app.play_video()
    # Simulate the interval between control refreshes while video advances.
    app._play_ui_next_due = float('inf')
    app._apply_play_advance(2, 1)
    assert app.displayed_frame == 2
    assert app._get_note_entry_text() == 'Note on frame 1'
    settings = config.load_config()
    settings['video_downscale'] = 2.0
    config.save_config(settings)
    app.apply_runtime_settings(settings)
    assert not app.play
    wait_until(app, lambda: app.displayed_frame == 2 and app._displayed_image is not None)
    assert app._get_note_entry_text() == 'Note on frame 2'
