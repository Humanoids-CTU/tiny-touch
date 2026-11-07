"""Opt-in real-window throughput check; ordinary CI has no speed requirement.

Set TINYTOUCH_REALTIME_VIDEO to a local CFR video and optionally
TINYTOUCH_REALTIME_RESULTS to a JSON output path. Uses unmodified production
playback, real decoding and rendering, and isolated project/config fixtures.
"""
import json
import os
from pathlib import Path
import time

import pytest

from domain.model import empty_bundle
from gui_driver import click, load_video, pump, wait_until

pytestmark = [pytest.mark.gui, pytest.mark.skipif(
    not os.environ.get('TINYTOUCH_REALTIME_VIDEO'), reason='opt-in playback benchmark')]
ROOT = Path(__file__).resolve().parents[2]


def test_realtime_play_and_arrow_holds(app_factory, workspace):
    path = (ROOT / os.environ['TINYTOUCH_REALTIME_VIDEO']).resolve()
    settings_path = workspace.root / 'config.json'
    settings = json.loads(settings_path.read_text())
    settings['video_renderer'] = os.environ.get('TINYTOUCH_REALTIME_RENDERER', 'auto')
    settings['realtime_arrow_hold'] = True
    settings_path.write_text(json.dumps(settings))
    app = app_factory()
    app.attributes('-alpha', 1.0)
    app.geometry('1200x1000+80+40')
    app.title('TinyTouch isolated realtime playback verification')
    load_video(app, workspace, path)
    pump(app, .5)
    total = app.video.total_frames
    fps = app.frame_rate
    limb = app.option_var_1.get()
    # An annotated workload exercises timeline markers, notes and state changes.
    for frame in range(total + 1):
        bundle = empty_bundle()
        bundle['Params']['Par1'] = 'ON' if (frame // 25) % 2 == 0 else 'OFF'
        bundle[limb]['LimbParams'] = {'Par1': 'ON' if (frame // 50) % 2 == 0 else 'OFF'}
        if frame % 50 == 0:
            bundle['Note'] = f'Benchmark annotation at frame {frame}'
            bundle[limb].update(X=[100], Y=[100], Zones=[['I']],
                                Onset='ON' if frame % 100 == 0 else 'OFF')
        app.video.frames[frame] = bundle
    app._timeline_dirty = app._timeline2_dirty = True
    app.display_first_frame()
    results = []
    modes = os.environ.get('TINYTOUCH_REALTIME_MODES', 'play,hold_forward,hold_backward').split(',')
    for mode in modes:
        direction = -1 if mode == 'hold_backward' else 1
        start_frame, end_frame = (total, 0) if direction == -1 else (0, total)
        app.stop_video()
        app._cancel_arrow_hold_state()
        if app.video.current_frame != start_frame:
            app.next_frame(start_frame - app.video.current_frame)
        wait_until(app, lambda: app.displayed_frame == start_frame)
        wait_until(app, lambda: app._play_window_buffered(start_frame, direction))
        pump(app, .25)
        paints = []
        stalls = []
        original_ready = app._play_window_buffered

        def record_ready(*args):
            ready = original_ready(*args)
            if not ready:
                stalls.append(time.perf_counter())
            return ready

        def painted(frame, size):
            paints.append((time.perf_counter(), frame))

        app._play_window_buffered = record_ready
        app.frame_paint_listeners.append(painted)
        started = time.perf_counter()
        timeout_s = max(30, 3 * total / fps)
        finished_at_boundary = []

        def poll():
            if app.video.current_frame == end_frame and not app.play:
                finished_at_boundary.append(True)
                app.quit()
            elif time.perf_counter() - started > timeout_s:
                app.stop_video()
                app.quit()
            else:
                app.after(5, poll)

        timer = app.after(5, poll)
        try:
            if mode == 'play':
                click(app, 'Play')
            elif direction == 1:
                app.navigate_right(None)
            else:
                app.navigate_left(None)
            app.mainloop()
        finally:
            app.after_cancel(timer)
            app.stop_video()
            app._cancel_arrow_hold_state()
            app._play_window_buffered = original_ready
            app.frame_paint_listeners.remove(painted)
        elapsed = paints[-1][0] - started if paints else None
        # The first playback step is immediate; frame 0 was already visible.
        expected = (max(0, total - 1) / fps if mode == 'play' else
                    .150 + max(0, total - 2) / fps)
        result = dict(mode=mode, renderer=app._renderer_status.get(), fps=fps,
                      advances=total, elapsed_s=elapsed, expected_s=expected,
                      painted_frames=len(paints), buffer_stalls=len(stalls),
                      unique_frames=len({frame for _, frame in paints}),
                      first_frames=[frame for _, frame in paints[:15]],
                      last_frames=[frame for _, frame in paints[-15:]],
                      final_frame=app.displayed_frame)
        results.append(result)
        print('REALTIME_RESULT ' + json.dumps(result), flush=True)
        output = os.environ.get('TINYTOUCH_REALTIME_RESULTS')
        if output:
            Path(output).write_text(json.dumps(results, indent=2))
        assert finished_at_boundary, f'Playback did not finish: {result}'
        assert elapsed <= expected * 1.05 + .05, f'Playback fell behind realtime: {result}'
        assert [frame for _, frame in paints] == list(range(
            start_frame + direction, end_frame + direction, direction))
        assert app.displayed_frame == end_frame
        assert app.frame_counter_label.cget('text') == f'{end_frame} / {total}'
        assert app._get_note_entry_text() == (app.video.frames[end_frame]['Note'] or '')
    assert workspace.errors() == []
