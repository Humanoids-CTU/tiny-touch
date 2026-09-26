"""`PreciseTimers`: 1 ms Windows timer resolution while any holder needs it."""

from adapters.timer_resolution import PRECISE_TIMER_MS, PreciseTimers


class FakeWinmm:
    def __init__(self, begin_result=0):
        self.calls = []
        self.begin_result = begin_result

    def timeBeginPeriod(self, ms):
        self.calls.append(("begin", ms))
        return self.begin_result

    def timeEndPeriod(self, ms):
        self.calls.append(("end", ms))
        return 0


def test_resolution_is_raised_once_and_restored_when_the_last_holder_leaves():
    winmm = FakeWinmm()
    timers = PreciseTimers(winmm)

    timers.hold("playback")
    timers.hold("wheel")
    timers.hold("playback")
    timers.release("playback")
    assert winmm.calls == [("begin", PRECISE_TIMER_MS)]   # the wheel still needs it
    assert timers.active

    timers.release("wheel")
    assert winmm.calls == [("begin", PRECISE_TIMER_MS), ("end", PRECISE_TIMER_MS)]
    assert not timers.active


def test_releasing_without_holding_changes_nothing():
    winmm = FakeWinmm()
    timers = PreciseTimers(winmm)
    timers.release("wheel")
    timers.release_all()
    assert winmm.calls == []


def test_release_all_restores_the_resolution():
    winmm = FakeWinmm()
    timers = PreciseTimers(winmm)
    timers.hold("playback")
    timers.hold("wheel")
    timers.release_all()
    assert winmm.calls[-1] == ("end", PRECISE_TIMER_MS)
    assert not timers.active


def test_a_refused_request_leaves_timers_coarse_without_an_unbalanced_end():
    winmm = FakeWinmm(begin_result=97)   # TIMERR_NOCANDO
    timers = PreciseTimers(winmm)
    timers.hold("playback")
    timers.release("playback")
    assert winmm.calls == [("begin", PRECISE_TIMER_MS)]
    assert not timers.active


def test_it_is_a_no_op_off_windows(monkeypatch):
    monkeypatch.setattr("adapters.timer_resolution.sys.platform", "linux")
    timers = PreciseTimers()
    timers.hold("playback")
    assert not timers.active
    timers.release("playback")
