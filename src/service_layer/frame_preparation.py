"""One cancellable extraction worker; progress is polled by the UI thread."""
from concurrent.futures import Future
from threading import Event, Lock, Thread

from adapters.frame_extractor import FrameExtractionCancelled


class FramePreparationJob:
    def __init__(self, extract):
        self.cancel_event = Event()
        self._extract = extract
        self._result = Future()
        self._progress = None
        self._lock = Lock()
        # Shutdown waits for cleanup before destroying the application.
        self.thread = Thread(target=self._run, name="frame-preparation")

    @property
    def progress(self):
        with self._lock:
            return self._progress

    def _report(self, *progress):
        with self._lock:
            self._progress = progress

    def _run(self):
        try:
            result = self._extract(progress_cb=self._report, cancel_event=self.cancel_event)
            if self.cancel_event.is_set():
                raise FrameExtractionCancelled("Frame extraction cancelled.")
        except Exception as exc:
            self._result.set_exception(exc)
        else:
            self._result.set_result(result)

    def start(self):
        self.thread.start()

    def cancel(self):
        self.cancel_event.set()

    def result(self):
        try:
            result = self._result.result()
        except Exception:
            if self.cancel_event.is_set():
                raise FrameExtractionCancelled("Frame extraction cancelled.") from None
            raise
        if self.cancel_event.is_set():
            raise FrameExtractionCancelled("Frame extraction cancelled.")
        return result
