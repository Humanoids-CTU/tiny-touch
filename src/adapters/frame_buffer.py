"""
adapters/frame_buffer.py
The frame read-ahead buffer, extracted from LabelingApp (background_update
and the buffer store/evict helpers). NO Tk imports here, and all app state
the worker threads need arrives through the injected context provider.
Playback pacing is not here any more: it runs on the Tk thread
(`LabelingApp._play_tick`, SMOOTHNESS_PLAN.md step 3).

Threading invariants:
  (a) one RLock (`_lock`) guards the four buffer structures
      (frame dict, byte-size dict, byte total, in-flight map);
  (b) `reset()` bumps the generation counter so in-flight decodes started
      under the old video/settings discard their result;
  (c) the buffering thread and the decode pool never call into the GUI —
      not even to schedule work there. They only fill the buffer; the GUI
      polls it from its own event loop (`LabelingApp._display_pump`,
      `LabelingApp._play_tick`). Reason: a worker's `Tk.after()` is a
      synchronous round-trip that waits for the Tk thread, so every slow
      repaint used to stall buffering (SMOOTHNESS_PLAN.md step 2);
  (d) a frame is decoded at most once: the synchronous priority path
      (`_load_priority`) cancels a queued pool decode of the same frame or
      waits for a running one instead of decoding it again.
"""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from threading import Event, RLock
from typing import Callable, NamedTuple

from PIL import Image


logger = logging.getLogger(__name__)

# Frames past the current one (in the play direction) that must be buffered
# before playback advances — it stalls briefly rather than stutters. Also the
# look-ahead behind `FrameBuffer.buffer_ready`.
PLAYBACK_BUFFER_AHEAD = 3
BUFFER_MAX_BYTES = 1_000_000_000
# Upper bound on how long a priority load waits for a pool decode of the same
# frame that is already running (normally 5-40 ms). Past it we decode ourselves.
PRIORITY_WAIT_S = 1.0


def compute_target_size(orig_w, orig_h, display_w, display_h, downscale):
    """Pure fit-box sizing rule shared by the decode path and `resize_for_buffer`.

    Target box = (display_w, display_h) / downscale; the source is fit into it
    aspect-preserving with scale = min(box_w/orig_w, box_h/orig_h). Unlike the
    old rule, scale > 1 is ALLOWED (upscale) so a low-res video fills a big
    monitor — the upscale happens here, in the worker decode path, because
    paint-time upscaling on the UI thread blows the 40 ms playback budget.
    Degenerate display dims (<= 0) return the original size unchanged;
    downscale <= 0 is treated as 1.0 (both mirror the old guards).
    """
    if display_w <= 0 or display_h <= 0 or orig_w <= 0 or orig_h <= 0:
        return orig_w, orig_h
    if downscale <= 0:
        downscale = 1.0
    box_w = max(1, int(display_w / downscale))
    box_h = max(1, int(display_h / downscale))
    aspect_ratio = orig_w / orig_h
    if box_w / box_h > aspect_ratio:
        return max(1, int(box_h * aspect_ratio)), box_h
    return box_w, max(1, int(box_w / aspect_ratio))


def resize_for_buffer(img, display_width, display_height, downscale):
    """Tk-free fit-box resize used by worker threads. Pure CPU work — no widget calls.

    Now upscales as well as downscales (see `compute_target_size`), and uses
    BILINEAR instead of LANCZOS: measured RMS drift < 1.6/255 (invisible) for
    ~1.5-3.7x faster end-to-end decode (tests/perf/benchmark_decode_pipeline.py).
    """
    target = compute_target_size(
        img.width, img.height, display_width, display_height, downscale
    )
    if target == img.size:
        return img
    return img.resize(target, Image.Resampling.BILINEAR)


class BufferContext(NamedTuple):
    """Per-tick snapshot of app state the buffering thread needs.
    Built ON DEMAND by the injected provider so the engine never reaches
    into the GUI object graph."""
    frames_dir: str
    current_frame: int
    total_frames: int
    display_w: int
    display_h: int
    downscale: float
    jump_frame_count: int
    last_step_sign: int


class _NullPerf:
    """No-op stand-in for PerfLogger when none is injected."""

    def time(self, name):
        return nullcontext()

    def record(self, name, dt):
        pass


class FrameBuffer:
    """Sliding-window JPEG frame buffer.

    Constructed with config values only; the frames directory and all
    per-video numbers arrive via the context provider because they change on
    every video load. The GUI learns about newly decoded frames by polling
    (`get` / `in` / `buffer_ready`), never by callback.
    """

    def __init__(
        self,
        *,
        get_buffer_context: Callable,
        max_bytes: int = BUFFER_MAX_BYTES,
        playback_buffer_ahead: int = PLAYBACK_BUFFER_AHEAD,
        perf=None,
    ):
        self._get_buffer_context = get_buffer_context        # () -> BufferContext | None

        # Config values.
        self._max_bytes = max_bytes
        self._playback_ahead = playback_buffer_ahead
        self._perf = perf if perf is not None else _NullPerf()

        # Buffer structures — ALL guarded by the one RLock.
        self._lock = RLock()
        self._buffer = {}            # frame index -> decoded/resized PIL image
        self._buffer_bytes = {}      # frame index -> estimated byte size
        self._buffer_total = 0       # running byte total
        self._inflight = {}          # frame index -> Future (pool decode) or
                                     # None (synchronous priority load / a pool
                                     # submission whose Future isn't stored yet)
        self._gen = 0                # bumps on reset() to discard stale decodes

        # Priority-load + parallel-prefetch infrastructure. Pool size adapts
        # to the machine: PIL releases the GIL during decode/resize, so extra
        # workers give real parallelism (~1.4-1.5x window-fill throughput at
        # 6-8 workers on a 16-core box vs the old fixed 3).
        self._priority_frame = None
        self._priority_event = Event()
        pool_workers = max(3, min(8, (os.cpu_count() or 4) // 2))
        logger.debug(
            "frame_buffer: decode pool starting with %d workers (cpu_count=%s)",
            pool_workers,
            os.cpu_count(),
        )
        self._loader_pool = ThreadPoolExecutor(
            max_workers=pool_workers, thread_name_prefix="frame-loader"
        )
        # Last byte-aware window cap, for change-only logging (the buffering
        # loop ticks every 10 ms — logging each tick would flood the console).
        self._last_window_cap = None

        # True while the current frame and the next PLAYBACK_BUFFER_AHEAD
        # frames are buffered; written by the buffering thread only.
        self.buffer_ready = False

        # Shutdown latch. The buffering loop polls it, so `shutdown()`
        # actually ENDS it instead of leaving it spinning after the Tk root
        # is gone (see shutdown()).
        self._stopped = Event()

    # === Buffer access (UI thread) ============================================
    def __contains__(self, frame_number) -> bool:
        return frame_number in self._buffer

    def get(self, frame_number):
        """The decoded PIL image for `frame_number`, or None if not buffered."""
        return self._buffer.get(frame_number)

    def request_priority(self, frame_number):
        """Hint the buffering thread to load `frame_number` ASAP (jump target)."""
        with self._lock:
            self._priority_frame = frame_number
        self._priority_event.set()

    def _take_priority(self):
        """Read and clear the priority hint in one step. Two separate
        statements would lose a hint the UI thread writes between them."""
        with self._lock:
            priority, self._priority_frame = self._priority_frame, None
        return priority

    def poke(self):
        """Wake the buffering thread early (current frame missing from cache)."""
        self._priority_event.set()

    def reset(self):
        # Lock so concurrent workers can't store into a half-cleared buffer.
        # Bumps the generation so any in-flight worker decoded under the OLD
        # video/settings discards its result instead of polluting the new buffer.
        with self._lock:
            self._buffer.clear()
            self._buffer_bytes.clear()
            self._buffer_total = 0
            self._inflight.clear()
            self._gen += 1

    @property
    def stopped(self) -> bool:
        """True once `shutdown()` was called — the buffering loop is winding down."""
        return self._stopped.is_set()

    def shutdown(self, *, wait=False, cancel_futures=True):
        """Stop the buffering loop, then the loader pool.

        The latch is set FIRST and the buffering thread is woken immediately,
        so the loop ends promptly (the app calls this from `on_close()` one
        line before `destroy()`).
        """
        self._stopped.set()
        self._priority_event.set()  # break the 10 ms wait right away
        self._loader_pool.shutdown(wait=wait, cancel_futures=cancel_futures)

    # === Buffering thread =====================================================
    def background_update(self):
        while not self._stopped.is_set():
            # Sleep up to 10 ms unless a jump pokes us awake earlier.
            self._priority_event.wait(timeout=0.01)
            self._priority_event.clear()
            if self._stopped.is_set():
                return
            ctx = self._get_buffer_context()
            if ctx is None:
                continue
            with self._perf.time("background_update"):
                current_frame = ctx.current_frame
                if current_frame < 0 or current_frame > ctx.total_frames:
                    # Transiently possible around a video reload (old position
                    # against new total). Skip the tick — never `return`: that
                    # would kill this daemon permanently, and a Thread cannot
                    # be restarted.
                    continue

                # Per-tick context captured once (the provider reads the
                # geometry cache maintained on the main thread — H1).
                frames_dir = ctx.frames_dir
                display_w = ctx.display_w
                display_h = ctx.display_h
                downscale = ctx.downscale
                gen = self._gen

                # 1) Load the currently-visible frame first (synchronously) so the
                #    user sees their jump destination ASAP. The GUI's display
                #    pump notices it in the buffer and paints it.
                if current_frame not in self._buffer:
                    with self._perf.time("priority_load"):
                        self._load_priority(
                            current_frame, frames_dir, display_w, display_h, downscale, gen
                        )
                current_frame_loaded = current_frame in self._buffer

                # 2) Honour an explicit priority hint (e.g. _request_buffered_step
                #    polling pre-loads the jump target before next_frame() is called).
                priority = self._take_priority()
                if (priority is not None
                        and priority != current_frame
                        and 0 <= priority <= ctx.total_frames
                        and priority not in self._buffer):
                    with self._perf.time("priority_load"):
                        self._load_priority(
                            priority, frames_dir, display_w, display_h, downscale, gen
                        )

                # 3) Asymmetric, velocity-aware prefetch window. Same direction as
                #    the user's last navigation step gets a wider lookahead so a
                #    second jump in that direction lands in cache.
                base_ahead, base_behind = 50, 30
                jump = max(1, ctx.jump_frame_count)
                sign = ctx.last_step_sign
                if sign > 0:
                    ahead = max(base_ahead, jump * 2)
                    behind = max(10, base_behind // 2)
                elif sign < 0:
                    ahead = max(10, base_ahead // 2)
                    behind = max(base_behind, jump * 2)
                else:
                    ahead, behind = base_ahead, base_behind

                # 3a) Byte-aware window cap. Upscaled frames can be huge (a 4K
                #     canvas frame is ~25 MB), so the full 80-frame window can
                #     exceed the byte budget — the evictor then deletes what
                #     this loop immediately resubmits (infinite decode churn).
                #     Cap the window at roughly HALF the budget and shrink
                #     ahead/behind proportionally; the eviction keep-range in
                #     step 5 scales from the shrunken values, so trim/evict
                #     never fight the submission loop.
                if self._max_bytes and self._max_bytes > 0:
                    with self._lock:
                        if self._buffer:
                            est_frame_bytes = max(
                                1, self._buffer_total // len(self._buffer)
                            )
                        else:
                            est_frame_bytes = max(1, display_w * display_h * 3)
                    max_window_frames = max(
                        self._playback_ahead + 2,
                        (self._max_bytes // est_frame_bytes) // 2,
                    )
                    window_frames = ahead + behind
                    if window_frames > max_window_frames:
                        shrink = max_window_frames / window_frames
                        ahead = max(self._playback_ahead + 1, int(ahead * shrink))
                        behind = max(1, int(behind * shrink))
                        if self._last_window_cap != max_window_frames:
                            self._last_window_cap = max_window_frames
                            logger.debug(
                                "frame_buffer: prefetch window capped to %d frames "
                                "(~%.1f MB/frame, budget %.0f MB) — ahead=%d, behind=%d",
                                max_window_frames,
                                est_frame_bytes / 1e6,
                                self._max_bytes / 1e6,
                                ahead,
                                behind,
                            )
                    else:
                        self._last_window_cap = None
                start_frame = max(0, current_frame - behind)
                end_frame = min(ctx.total_frames, current_frame + ahead)

                # 3b) Cancel queued decodes that fell OUTSIDE the new window (a
                #     jump leaves the pool's FIFO queue full of old-window
                #     decodes — measured jump p95 was ~1.1-1.3 s because the
                #     jump target queued behind them). Only queued-not-started
                #     futures cancel; running ones return False and are left
                #     alone (they'll discard themselves from _inflight when
                #     they finish). Cancelled frames MUST leave _inflight, or
                #     they'd never be re-submitted.
                cancelled = 0
                with self._lock:
                    stale = [
                        (f, fut) for f, fut in self._inflight.items()
                        if (f < start_frame or f > end_frame) and fut is not None
                    ]
                    for f, fut in stale:
                        if fut.cancel():
                            self._inflight.pop(f, None)
                            cancelled += 1
                if cancelled:
                    logger.debug(
                        "frame_buffer: cancelled %d stale prefetch decodes outside "
                        "[%d, %d] (current_frame=%d)",
                        cancelled,
                        start_frame,
                        end_frame,
                        current_frame,
                    )

                # 4) Submit prefetch loads to the worker pool. Forward window first
                #    (most likely direction of travel), then backward.
                for i in range(current_frame + 1, end_frame + 1):
                    self._maybe_submit_load(
                        i, ctx.total_frames, frames_dir, display_w, display_h, downscale, gen
                    )
                for i in range(current_frame - 1, start_frame - 1, -1):
                    self._maybe_submit_load(
                        i, ctx.total_frames, frames_dir, display_w, display_h, downscale, gen
                    )

                # 5) Trim out-of-range frames + enforce the byte budget. Hard cap
                #    scales with the asymmetric window so a wide forward prefetch
                #    isn't immediately undone.
                buffer_range_behind = max(200, behind * 4)
                buffer_range_ahead = max(200, ahead * 4)
                min_keep = max(0, current_frame - buffer_range_behind)
                max_keep = min(ctx.total_frames, current_frame + buffer_range_ahead)
                with self._lock:
                    frames_to_remove = [k for k in self._buffer if k < min_keep or k > max_keep]
                    for k in frames_to_remove:
                        self._remove_frame(k)
                    self._evict_to_budget(current_frame)

                # 6) buffer_ready: the window ahead is decoded (status for the GUI).
                buffer_ready = current_frame_loaded
                if buffer_ready:
                    max_check = min(ctx.total_frames, current_frame + self._playback_ahead)
                    for i in range(current_frame, max_check + 1):
                        if i not in self._buffer:
                            buffer_ready = False
                            break
                self.buffer_ready = buffer_ready

    # === Decode / store / evict ==============================================
    def _load_priority(self, frame_number, frames_dir, display_w, display_h, downscale, gen):
        """Get `frame_number` into the buffer NOW, without decoding it twice.

        Runs on the buffering thread for the current frame and the priority
        hint. If the pool already holds a decode of this frame:
          - still QUEUED  -> cancel it and decode here (jump the FIFO queue);
          - already RUNNING -> wait for it; it finishes sooner than a fresh
            decode would. Only if it fails, is discarded (buffer reset) or
            exceeds PRIORITY_WAIT_S do we decode here after all.
        Every `_inflight` entry the buffering thread can see here is a Future:
        the only other writer, `_maybe_submit_load`, runs on this same thread
        and stores its Future before returning.
        """
        with self._lock:
            if frame_number in self._buffer:
                return
            future = self._inflight.get(frame_number)
            if future is not None and future.cancel():
                self._inflight.pop(frame_number, None)
                future = None
        if future is not None:
            try:
                future.result(timeout=PRIORITY_WAIT_S)
            except Exception:
                pass  # timeout / failure: fall through to our own decode
            if frame_number in self._buffer:
                return
        self._load_frame_to_buffer(
            frame_number, frames_dir, display_w, display_h, downscale, gen
        )

    def _load_frame_to_buffer(self, frame_number, frames_dir, display_w, display_h, downscale, gen):
        """Disk read + JPEG decode + resize + buffer store. Safe to run on any thread.

        The target size is computed from the ORIGINAL dimensions (Image.open
        reads .size from the header, no decode yet) so `draft()` can tell
        libjpeg to decode at a reduced DCT scale (1/2, 1/4, 1/8) whenever the
        source is larger than the target — draft only works pre-load and only
        on JPEGs, which is exactly what the frames dir holds. The (much
        smaller) decoded image then gets one cheap BILINEAR resize, skipped
        entirely when draft already landed on the exact target size.

        Stores the result only if the buffer generation still matches (gen == self._gen),
        i.e. no reset() happened mid-decode. Always discards from the in-flight map
        (registering itself with a None entry on the synchronous priority path).
        """
        with self._lock:
            self._inflight.setdefault(frame_number, None)
        started = time.perf_counter()
        try:
            with self._perf.time("load_frame_total"):
                frame_path = os.path.join(frames_dir, f"frame{frame_number}.jpg")
                with self._perf.time("load_frame_open"):
                    with Image.open(frame_path) as opened:
                        target = compute_target_size(
                            *opened.size, display_w, display_h, downscale
                        )
                        opened.draft("RGB", target)
                        img = opened.copy()
                with self._perf.time("load_frame_resize"):
                    if img.size != target:
                        img = img.resize(target, Image.Resampling.BILINEAR)
                try:
                    bytes_per_pixel = max(1, len(img.getbands()))
                except Exception:
                    bytes_per_pixel = 4
                est_bytes = int(img.width * img.height * bytes_per_pixel)
                with self._lock:
                    duplicate = frame_number in self._buffer
                    if gen == self._gen:
                        self._store_frame(frame_number, img, est_bytes)
                    self._inflight.pop(frame_number, None)
                if duplicate:
                    # Another decode of the same frame finished first; this
                    # one was wasted work (perf metric M8).
                    self._perf.record("duplicate_decode", time.perf_counter() - started)
        except Exception:
            with self._lock:
                self._inflight.pop(frame_number, None)
            logger.exception("Opening or processing frame %s", frame_number)

    def _maybe_submit_load(self, frame_number, total_frames, frames_dir, display_w, display_h, downscale, gen):
        """Submit a prefetch load to the worker pool, deduping against in-flight + cached frames.

        The Future is kept in `_inflight` so `background_update` can cancel
        queued decodes that a jump left outside the new prefetch window."""
        if frame_number < 0 or frame_number > total_frames:
            return
        with self._lock:
            if frame_number in self._buffer or frame_number in self._inflight:
                return
            self._inflight[frame_number] = None  # reserve before releasing the lock
        try:
            future = self._loader_pool.submit(
                self._load_frame_to_buffer,
                frame_number, frames_dir, display_w, display_h, downscale, gen,
            )
        except RuntimeError:
            # Pool was shut down (e.g. on app close); back out the inflight reservation.
            with self._lock:
                self._inflight.pop(frame_number, None)
            return
        with self._lock:
            # Store the Future for cancellation — unless the decode already
            # finished and removed its own entry (don't resurrect it).
            if frame_number in self._inflight and self._inflight[frame_number] is None:
                self._inflight[frame_number] = future

    def _remove_frame(self, frame_number):
        with self._lock:
            if frame_number in self._buffer:
                del self._buffer[frame_number]
            removed = self._buffer_bytes.pop(frame_number, 0)
            self._buffer_total = max(0, self._buffer_total - removed)

    def _store_frame(self, frame_number, img, est_bytes):
        with self._lock:
            if frame_number in self._buffer_bytes:
                self._buffer_total = max(0, self._buffer_total - self._buffer_bytes.get(frame_number, 0))
            self._buffer[frame_number] = img
            self._buffer_bytes[frame_number] = est_bytes
            self._buffer_total = self._buffer_total + est_bytes

    def _evict_to_budget(self, current_frame):
        limit = self._max_bytes
        if limit is None or limit <= 0:
            return
        with self._lock:
            if self._buffer_total <= limit:
                return
            candidates = sorted(self._buffer.keys(), key=lambda k: abs(k - current_frame), reverse=True)
            for k in candidates:
                if k == current_frame:
                    continue
                self._remove_frame(k)
                if self._buffer_total <= limit:
                    break
