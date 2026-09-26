"""
adapters/timer_resolution.py
Precise Tk timers on Windows while the app paces frames.

Tk's `after(ms)` waits with a millisecond timeout that Windows rounds to its
system timer tick — 15.6 ms by default — so 40 ms playback steps come out as
~31 / ~47 ms (measured). `timeBeginPeriod(1)` raises this process's timer
resolution to 1 ms for as long as it is held (per process since Windows 10
2004); video players and browsers do the same while playing. It costs a
little power, so it is held only while something is actually paced frame by
frame (playback, wheel scrolling) and released right after.

On other platforms Tk's timers are already precise (select/poll with
microsecond timeouts), so this is a no-op there.
"""

import logging
import sys

logger = logging.getLogger(__name__)

PRECISE_TIMER_MS = 1
_TIMERR_NOERROR = 0


def _load_winmm():
    import ctypes

    return ctypes.WinDLL("winmm")


class PreciseTimers:
    """1 ms timer resolution while at least one named holder wants it.

    Holders are names ("playback", "wheel"), so one user stopping cannot
    drop the precision another one still needs. Every method is idempotent
    and never raises: if the OS refuses, timers simply stay coarse.
    """

    def __init__(self, winmm=None):
        self._winmm = winmm       # injectable for tests; loaded lazily on Windows
        self._holders = set()
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def hold(self, holder):
        self._holders.add(holder)
        if not self._active:
            self._activate()

    def release(self, holder):
        self._holders.discard(holder)
        if self._active and not self._holders:
            self._deactivate()

    def release_all(self):
        self._holders.clear()
        if self._active:
            self._deactivate()

    def _api(self):
        if self._winmm is None and sys.platform == "win32":
            try:
                self._winmm = _load_winmm()
            except OSError as exc:
                logger.debug("precise timers unavailable: %s", exc)
                self._winmm = False
        return self._winmm or None

    def _activate(self):
        api = self._api()
        if api is None:
            return
        result = api.timeBeginPeriod(PRECISE_TIMER_MS)
        if result == _TIMERR_NOERROR:
            self._active = True
            logger.debug("precise timers on (%d ms)", PRECISE_TIMER_MS)
        else:
            logger.debug("timeBeginPeriod(%d) refused: %s", PRECISE_TIMER_MS, result)

    def _deactivate(self):
        self._winmm.timeEndPeriod(PRECISE_TIMER_MS)
        self._active = False
        logger.debug("precise timers off")
