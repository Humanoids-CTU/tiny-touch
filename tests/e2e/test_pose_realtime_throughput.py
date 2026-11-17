"""Opt-in real-window Pose playback check; ordinary CI has no speed requirement.

Set TINYTOUCH_REALTIME_VIDEO to a local CFR video. Optional:
TINYTOUCH_REALTIME_RENDERER ('cpu' / 'auto'), TINYTOUCH_POSE_CARRY ('1' sets a
manual head size at frame 0 so play carries it onto every frame, default '1'),
TINYTOUCH_POSE_PROFILE (path for a cProfile dump of the playback run).
"""
import cProfile
import json
import os
from pathlib import Path
import time

import pytest

from domain.pose import ScaleKind, ZoneEvent
from domain.pose_setup import PoseCodingSetup
from gui_driver import click, load_video, pump, wait_until

pytestmark = [pytest.mark.gui, pytest.mark.skipif(
    not os.environ.get('TINYTOUCH_REALTIME_VIDEO'), reason='opt-in playback benchmark')]
ROOT = Path(__file__).resolve().parents[2]


def test_pose_realtime_play(app_factory, workspace, monkeypatch):
    kind = os.environ.get('TINYTOUCH_ANNOTATION', 'Pose')
    if os.environ.get('TINYTOUCH_GPU_SHRINK') in ('0', '1'):
        monkeypatch.setattr('adapters.frame_buffer.GPU_SHRINK_IN_WORKER',
                            os.environ['TINYTOUCH_GPU_SHRINK'] == '1')
    monkeypatch.setattr('labeling_app.choose_annotation_type', lambda *a, **kw: kind)
    monkeypatch.setattr('labeling_app.configure_pose_video', lambda *a, **kw: PoseCodingSetup())
    path = (ROOT / os.environ['TINYTOUCH_REALTIME_VIDEO']).resolve()
    settings_path = workspace.root / 'config.json'
    settings = json.loads(settings_path.read_text())
    settings['video_renderer'] = os.environ.get('TINYTOUCH_REALTIME_RENDERER', 'cpu')
    settings_path.write_text(json.dumps(settings))
    app = app_factory()
    app.attributes('-alpha', 1.0)
    app.geometry('1200x1000+80+40')
    app.title('TinyTouch isolated Pose realtime playback verification')
    load_video(app, workspace, path)
    assert app.annotation_type == kind
    pump(app, .5)
    total = app.video.total_frames
    fps = app.frame_rate
    pose = kind == 'Pose'
    labels = app.pose_session.labels if pose else None
    if pose:
        panel = app._pose_panel
        if os.environ.get('TINYTOUCH_POSE_CARRY', '1') == '1':
            panel.edit_scale(ScaleKind.HEAD, 1.2)
            assert labels.scale(0, ScaleKind.HEAD) is not None
        # A few events so the timelines and dots carry real marks.
        for frame in range(0, total, max(1, total // 8)):
            labels.set_event(frame, 'A', ZoneEvent.ON if (frame // 10) % 2 == 0 else ZoneEvent.OFF,
                             displayed_frame=frame)
        app._pose_timeline_index = None
    app.display_first_frame()
    # Wall time per UI-thread step, by name (instance-level wrappers).
    timings = {}

    instrument = os.environ.get('TINYTOUCH_TIMERS', '1') == '1'

    def timed(owner, name):
        if not instrument:   # measure production speed without wrapper overhead
            return
        original = getattr(owner, name)

        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                timings.setdefault(name, []).append(time.perf_counter() - t0)
        setattr(owner, name, wrapper)

    # Diagnostic switches, comma-separated: dots, timelines, controls, counter, idle.
    ablate = set(filter(None, os.environ.get('TINYTOUCH_ABLATE', '').split(',')))
    noop = lambda *a, **kw: None
    if 'timelines' in ablate:
        app.draw_timeline = app.draw_timeline2 = noop
    if 'detail' in ablate:
        app.draw_timeline = noop
    if 'overview' in ablate:
        app.draw_timeline2 = noop
    if 'controls' in ablate:
        app._refresh_frame_controls = noop
    if 'counter' in ablate:
        app.update_frame_counter = noop
    surface = getattr(app, '_gpu_video', None)
    if surface is not None and 'gpu' in ablate:
        for name in ('SDL_UpdateTexture', 'SDL_RenderPresent', 'SDL_RenderCopy', 'SDL_RenderClear',
                     'SDL_PumpEvents', 'SDL_FlushEvents'):
            timed(surface.sdl, name)
        timed(surface, '_draw')
        timed(surface, 'show')
        timed(surface, '_redraw')
        timed(surface, '_schedule_redraw')
    if pose and 'dots' in ablate:
        panel.draw_frame = noop
    from gui import timeline as timeline_module
    for name in ('draw_touch_detail', 'draw_touch_overview'):
        timed(timeline_module, name)
    for name in ('display_first_frame', '_show_frame_image', '_refresh_playback_ui',
                 '_refresh_frame_controls', 'draw_timeline', 'draw_timeline2', '_draw_diagram_dots',
                 'update_frame_counter', 'update_limb_parameter_buttons', 'update_button_colors',
                 'update_note_entry'):
        timed(app, name)
    if pose:
        for name in ('refresh', 'draw_frame', 'draw', 'annotation_changed'):
            timed(panel, name)
        index = app._get_pose_timeline_index()
        timed(index, 'update')
        timed(app, '_pose_annotation_changed')
        for view, label in (((app._pose_detail_timeline, 'detail'), (app._pose_overview_timeline, 'overview'))
                            if instrument else ()):
            for name in ('draw', '_column', 'flush'):
                original = getattr(view, name)
                def wrapper(*args, _o=original, _n=f'{label}.{name}', **kwargs):
                    t0 = time.perf_counter()
                    try:
                        return _o(*args, **kwargs)
                    finally:
                        timings.setdefault(_n, []).append(time.perf_counter() - t0)
                setattr(view, name, wrapper)
        original_painted = panel.painted
        timed(panel, 'painted')
        app.frame_paint_listeners[:] = [panel.painted if l == original_painted else l
                                        for l in app.frame_paint_listeners]
    wait_until(app, lambda: app._play_window_buffered(0, 1))
    pump(app, .25)

    if os.environ.get('TINYTOUCH_PLAYHEAD_PROBE'):
        from collections import Counter
        for name in ('timeline_canvas', 'timeline2_canvas'):
            c = getattr(app, name)
            kinds = Counter(c.type(i) for i in c.find_all())
            images = []
            for i in c.find_withtag('all'):
                if c.type(i) == 'image':
                    bbox = c.bbox(i)
                    images.append((c.gettags(i), bbox and (bbox[2] - bbox[0], bbox[3] - bbox[1])))
            print('CANVAS', kind, name, c.winfo_width(), 'x', c.winfo_height(), dict(kinds), 'images', images[:6],
                  'parent', c.winfo_parent(), flush=True)
        # Move only the timeline playheads, frame by frame; time Tk's repaint.
        video = app.video
        for label, draws in (('detail', (app.draw_timeline,)), ('overview', (app.draw_timeline2,)),
                             ('both', (app.draw_timeline, app.draw_timeline2))):
            spent, idle_t = [], []
            for frame in range(1, 401):
                video.current_frame = frame
                t0 = time.perf_counter()
                for draw in draws:
                    draw()
                t1 = time.perf_counter()
                app.update_idletasks()
                spent.append(t1 - t0); idle_t.append(time.perf_counter() - t1)
            spent.sort(); idle_t.sort()
            print('PLAYHEAD_PROBE', kind, label, 'python median %.2f ms' % (1000 * spent[200]),
                  'tk idle median %.2f ms p95 %.2f ms' % (1000 * idle_t[200], 1000 * idle_t[380]), flush=True)
        return
    paints, steps = [], []
    original_advance = app._apply_play_advance

    idle = []
    measure_idle = 'idle' in ablate

    def timed_advance(*args):
        t0 = time.perf_counter()
        original_advance(*args)
        steps.append(time.perf_counter() - t0)
        if measure_idle:   # run Tk's pending redraw/layout now, so it can be timed
            t1 = time.perf_counter()
            app.update_idletasks()
            idle.append(time.perf_counter() - t1)

    app._apply_play_advance = timed_advance
    app.frame_paint_listeners.append(lambda frame, size: paints.append((time.perf_counter(), frame)))
    stalls = []
    original_ready = app._play_window_buffered

    def record_ready(*args):
        ready = original_ready(*args)
        if not ready:
            stalls.append(time.perf_counter())
        return ready

    app._play_window_buffered = record_ready
    started = time.perf_counter()
    timeout_s = float(os.environ.get('TINYTOUCH_BENCH_SECONDS', max(30, 3 * total / fps)))
    done = []

    def poll():
        if app.video.current_frame == total and not app.play:
            done.append(True)
            app.quit()
        elif time.perf_counter() - started > timeout_s:
            app.stop_video()
            app.quit()
        else:
            app.after(5, poll)

    timer = app.after(5, poll)
    profile_path = os.environ.get('TINYTOUCH_POSE_PROFILE')
    profiler = cProfile.Profile() if profile_path else None
    try:
        click(app, 'Play')
        if profiler:
            profiler.enable()
        app.mainloop()
    finally:
        if profiler:
            profiler.disable()
            profiler.dump_stats(profile_path)
        app.after_cancel(timer)
        app.stop_video()
        app._apply_play_advance = original_advance
        app._play_window_buffered = original_ready
    elapsed = paints[-1][0] - started if paints else None
    expected = max(0, total - 1) / fps
    steps.sort()
    canvas_items = {name: len(getattr(app, name).find_all()) for name in ('timeline_canvas', 'timeline2_canvas')}
    shown = getattr(app, '_displayed_image', None)
    result = dict(ablate=sorted(ablate), canvas_items=canvas_items, renderer=app._renderer_status.get(),
                  frame=(shown.size, shown.mode) if shown is not None else None,
                  display=(app._display_w, app._display_h), shown_fps=round(len(paints) / elapsed, 1) if elapsed else None,
                  idle_ms_mean=round(1000 * sum(idle) / len(idle), 2) if idle else None,
                  fps=fps, frames=total, elapsed_s=elapsed, expected_s=expected,
                  ratio=elapsed / expected if elapsed and expected else None,
                  buffer_stalls=len(stalls), painted=len(paints),
                  step_ms_median=1000 * steps[len(steps) // 2] if steps else None,
                  step_ms_p95=1000 * steps[int(len(steps) * .95)] if steps else None,
                  step_ms_max=1000 * steps[-1] if steps else None,
                  carried=sum(1 for f in range(total + 1)
                              if labels.scale(f, ScaleKind.HEAD) is not None) if pose else None,
                  ms_per_step={name: round(1000 * sum(v) / max(1, len(steps)), 2)
                               for name, v in sorted(timings.items(), key=lambda kv: -sum(kv[1]))},
                  calls={name: len(v) for name, v in timings.items()},
                  p95_ms_per_call={name: round(1000 * sorted(v)[int(len(v) * .95)], 2)
                                   for name, v in timings.items() if v})
    print('POSE_REALTIME_RESULT ' + json.dumps(result), flush=True)
    assert done, f'Playback did not finish: {result}'
    assert elapsed <= expected * 1.05 + .05, f'Pose playback fell behind realtime: {result}'
    assert workspace.errors() == []
