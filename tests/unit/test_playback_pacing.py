"""Headless checks for playback paced on the Tk thread (`LabelingApp._play_tick`).

There is no playback thread any more (SMOOTHNESS_PLAN.md step 3): Play and
arrow-hold playback are a chain of `after()` callbacks on the Tk thread,
paced against a running deadline like the mouse wheel, and gated on the
next PLAYBACK_BUFFER_AHEAD frames being decoded ("stall briefly rather than
stutter").
"""

from types import MethodType, SimpleNamespace

import pytest

import labeling_app
from adapters.frame_buffer import PLAYBACK_BUFFER_AHEAD
from labeling_app import LabelingApp

FPS = 25.0
INTERVAL_MS = 1000.0 / FPS


class FakeBuffer:
    def __init__(self, frames=range(0, 1000)):
        self.frames = set(frames)
        self.priority_requests = []

    def __contains__(self, frame):
        return frame in self.frames

    def request_priority(self, frame):
        self.priority_requests.append(frame)


class FakeClock:
    """Deterministic stand-in for the `time` module; the test advances it."""

    def __init__(self):
        self.now = 1000.0

    def perf_counter(self):
        return self.now

    def monotonic(self):
        return self.now


class WindowsClock(FakeClock):
    """time.monotonic() on Windows is GetTickCount64: 15.625 ms steps."""

    TICK_S = 0.015625

    def monotonic(self):
        return (self.now // self.TICK_S) * self.TICK_S


class TimersRecorder:
    def __init__(self):
        self.holders = set()
        self.log = []

    def hold(self, holder):
        self.holders.add(holder)
        self.log.append(("hold", holder))

    def release(self, holder):
        self.holders.discard(holder)
        self.log.append(("release", holder))


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(labeling_app, "time", fake)
    return fake


@pytest.fixture
def windows_clock(monkeypatch):
    fake = WindowsClock()
    monkeypatch.setattr(labeling_app, "time", fake)
    return fake


def _play_app(clock, *, current_frame=100, total_frames=999, buffer=None, redraw_s=0.0):
    app = SimpleNamespace(
        video=SimpleNamespace(current_frame=current_frame, total_frames=total_frames),
        frame_rate=FPS,
        frame_buffer=buffer if buffer is not None else FakeBuffer(),
        play=False,
        play_dir=1,
        _hold_play_active=False,
        _play_tick_id=None,
        _play_next_due=None,
        _precise_timers=TimersRecorder(),
        scheduled=[],      # (delay_ms, callback)
        advances=[],       # (frame, direction, clock time)
    )

    def after(delay, callback):
        app.scheduled.append((delay, callback))
        return len(app.scheduled)

    def apply_play_advance(next_frame, direction):
        app.advances.append((next_frame, direction, clock.now))
        app.video.current_frame = next_frame
        clock.now += redraw_s  # the synchronous redraw cost

    app.after = after
    app._apply_play_advance = apply_play_advance
    app._next_deadline = LabelingApp._next_deadline
    app._next_playback_deadline = LabelingApp._next_playback_deadline
    for name in ("_frame_interval_s", "_start_playback", "_play_window_buffered",
                 "_play_tick", "_end_play_chain", "_on_playback_boundary", "stop_video",
                 "_flush_playback_ui"):
        setattr(app, name, MethodType(getattr(LabelingApp, name), app))
    return app


def _run(app, clock, ticks):
    """Fire up to `ticks` scheduled callbacks, advancing the clock by their delay."""
    for _ in range(ticks):
        if not app.scheduled:
            return
        delay, callback = app.scheduled.pop(0)
        clock.now += delay / 1000.0
        callback()


def test_playback_advances_one_frame_per_frame_interval(clock):
    app = _play_app(clock)
    app._start_playback(1)
    _run(app, clock, 10)

    frames = [f for f, _, _ in app.advances]
    assert frames == list(range(101, 112))
    gaps_ms = [(b - a) * 1000 for (_, _, a), (_, _, b) in zip(app.advances, app.advances[1:])]
    assert all(abs(g - INTERVAL_MS) < 1.0 for g in gaps_ms)


def test_redraw_cost_is_absorbed_into_the_frame_interval(clock):
    # 25 ms of redraw per frame must not stretch the 40 ms interval to 65 ms.
    app = _play_app(clock, redraw_s=0.025)
    app._start_playback(1)
    _run(app, clock, 10)

    gaps_ms = [(b - a) * 1000 for (_, _, a), (_, _, b) in zip(app.advances, app.advances[1:])]
    assert all(abs(g - INTERVAL_MS) < 1.0 for g in gaps_ms)


def test_playback_waits_for_the_frames_ahead_then_resumes_without_a_burst(clock):
    ahead = set(range(101, 101 + PLAYBACK_BUFFER_AHEAD + 1))
    buffer = FakeBuffer(set(range(0, 1000)) - ahead)
    app = _play_app(clock, buffer=buffer)
    app._start_playback(1)
    _run(app, clock, 5)                       # 5 polls while the frames decode

    assert app.advances == []
    assert buffer.priority_requests and buffer.priority_requests[-1] == 101

    buffer.frames |= ahead                    # the decodes land
    _run(app, clock, 3)
    frames = [f for f, _, _ in app.advances]
    assert frames == [101, 102, 103]
    gaps_ms = [(b - a) * 1000 for (_, _, a), (_, _, b) in zip(app.advances, app.advances[1:])]
    assert all(abs(g - INTERVAL_MS) < 1.0 for g in gaps_ms)   # no catch-up burst


def test_backward_playback_waits_for_the_frames_behind(clock):
    behind = {99, 98}
    buffer = FakeBuffer(set(range(0, 1000)) - behind)
    app = _play_app(clock, buffer=buffer)
    app._start_playback(-1)
    _run(app, clock, 3)
    assert app.advances == []

    buffer.frames |= behind
    _run(app, clock, 2)
    assert [f for f, d, _ in app.advances] == [99, 98]
    assert all(d == -1 for _, d, _ in app.advances)


@pytest.mark.parametrize("start,direction", [(999, 1), (0, -1)])
def test_playback_stops_at_the_edge_it_moves_toward(clock, start, direction):
    app = _play_app(clock, current_frame=start)
    app._start_playback(direction)

    assert app.play is False
    assert app.advances == [] and app.scheduled == []


def test_stop_ends_the_chain_at_the_next_tick(clock):
    app = _play_app(clock)
    app._start_playback(1)
    _run(app, clock, 2)
    app.stop_video()
    _run(app, clock, 5)

    assert [f for f, _, _ in app.advances] == [101, 102, 103]
    assert app.scheduled == [] and app._play_tick_id is None


def test_starting_twice_keeps_a_single_tick_chain(clock):
    app = _play_app(clock)
    app._start_playback(1)
    app._start_playback(1)   # e.g. Play pressed while already playing

    assert len(app.scheduled) == 1


def test_playback_ends_when_the_video_goes_away(clock):
    app = _play_app(clock)
    app._start_playback(1)
    app.video = None          # the project was unloaded mid-playback
    _run(app, clock, 1)

    assert app.play is False and app.scheduled == []


def test_pacing_stays_exact_when_the_monotonic_clock_is_coarse(windows_clock):
    # Regression: deadlines computed from time.monotonic() were quantized to
    # Windows' 15.6 ms tick, so 25 fps steps alternated between ~31 and ~47 ms.
    app = _play_app(windows_clock, redraw_s=0.007)
    app._start_playback(1)
    _run(app, windows_clock, 12)

    gaps_ms = [(b - a) * 1000 for (_, _, a), (_, _, b) in zip(app.advances, app.advances[1:])]
    assert gaps_ms and all(abs(g - INTERVAL_MS) < 1.0 for g in gaps_ms), gaps_ms


def test_precise_timers_are_held_exactly_while_playback_runs(clock):
    app = _play_app(clock)
    app._start_playback(1)
    _run(app, clock, 3)
    assert app._precise_timers.holders == {"playback"}

    app.stop_video()
    _run(app, clock, 1)
    assert app._precise_timers.holders == set()


def test_precise_timers_are_released_at_the_boundary(clock):
    app = _play_app(clock, current_frame=997)
    app._start_playback(1)
    _run(app, clock, 5)                       # 998, 999, then the edge
    assert app.play is False
    assert app._precise_timers.holders == set()
