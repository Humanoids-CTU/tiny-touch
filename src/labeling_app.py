import os
import sys
import time
import webbrowser
import logging
import sqlite3
from contextlib import contextmanager
from threading import Thread, Event, get_ident, current_thread

import keyboard
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk

from adapters import config
from adapters import video_probe
from adapters.frame_buffer import (
    PLAYBACK_BUFFER_AHEAD, BufferContext, FrameBuffer, GpuFrame, compute_target_size,
    resize_for_buffer,
)
from adapters.frame_extractor import FrameExtractionCancelled, FrameExtractionError
from adapters.timer_resolution import PreciseTimers
from adapters.channel_diagram import render_channel_diagram
from adapters.zone_masks import load_zone_masks, editable_zone_names, zone_label_positions
from domain.playback import compute_play_step
from gui.timeline_geometry import timeline_click_frame
from gui import timeline
from domain.model import (
    LIMBS,
    FrameRecord,
    bundle_summary_str,
    preview_lines_for_save,
)
from domain.project import ProjectPaths
from domain.touch import NO_ZONE, find_last_open_onset, find_open_touches, zones_at
from domain.templates import DEFAULT_TEMPLATE, get_template
from domain.pose import ZoneEvent, Navigation
from domain.pose_export import special_zone_ids
from gui.pose_panel import PosePanel
from domain.pose_timeline import PoseTimelineIndex
from gui.pose_timeline import (PoseTimelineView, POSE_DETAIL_HEIGHT, POSE_OVERVIEW_HEIGHT,
                               POSE_DETAIL_FLUSH_INTERVAL_S)
from domain.zone_display import ZoneDisplaySettings
from gui import theme
from gui import widgets
from gui import window_reveal
from gui import content_swap
from gui import app_dialogs
from gui.app_dialogs import (center_over_parent, custom_confirm_close, confirm_discard,
                             CLOSE_SAVE, CLOSE_DISCARD)
from gui.video_surface import GpuVideoSurface, VideoRendererError, rounded_corner_mask
from gui.special_zones_app import SpecialZonesApp, DEFAULT_SPECIAL_ZONES_DIAGRAM_SCALE
from gui.frame_dialog import FrameDialog
from gui.open_touches_dialog import (
    OpenTouchesDialog, GO_TO_ONSET, ANALYZE_ANYWAY, SAVE_AND_CLOSE, DISCARD_AND_CLOSE,
)
from gui.template_dialog import choose_template, template_diagram
from gui.video_library import choose_video, choose_existing_video
from service_layer.project_copy import next_copy_project
from gui.coding_setup_wizard import configure_video
from gui.pose_setup_wizard import configure_pose_video, choose_annotation_type
from adapters.project_catalog import find_resumable, list_projects, SOURCE_META
from adapters.sqlite_repo import SqliteRepository
from gui.zone_names_dialog import edit_zone_names
from gui.zone_labels import draw_zone_labels
from gui.diagram_highlight import DiagramHighlighter
from resource_utils import asset_path
from gui.ui_components import (CARD_CONTENT_PAD, build_ui, draw_startup_diagram, sync_play_control,
                               align_timeline_to_video, max_diagram_scale, TIMELINE_HEIGHT, TIMELINE2_HEIGHT,
                               diagram_native_size, fit_diagram_to_column)
from gui.diagram_resize import clamp_scale
from gui.video_overlay import BADGE_INSET
from log_setup import open_logs_folder
from perf_utils import PerfLogger
from service_layer import (analysis_service, annotation_service, pose_export_service,
                           project_service, save_service)
from service_layer.project_service import LabelingTimer
from service_layer.save_service import SaveOutcome
from service_layer.frame_preparation import FramePreparationJob
from video_model import Video


logger = logging.getLogger(__name__)
annotation_logger = logging.getLogger("annot")


# =============================================================================
# Constants
# =============================================================================
# Keep taps precise without waiting for the operating system's repeat delay.
ARROW_HOLD_DELAY_MS = 150
# Mouse-wheel navigation. Notches are queued and consumed one frame per video
# frame interval, so a fast flick moves at playback speed (like holding an
# arrow key) instead of racing the redraw. The queue is capped at
# WHEEL_BACKLOG_S worth of frames so motion stops shortly after the wheel does.
# WHEEL_NOTCH_DELTA is Tk's <MouseWheel> delta for one notch on Windows;
# high-resolution wheels report fractions of it, which are accumulated.
WHEEL_BACKLOG_S = 0.2
WHEEL_NOTCH_DELTA = 120
WHEEL_DEFAULT_INTERVAL_MS = 40
WHEEL_BUFFER_POLL_MS = 50
# How often the Tk thread polls the frame buffer for a newly decoded current
# frame (LabelingApp._display_pump). Workers never call Tk, so this poll is
# how background decodes reach the screen; 10 ms is below one video frame.
DISPLAY_PUMP_MS = 10
FRAME_PREPARATION_POLL_MS = 50
# A video load swaps the main window's content behind a cover (gui.content_swap)
# until the new video's first frame is painted, but never longer than this.
LOAD_FIRST_FRAME_TIMEOUT_MS = 1500
# Playback runs on the Tk thread (LabelingApp._play_tick), paced against a
# running deadline like the wheel. When the next PLAYBACK_BUFFER_AHEAD frames
# are not decoded yet it re-checks every PLAYBACK_STALL_POLL_MS: a cheap
# dict lookup on the Tk thread, so it can poll much faster than the old
# thread's 150 ms sleep and resume as soon as the frames land.
PLAYBACK_STALL_POLL_MS = 20
# Video frames follow source FPS; annotation controls need fewer repaints.
PLAYBACK_UI_INTERVAL_S = 1.0 / 25.0
# Timeline playheads move at most at a typical monitor refresh: a move the
# screen cannot show still costs Tk ~1-1.5 ms of GDI repaint per timeline
# beside the GPU video (measured), most of a 100 FPS frame budget. Videos at
# or below 60 FPS keep a playhead move on every frame (the jitter allowance).
PLAYBACK_PLAYHEAD_INTERVAL_S = 1.0 / 60.0
PLAYBACK_PLAYHEAD_JITTER_S = 0.003
# Recover ordinary event-loop jitter without accumulating unlimited catch-up
# work after a long pause. Every callback still advances at most one frame.
PLAYBACK_MAX_LAG_S = 0.25
# A video-panel resize rebuilds the frame buffer only after no new size has
# arrived for this long (LabelingApp.on_resize). Longer than the gap between
# <Configure> events of a window-edge drag (~16 ms) and the perf scenario's
# 50 ms resize steps; every extra millisecond delays the sharp frame.
RESIZE_SETTLE_MS = 100
# What the user is told when a save did not fully reach disk (save_service.SaveOutcome).
EXPORT_STALE_MESSAGE = (
    "Your annotations are saved, but the export files (CSV, metadata and diagram) "
    "could not be updated and are out of date.\n\n"
    "Close the CSV in other programs (for example Excel) and save again. "
    "Details are in the log."
)
# Pose publishes a CSV and metadata only (no diagram).
POSE_EXPORT_STALE_MESSAGE = (
    "Your annotations are saved, but the Pose export files (CSV and metadata) "
    "could not be updated and are out of date.\n\n"
    "Close the CSV in other programs (for example Excel) and save again. "
    "Details are in the log."
)
NOT_SAVED_MESSAGE = (
    "Your latest changes were NOT saved to disk. Details are in the log.\n\n"
    "Try Save again before closing the video."
)
# Title of the progress windows shown while a video is opened.
LOAD_PROGRESS_TITLE = "Loading Video"
UNLOAD_SAVE_FAILED_MESSAGE = (
    "Saving the current video failed (see the log).\n"
    "The new video was NOT loaded, so nothing is lost."
)


def _export_stale_message(app):
    """The out-of-date export text for the open project's annotation type."""
    return (POSE_EXPORT_STALE_MESSAGE if getattr(app, "annotation_type", "Touch") == "Pose"
            else EXPORT_STALE_MESSAGE)


def _report_save_outcome(parent, outcome):
    """Tell the user about a save that did not fully reach disk."""
    if outcome is SaveOutcome.EXPORT_STALE:
        messagebox.showwarning("Export not updated", _export_stale_message(parent), parent=parent)
    elif outcome is SaveOutcome.NOT_SAVED:
        messagebox.showerror("Save failed", NOT_SAVED_MESSAGE, parent=parent)


def count_unsaved_frames(frames) -> int:
    """Frames edited since the last save (`Changed` is the dirty tracker)."""
    return sum(1 for bundle in frames.values() if isinstance(bundle, dict) and bundle.get("Changed"))


def format_counter_time(ms, total_ms):
    """`ms` as S.mmm, M:SS.mmm or H:MM:SS.mmm, chosen by the video's length `total_ms`."""
    hours, remainder = divmod(ms, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, milliseconds = divmod(remainder, 1000)
    if total_ms >= 3600000:
        return f"{hours}:{minutes:02}:{seconds:02}.{milliseconds:03}"
    if total_ms >= 60000:
        return f"{minutes + 60 * hours}:{seconds:02}.{milliseconds:03}"
    return f"{seconds + 60 * minutes}.{milliseconds:03}"


# Rounded corners of the shown video frame (design px; CPU and GPU paths).
VIDEO_CORNER_RADIUS = 12
# Canvas tag of the per-frame dots on the diagram, so a frame change can
# replace just them and leave the limb image and zone labels alone.
DIAGRAM_DOT_TAG = "dot"
# Dev guard (H1): when True, the main render/timeline methods raise if called
# off the Tk main thread, so any future thread-boundary regression fails loudly
# at the offending call site instead of crashing Tcl intermittently.
DEBUG_ASSERT_UI_THREAD = False
# Progress / export windows (design px, scaled with theme.px).
PROGRESS_WINDOW_W = 520
PROGRESS_WINDOW_H = 150
EXPORT_WINDOW_H = 160
PROGRESS_BAR_LENGTH = 460
EXPORT_STATUS_SLACK_CHARS = 4  # room for a longer elapsed time (h:mm:ss) without a resize
PROGRESS_TIME_WIDTH = 5  # characters reserved for "m:ss"/"mm:ss"; hours just grow it

# =============================================================================
# Standalone helpers
# =============================================================================
@contextmanager
def center_native_file_dialog(parent):
    """Center the Windows common file dialog that belongs to *parent*.

    Tk exposes no geometry option for its native Windows file picker.  A
    temporary WinEvent hook lets us position only the picker owned by this app;
    on non-Windows platforms the native Tk behavior remains untouched.
    """
    if os.name != "nt":
        yield
        return

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        event_object_show = 0x8002
        ga_rootowner = 3
        winevent_outofcontext = 0
        swp_nosize = 0x0001
        swp_nozorder = 0x0004
        swp_noactivate = 0x0010
        parent_handle = parent.winfo_id()
        process_id = os.getpid()

        callback_type = ctypes.WINFUNCTYPE(
            None,
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.HWND,
            wintypes.LONG,
            wintypes.LONG,
            wintypes.DWORD,
            wintypes.DWORD,
        )
        user32.SetWinEventHook.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HMODULE,
            callback_type,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        user32.SetWinEventHook.restype = wintypes.HANDLE
        user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
        user32.UnhookWinEvent.restype = wintypes.BOOL
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]

        def on_window_shown(_hook, _event, window, object_id, child_id, *_args):
            if object_id != 0 or child_id != 0:
                return
            if user32.GetAncestor(window, ga_rootowner) != parent_handle:
                return
            class_name = ctypes.create_unicode_buffer(256)
            if user32.GetClassNameW(window, class_name, len(class_name)) == 0:
                return
            if class_name.value != "#32770":
                return
            rect = wintypes.RECT()
            if not user32.GetWindowRect(window, ctypes.byref(rect)):
                return
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
            user32.SetWindowPos(
                window,
                None,
                max(0, x),
                max(0, y),
                0,
                0,
                swp_nosize | swp_nozorder | swp_noactivate,
            )

        callback = callback_type(on_window_shown)
        hook = user32.SetWinEventHook(
            event_object_show,
            event_object_show,
            None,
            callback,
            process_id,
            0,
            winevent_outofcontext,
        )
    except (AttributeError, OSError):
        yield
        return

    try:
        yield
    finally:
        user32.UnhookWinEvent(hook)


def load_parameter_names_into(video_obj, par_buttons, limb_par_buttons, setup=None):
    """
    Sets names onto the video object and updates the buttons' labels.
    par_buttons: dict {1: button, 2: button, 3: button}
    limb_par_buttons: dict {1: button, 2: button, 3: button}

    The config-reading half lives in adapters.config.load_parameter_labels();
    this keeps the Video-entity mutation + Tk button wiring (GUI side, to be
    absorbed by the service layer in the next refactor step).
    """
    labels = config.load_parameter_labels() if setup is None else {
        **{f"parameter{i}": setup.parameter_labels[f"Par{i}"] for i in range(1, 4)},
        **{f"limb_parameter{i}": getattr(setup, "limb_parameter_labels", {}).get(f"Par{i}", "") for i in range(1, 4)},
    }
    p1 = labels['parameter1']
    p2 = labels['parameter2']
    p3 = labels['parameter3']

    video_obj.parameter1_name = p1
    video_obj.parameter2_name = p2
    video_obj.parameter3_name = p3
    if par_buttons.get(1):
        par_buttons[1].config(text=f"{p1}")
        theme.set_button_state(par_buttons[1], None)
    if par_buttons.get(2):
        par_buttons[2].config(text=f"{p2}")
        theme.set_button_state(par_buttons[2], None)
    if par_buttons.get(3):
        par_buttons[3].config(text=f"{p3}")
        theme.set_button_state(par_buttons[3], None)

    video_obj.limb_parameter1_name = labels['limb_parameter1']
    video_obj.limb_parameter2_name = labels['limb_parameter2']
    video_obj.limb_parameter3_name = labels['limb_parameter3']
    if limb_par_buttons.get(1):
        limb_par_buttons[1].config(text=f"{video_obj.limb_parameter1_name}")
        theme.set_button_state(limb_par_buttons[1], None)
    if limb_par_buttons.get(2):
        limb_par_buttons[2].config(text=f"{video_obj.limb_parameter2_name}")
        theme.set_button_state(limb_par_buttons[2], None)
    if limb_par_buttons.get(3):
        limb_par_buttons[3].config(text=f"{video_obj.limb_parameter3_name}")
        theme.set_button_state(limb_par_buttons[3], None)


# =============================================================================
# Main Application
# =============================================================================
class LabelingApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.config = config.load_app_config()
        self.style = theme.init_style(self, self.config.appearance)
        # Built hidden; shown once laid out (see main.py for the zoomed map).
        window_reveal.hide_root_until_settled(self)

        # Core state (was previously in __init__)
        self.video = None
        self.video_name = None
        self.minimal_touch_length = None
        self.template = DEFAULT_TEMPLATE
        self.zone_display = ZoneDisplaySettings()
        self.special_zones_diagram_scale = DEFAULT_SPECIAL_ZONES_DIAGRAM_SCALE
        self.special_zones_note = None
        self._special_zones_app = None
        # Working-state repository (state/<video>.db). Opened by load_video,
        # held for as long as that project is open, closed by _close_state_repo.
        # Tk-thread-bound by contract — never hand it to a worker thread.
        self.state_repo = None
        self.labeling_timer = LabelingTimer()
        self._zone_masks = []
        self._zone_dir = None
        # Hover highlight + zone tag on the diagram (gui.diagram_highlight).
        # Built in _draw_diagram_base once masks and scale are known, keyed by
        # (zone directory, scale) so limb switches reuse it.
        self._highlighter = None
        self._highlighter_key = None
        self._closing = False
        self._frame_extraction_cancel = None

        # Build UI (creates frames, widgets, binds events; sets many attributes)
        build_ui(self)
        self._logged_limb = self.option_var_1.get()

        # Config flags that affect UI sizing & behavior
        self.minimal_touch_length = self.config.minimal_touch_length
        logger.debug("template: %s", self.template)
        logger.debug("minimal touch length: %s", self.minimal_touch_length)
        self.perf = PerfLogger(
            enabled=self.config.perf_enabled,
            log_every_s=self.config.perf_log_every_s,
            top_n=self.config.perf_log_top_n,
        )
        logger.debug("performance logging enabled: %s", self.config.perf_enabled)
        self.video_downscale = self.config.video_downscale
        logger.debug("video downscale: %s", self.video_downscale)
        self.jump_seconds = self.config.jump_seconds
        self.jump_frame_count = 7  # fallback until a video loads & framerate is known
        logger.debug("fast jump configured: %ss", self.jump_seconds)
        self._refresh_jump_label()

        # Arrow playback follows key-down/key-up, independently of OS repeat.
        self.realtime_arrow_hold = self.config.realtime_arrow_hold
        logger.debug("realtime arrow hold: %s", self.realtime_arrow_hold)
        self.diagram_hover_effects = self.config.diagram_hover_effects
        logger.debug("diagram hover effects: %s", self.diagram_hover_effects)
        self.play_dir = 1
        self._arrow_held_dir = None
        self._arrow_release_id = None
        self._arrow_start_id = None
        self._hold_play_active = False
        self._play_tick_id = None             # after() id of the pending _play_tick
        self._play_next_due = None            # perf_counter deadline of the next playback step
        self._play_ui_next_due = None         # next ancillary UI refresh during playback
        self._play_ui_pending = False         # controls lag behind the last video paint
        # 1 ms Windows timer resolution while frames are paced (playback,
        # wheel); Tk's after() is otherwise rounded to the 15.6 ms tick.
        self._precise_timers = PreciseTimers()

        # Mouse-wheel pacing state (see WHEEL_* constants).
        self._wheel_backlog = 0               # signed frames still to step (+ forward, - back)
        self._wheel_tick_id = None            # after() id of the paced stepper
        self._wheel_delta_accum = 0           # sub-notch <MouseWheel> delta carried over
        self._wheel_next_due = None           # perf_counter deadline of the next paced step

        # Thread → UI boundary (H1). Workers never touch Tk widgets directly:
        # they advance plain state and schedule redraws via self.after(0, ...).
        self._ui_thread_ident = get_ident()   # Tk main thread (this __init__)
        self._display_w = 0                   # video_frame geometry, cached on the main
        self._display_h = 0                   # thread (workers must not call winfo_*)
        self._resize_target = None            # latest panel size from <Configure>
        self._resize_after_id = None          # after() id of the pending _apply_resize
        self._last_step_sign = 0              # +1 forward / -1 backward / 0 none

        # What is ACTUALLY on screen, as opposed to what is buffered: set only
        # when display_first_frame really paints an image. Listeners are called
        # as listener(frame_number, (width, height)) after every paint — the
        # perf scenario uses them to time paints and measure playback jitter.
        self.displayed_frame = None
        self.frame_paint_listeners = []
        self._displayed_image = None          # the PIL image on screen (identity check)
        self._gpu_video = None
        self._gpu_failed = False
        self._renderer_status = tk.StringVar(self, "Not initialized")
        self._buffer_status_shown = None      # last state of the Loaded/Loading chip
        self._display_pump_id = None          # after() id of _display_pump

        # While True, _buffer_context returns None so the buffering thread
        # idles and the display pump paints nothing. Held during load_video
        # until the new video is fully published: neither may observe (or
        # repaint from) a half-published video, and their first tick for a
        # new video only happens after _publish_loaded_video finished. It is
        # lifted there (still inside the content swap, which waits for the
        # first frame) and again, harmlessly, when load_video returns.
        self._suspend_frame_workers = False

        # Frame buffer (adapters.frame_buffer): owns the buffer lock and
        # generation, the buffering thread and the decode pool. Nothing in it
        # calls Tk. The Tk thread reads it from its own event loop: the
        # display pump paints newly decoded frames and playback is paced by
        # _play_tick, so EVERY write to video.current_frame happens on the Tk
        # thread by construction.
        self.frame_buffer = FrameBuffer(
            get_buffer_context=self._buffer_context,
            perf=self.perf,
        )
        self.background_thread = Thread(target=self.frame_buffer.background_update, daemon=True)
        self._display_pump_id = self.after(DISPLAY_PUMP_MS, self._display_pump)

        # Diagram init
        self.init_diagram()
        # Timeline draw cache
        self._detail_timeline = timeline.TouchTimelineView(self.timeline_canvas)
        self._overview_timeline = timeline.TouchTimelineView(self.timeline2_canvas)
        # Synchronize the note to the stopped frame before the user edits it.
        self.note_entry.bind("<FocusIn>", lambda event: self.stop_video(), add="+")

    def _limb_param_key_for_index(self, idx: int) -> str:
        return f"Par{idx}"

    def _set_mode_button_states(self):
        has_video = self.video is not None
        state = tk.NORMAL if has_video else tk.DISABLED
        if getattr(self, "analysis_btn", None):
            self.analysis_btn.config(state=state if getattr(self, "annotation_type", "Touch") == "Touch" else tk.DISABLED)
        if getattr(self, "special_zones_btn", None):
            self.special_zones_btn.config(state=state)
        panel = self.__dict__.get("_pose_panel")
        if panel is not None:
            for widget in panel.widgets:
                widget.config(state=state)
        # The right column only annotates a loaded video.
        selector = getattr(self, "channel_selector", None)
        if selector is not None:
            for value in selector.values:
                selector.set_enabled(value, has_video)
        for name in ("save_btn", "par1_btn", "par2_btn", "par3_btn",
                     "limb_par1_btn", "limb_par2_btn", "limb_par3_btn", "save_note_button"):
            button = getattr(self, name, None)
            if button is not None:
                button.config(state=state)
        if getattr(self, "note_entry", None) is not None:
            self.note_entry.config(state=state)

    # === UI Rebuild & Annotation Controls =====================================
    def _reset_zone_cache(self):
        self._zone_masks = []
        self._zone_dir = None
        self._zone_label_positions = {}
        if self._highlighter is not None:
            self._highlighter.destroy()
        self._highlighter = None
        self._highlighter_key = None

    def _clear_frame_children(self, frame):
        for child in frame.winfo_children():
            child.destroy()

    def rebuild_annotation_controls(self):
        if not hasattr(self, "mode_controls_frame"):
            return

        self._pose_timeline_index = None
        self._pose_detail_timeline = PoseTimelineView(self.timeline_canvas, POSE_DETAIL_FLUSH_INTERVAL_S)
        self._pose_overview_timeline = PoseTimelineView(self.timeline2_canvas)
        pose = getattr(self, "annotation_type", "Touch") == "Pose"
        self.timeline_canvas.config(height=theme.px(POSE_DETAIL_HEIGHT if pose else TIMELINE_HEIGHT))
        self.timeline2_canvas.config(height=theme.px(POSE_OVERVIEW_HEIGHT if pose else TIMELINE2_HEIGHT))
        for name in ("_detail_timeline", "_overview_timeline"):
            view = self.__dict__.get(name)
            if view is not None:
                view.reset()

        old_panel = self.__dict__.pop("_pose_panel", None)
        if old_panel is not None:
            old_panel.detach()
        definition = get_template(self.template)
        self.limb_parameter_heading.config(text="Channel parameters")
        self._clear_frame_children(self.mode_controls_frame)
        self._clear_frame_children(self.limb_parameter_frame)
        self.limb_par1_btn = None
        self.limb_par2_btn = None
        self.limb_par3_btn = None

        if getattr(self, "annotation_type", "Touch") == "Pose":
            self._pose_panel = PosePanel(self)
            self._pose_panel.build()
            self._set_mode_button_states()
            self._refit_diagram_if_resized()
            return

        px = theme.px
        inset = px(CARD_CONTENT_PAD)
        ttk.Label(
            self.mode_controls_frame,
            text="Channel Selector",
            style="CardHead.TLabel",
        ).pack(anchor="w", padx=inset, pady=(px(12), px(8)))

        # 2x2 gapless grid; a click sets option_var_1, then reports the change.
        self.channel_selector = widgets.SegmentedControl(
            self.mode_controls_frame,
            [(channel.key,
              self.coding_setup.channel_labels[channel.key]
              if getattr(self, "coding_setup", None) else channel.label)
             for channel in definition.channels],
            variable=self.option_var_1,
            command=lambda _value: self._on_limb_selected(),
            columns=2,
            bg="CARD",
        )
        self.channel_selector.pack(fill="x", padx=inset, pady=(0, inset))

        def pill(index, text):
            button = widgets.ParamPill(self.limb_parameter_frame, text=text,
                                       command=lambda: self.toggle_limb_parameter(index))
            button.pack(fill="x")
            return button

        self.limb_par1_btn = pill(1, self.config.limb_parameter1)
        self.limb_par2_btn = pill(2, self.config.limb_parameter2)
        self.limb_par3_btn = pill(3, self.config.limb_parameter3)

        self._set_mode_button_states()
        self._refit_diagram_if_resized()

    def _refit_diagram_if_resized(self):
        """Fit the diagram to the column again when its native size changed.

        Pose's diagram is much larger than Touch's and its controls are taller,
        so the scale fitted for one would push the other cards off the window.
        """
        native = diagram_native_size(self)
        previous = self.__dict__.get("_fitted_native_size")
        self._fitted_native_size = native
        if previous is not None and previous != native and self.__dict__.get("notes_card") is not None:
            fit_diagram_to_column(self)

    # === Data Bundle Management ================================================
    def _param_key_for_index(self, idx: int) -> str:
        return f"Par{idx}"

    def mark_bundle_changed(self, index=None):
        if self.video is None:
            return
        idx = self.video.current_frame if index is None else index

        if self.__dict__.get("_pose_panel") is not None:
            self._annotation_version = getattr(self, "_annotation_version", 0) + 1
            bundle = self.video.frames.get(idx)
            if isinstance(bundle, dict):
                bundle["Changed"] = True
            self._pose_annotation_changed(idx)
            self._refresh_after_annotation_edit()
            return

        # Every annotation edit passes through here, so this is where cached
        # views of the annotations go stale and the screen catches up.
        self._annotation_version = getattr(self, "_annotation_version", 0) + 1
        b = self.video.frames.get(idx)
        if isinstance(b, dict):
            b["Changed"] = True
            self._detail_timeline.invalidate()
            self._overview_timeline.invalidate()
            if hasattr(self, "notify_bundle_changed"):
                self.notify_bundle_changed(idx)
        self._refresh_after_annotation_edit()

    def notify_bundle_changed(self, index=None):
        if self.video is None:
            return
        idx = self.video.current_frame if index is None else index
        try:
            b = self.video.frames[idx]
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("FrameBundle updated:\n%s", bundle_summary_str(b, frame_index=idx))
        except Exception:
            logger.warning("could not summarize bundle at frame %s", idx, exc_info=True)

    # === Navigation & Input Events =============================================
    def global_click(self, event):
        try:
            focus = self.focus_get()
        except Exception:
            focus = None
        # Only clicks inside the main window leave the note: a click in a
        # dialog (Settings, ...) must keep the focus it just gave its field.
        try:
            in_main = event.widget.winfo_toplevel() is self
        except (AttributeError, tk.TclError):
            in_main = False
        if (in_main and getattr(self, "note_entry", None) and focus == self.note_entry
                and event.widget != self.note_entry):
            self.focus_set()

    def _entry_has_focus(self):
        """True while the note entry holds keyboard focus."""
        try:
            return getattr(self, "note_entry", None) is not None \
                and self.focus_get() is self.note_entry
        except Exception:
            return False

    def _show_buffer_status(self, loaded: bool):
        """The `Buffer: Loaded / Loading` chip, updated only on change (Tk thread)."""
        if loaded == self._buffer_status_shown:
            return
        self._buffer_status_shown = loaded
        if loaded:
            self.loading_label.set(theme.STATUS_OK, "Loaded")
        else:
            self.loading_label.set(theme.STATUS_BAD, "Loading")

    def _display_pump(self):
        """Poll the frame buffer from the Tk event loop (every DISPLAY_PUMP_MS).

        The ONE path by which frames decoded in the background reach the
        screen: when the buffered image for the current frame is not the one
        on screen — the frame just finished decoding, or the buffer was
        rebuilt at a new size after a resize — paint it. The buffering thread
        never calls Tk itself (see adapters.frame_buffer invariant (c)), so it
        can't stall behind a slow repaint. A frame that is already buffered
        is still painted immediately by next_frame; the pump only adds up to
        DISPLAY_PUMP_MS on the path where the frame had to be decoded first.
        """
        self._display_pump_id = self.after(DISPLAY_PUMP_MS, self._display_pump)
        if self.video is None or self._suspend_frame_workers:
            return
        buffered = self.frame_buffer.get(self.video.current_frame)
        self._show_buffer_status(buffered is not None)
        if buffered is not None and buffered is not self._displayed_image:
            self.display_first_frame()

    def _is_ui_thread(self) -> bool:
        """True when called on the Tk main thread (recorded in __init__)."""
        return get_ident() == self._ui_thread_ident

    def _assert_ui_thread(self):
        """Dev guard (H1): fail loudly on off-thread widget access.

        No-op unless DEBUG_ASSERT_UI_THREAD is enabled — zero cost in
        production, a hard RuntimeError at the offending call site in dev.
        """
        if DEBUG_ASSERT_UI_THREAD and not self._is_ui_thread():
            raise RuntimeError(
                f"Tk widget access from non-UI thread '{current_thread().name}' "
                "— marshal via self.after(0, ...)"
            )

    def navigate_left(self, event):  self._on_arrow_press(-1)
    def navigate_right(self, event): self._on_arrow_press(1)

    # --- Arrow-hold playback ------------------------------------------------
    def _on_arrow_press(self, direction):
        """Step once on key-down, then play if held past the tap grace period."""
        if self.video is None:
            return
        if not self.realtime_arrow_hold:
            self._request_buffered_step(direction)
            return

        if self._arrow_release_id is not None:
            self.after_cancel(self._arrow_release_id)
            self._arrow_release_id = None
        if self._arrow_held_dir == direction:
            return

        self._cancel_arrow_hold_state()
        self.stop_video()
        self._arrow_held_dir = direction
        self._arrow_start_id = self.after(
            ARROW_HOLD_DELAY_MS, lambda: self._begin_hold_playback(direction))
        self._request_buffered_step(direction, preserve_arrow_hold=True)

    def _begin_hold_playback(self, direction):
        self._arrow_start_id = None
        if self._arrow_held_dir != direction or self.video is None:
            return
        self._hold_play_active = True
        self._start_playback(direction)
        logger.debug("arrow playback started: direction=%s fps=%s", direction, self.frame_rate)

    def _on_arrow_release(self, direction):
        """Defer release to idle so X11 repeat release/press pairs cancel it."""
        if self._arrow_held_dir != direction or self._arrow_release_id is not None:
            return
        self._arrow_release_id = self.after_idle(self._cancel_arrow_hold_state)

    def _cancel_arrow_hold_state(self):
        """Stop arrow playback on release, focus loss, reload or shutdown."""
        if self._arrow_start_id is not None:
            self.after_cancel(self._arrow_start_id)
            self._arrow_start_id = None
        if self._arrow_release_id is not None:
            self.after_cancel(self._arrow_release_id)
            self._arrow_release_id = None
        self._arrow_held_dir = None
        if self._hold_play_active:
            self._hold_play_active = False
            self.play_dir = 1
            self.stop_video()

    def _refresh_jump_label(self):
        label = getattr(self, "jump_label", None)
        if label is None:
            return
        if self.video is not None and getattr(self, "frame_rate", None):
            text = f"Jump: {self.jump_frame_count} frames ({self.jump_seconds}s)"
        else:
            text = f"Jump: {self.jump_seconds}s"
        label.config(text=text)

    def update_last_mouse_position(self, event):
        self.last_mouse_x = event.x
        self.last_mouse_y = event.y
        if self._highlighter is not None and self.video is not None:
            self._highlighter.on_motion(event.x, event.y)

    def on_diagram_leave(self, _event=None):
        if self._highlighter is not None:
            self._highlighter.on_leave()

    def _hover_tooltip(self, zone, x, y):
        """Text of the tag next to the pointer at native diagram pixel (x, y).

        Show the user label, falling back to the fixed zone ID when unlabeled.
        `NN` (no zone) shows nothing.
        """
        if zone == NO_ZONE:
            return None
        return self.zone_display.label(zone)

    def on_resize(self, event):
        """<Configure> on the video panel: rebuild the buffer once it settles.

        A rebuild throws away every decoded frame, so it must not run per
        event: Tk also sends <Configure> for moves and re-layouts that keep
        the size, and a window-edge drag sends dozens of sizes per second.
        Same-size events are ignored; real changes restart a RESIZE_SETTLE_MS
        timer and only the final size is applied. The old frame stays on
        screen meanwhile.
        """
        size = (event.width, event.height)
        if size == self._resize_target:
            return
        self._resize_target = size
        if self._resize_after_id is not None:
            self.after_cancel(self._resize_after_id)
        self._resize_after_id = self.after(RESIZE_SETTLE_MS, self._apply_resize)

    def _apply_resize(self):
        self._resize_after_id = None
        if self._resize_target == (self._display_w, self._display_h):
            return  # the drag ended where it started
        logger.debug("video panel resized to %sx%s", *self._resize_target)
        # Refresh the geometry cache the buffer thread reads instead of winfo_* (H1).
        self._display_w, self._display_h = self._resize_target
        self._buffer_reset()
        if self.video:
            self.display_first_frame()

    # --- Mouse-wheel navigation, paced at the video frame rate ---------------
    def on_mouse_wheel(self, event):
        if self.video is None or getattr(self, "_selecting_frame", False):
            return
        # The wheel is bound app-wide; scrolling inside a dialog (video
        # library, zone names, ...) must not step the video behind it.
        widget = getattr(event, "widget", None)
        if widget is not None:
            try:
                if widget.winfo_toplevel() is not self:
                    return
            except (AttributeError, tk.TclError):
                return  # e.g. a popdown reported by path string: not the main window
        notches = self._wheel_notches(event)
        if notches == 0:
            return
        if self._wheel_backlog and (self._wheel_backlog > 0) != (notches > 0):
            self._wheel_backlog = 0  # direction reversal: drop the stale queue
        cap = self._wheel_backlog_cap()
        self._wheel_backlog = max(-cap, min(cap, self._wheel_backlog + notches))
        if self._wheel_tick_id is None:
            self._precise_timers.hold("wheel")
            self._wheel_tick()  # first notch paints immediately (tap feel)

    def _wheel_notches(self, event) -> int:
        """Signed frame steps for one wheel event (+1 = forward)."""
        num = getattr(event, "num", None)
        if num == 4:
            return -1
        if num == 5:
            return 1
        delta = getattr(event, "delta", 0) or 0
        if sys.platform != "win32":
            # macOS reports small per-event deltas; treat each event as a notch.
            return -1 if delta > 0 else (1 if delta < 0 else 0)
        self._wheel_delta_accum += delta
        notches = int(self._wheel_delta_accum / WHEEL_NOTCH_DELTA)
        self._wheel_delta_accum -= notches * WHEEL_NOTCH_DELTA
        return -notches  # wheel up (positive delta) = previous frame

    def _wheel_backlog_cap(self) -> int:
        fps = getattr(self, "frame_rate", None) or (1000.0 / WHEEL_DEFAULT_INTERVAL_MS)
        return max(1, round(fps * WHEEL_BACKLOG_S))

    def _frame_interval_ms(self) -> int:
        fps = getattr(self, "frame_rate", None)
        if fps and fps > 0:
            return max(1, round(1000.0 / fps))
        return WHEEL_DEFAULT_INTERVAL_MS

    def _wheel_tick(self):
        self._wheel_tick_id = None
        if self.video is None or self._wheel_backlog == 0:
            self._wheel_backlog = 0
            self._wheel_next_due = None
            self._precise_timers.release("wheel")
            return
        direction = 1 if self._wheel_backlog > 0 else -1
        current = self.video.current_frame
        target = max(0, min(self.video.total_frames, current + direction))
        if target == current:
            self._wheel_backlog = 0  # at the first/last frame: nothing left to do
            self._precise_timers.release("wheel")
            return
        if target not in self.frame_buffer:
            # Not decoded yet: ask for it and retry without consuming a notch.
            self.frame_buffer.request_priority(target)
            self._wheel_tick_id = self.after(WHEEL_BUFFER_POLL_MS, self._wheel_tick)
            return
        due = self._wheel_next_due = self._next_deadline(
            self._wheel_next_due, self._frame_interval_ms() / 1000.0)
        self._wheel_backlog -= direction
        self.next_frame(direction)
        # Stay armed until the deadline even with an empty queue: notches
        # arriving inside that window are queued instead of painting at once.
        delay_ms = max(1, round((due - time.perf_counter()) * 1000.0))
        self._wheel_tick_id = self.after(delay_ms, self._wheel_tick)

    def _cancel_wheel_scroll(self):
        """Drop queued wheel steps. Used when the video is unloaded."""
        if self._wheel_tick_id is not None:
            try: self.after_cancel(self._wheel_tick_id)
            except Exception: pass
            self._wheel_tick_id = None
        self._wheel_backlog = 0
        self._wheel_delta_accum = 0
        self._wheel_next_due = None
        self._precise_timers.release("wheel")

    @staticmethod
    def _next_deadline(due, interval_s):
        """Wheel deadline pacing without catching up late navigation steps.

        The next step is due one interval after the PREVIOUS deadline, not
        one interval after the redraw: the redraw itself costs ~20 ms, and
        adding it to every wait would make a 25 fps video move at ~16 fps.
        An idle or badly lagging clock restarts from now, so a late tick
        never tries to catch up with a burst of steps.

        perf_counter, NOT monotonic: on Windows time.monotonic() is
        GetTickCount64 with a 15.6 ms resolution, which quantized every
        deadline and made 25 fps steps alternate between ~31 and ~47 ms.
        """
        now = time.perf_counter()
        if due is None or due < now - interval_s:
            due = now
        return due + interval_s

    # --- Playback, paced on the Tk thread ------------------------------------
    # Play / arrow-hold playback is a chain of after() callbacks on the Tk
    # thread, like the wheel: advance one frame, schedule the next tick at
    # the next deadline. There is no playback thread — the work per step is
    # a paint, which must happen on the Tk thread anyway, and a thread that
    # asks Tk for every step waits on a synchronous round-trip each time.
    # At most one tick is pending (_play_tick_id); setting self.play = False
    # ends the chain at the next tick.
    def _frame_interval_s(self) -> float:
        """Exact seconds per video frame (playback must not drift)."""
        fps = getattr(self, "frame_rate", None)
        if fps and fps > 0:
            return 1.0 / fps
        return WHEEL_DEFAULT_INTERVAL_MS / 1000.0

    def _start_playback(self, direction):
        """Play in `direction` (+1 / -1); arm the tick chain if it is idle."""
        if not self.play or direction != self.play_dir:
            self._play_next_due = None
            self._play_ui_next_due = None
        self.play_dir = direction
        self.play = True
        sync_play_control(self)
        self._precise_timers.hold("playback")
        if self._play_tick_id is None:
            self._play_tick()

    def _end_play_chain(self):
        """The tick chain stops here: forget the clock, give back the timers."""
        self._play_next_due = None
        self._precise_timers.release("playback")
        self._flush_playback_ui()
        sync_play_control(self)

    @staticmethod
    def _next_playback_deadline(due, interval_s):
        """Keep modest lateness on the playback clock; bound recovery work.

        Resetting after just one late frame loses wall-clock time at high FPS.
        The next callback catches up one frame at a time, with a minimum 1 ms
        wait so input and paints can run. A long pause starts a fresh clock.
        Wheel scrolling deliberately retains its separate non-catch-up rule.
        """
        now = time.perf_counter()
        if due is None or now - due > PLAYBACK_MAX_LAG_S:
            due = now
        return due + interval_s

    def _play_window_buffered(self, current, direction):
        """True when `current` and the next PLAYBACK_BUFFER_AHEAD frames in
        the play direction (clamped to the video) are all decoded."""
        for k in range(PLAYBACK_BUFFER_AHEAD + 1):
            frame = current + direction * k
            if frame < 0 or frame > self.video.total_frames:
                break
            if frame not in self.frame_buffer:
                return False
        return True

    def _play_tick(self):
        self._play_tick_id = None
        if self.video is None:
            self.play = False  # the video went away (unload): playback is over
        if not self.play:
            self._end_play_chain()
            return
        direction = 1 if self.play_dir >= 0 else -1
        current = self.video.current_frame
        next_frame, stop = compute_play_step(current, self.video.total_frames, direction)
        if stop:
            self._end_play_chain()
            self._on_playback_boundary(current, direction)
            return
        if not self._play_window_buffered(current, direction):
            # Stall briefly rather than stutter: wait until the next frames
            # are decoded, then restart the clock (no catch-up burst).
            self.frame_buffer.request_priority(next_frame)
            self._play_next_due = None
            self._flush_playback_ui()
            self._play_tick_id = self.after(PLAYBACK_STALL_POLL_MS, self._play_tick)
            return
        due = self._play_next_due = self._next_playback_deadline(
            self._play_next_due, self._frame_interval_s())
        self._apply_play_advance(next_frame, direction)
        delay_ms = max(1, round((due - time.perf_counter()) * 1000.0))
        self._play_tick_id = self.after(delay_ms, self._play_tick)

    def _request_buffered_step(self, delta, *, preserve_arrow_hold=False):
        if self.video is None:
            return
        if not preserve_arrow_hold:
            self.stop_video()
        self._pending_buffer_step = delta
        self._pending_buffer_preserve_hold = preserve_arrow_hold
        # Hint the buffering thread to prioritize the jump target so the polling
        # loop in _buffered_step_tick picks it up on the next 50ms tick.
        target = max(0, min(self.video.total_frames, self.video.current_frame + delta))
        if target not in self.frame_buffer:
            self.frame_buffer.request_priority(target)
        self._buffered_step_tick()

    def _buffered_step_tick(self):
        if self.video is None:
            self._pending_buffer_step = None
            return
        delta = getattr(self, "_pending_buffer_step", None)
        if delta is None:
            return
        current_frame = self.video.current_frame
        next_frame = max(0, min(self.video.total_frames, current_frame + delta))
        if current_frame not in self.frame_buffer or next_frame not in self.frame_buffer:
            self.after(50, self._buffered_step_tick)
            return
        self._pending_buffer_step = None
        self.next_frame(delta, preserve_arrow_hold=self._pending_buffer_preserve_hold)

    def on_middle_click(self, event=None):
        panel = self.__dict__.get("_pose_panel")
        if panel is not None:
            x = self.last_mouse_x if event is None or getattr(event, "keysym", "") == "d" else event.x
            y = self.last_mouse_y if event is None or getattr(event, "keysym", "") == "d" else event.y
            panel.click(x, y, None)
            return
        if self.video is None:
            return
        if not LabelingApp._annotation_frame_ready(self):
            return
        # mouse position in display coords; convert to data coords using diagram_scale
        if event is None or isinstance(event, tk.Event):
            x_disp, y_disp = self.last_mouse_x, self.last_mouse_y
        else:
            x_disp, y_disp = event.x, event.y

        scale = getattr(self, "diagram_scale", 1.0)
        x_pos = x_disp * (1.0 / scale)
        y_pos = y_disp * (1.0 / scale)

        current_frame = self.video.current_frame
        option = self.option_var_1.get()

        # threshold in data coords (≈20 px in display); translates to 20/scale
        removed = annotation_service.remove_nearest_click(
            self.video.frames, current_frame, option, x_pos, y_pos,
            max_dist=20.0 / scale,
        )
        if removed:
            self.mark_bundle_changed()  # also repaints the dots and timelines
            rec = self.video.frames[current_frame][option]
            annotation_logger.info(
                "f=%s %s delete points=%s",
                current_frame,
                option,
                len(rec.get("X", [])),
            )

    # === Diagram Init & Click Handling =========================================
    # The diagram is repainted on EVENTS, not on a timer: frame changes
    # (display_first_frame), annotation edits (mark_bundle_changed), limb and
    # display-setting changes (on_radio_click), and template / zone-name /
    # project changes (_redraw_diagram). It used to be fully rebuilt every
    # 300 ms by `periodic_print_dot`, which hid those dependencies and would
    # wipe any canvas item that is meant to live longer than one repaint.
    def init_diagram(self):
        self._ghost_cache = None
        self._reset_zone_cache()
        self._load_zone_masks()
        self._redraw_diagram()

    def _redraw_diagram(self):
        """Full diagram repaint: limb image, zone labels, then the dots."""
        panel = self.__dict__.get("_pose_panel")
        if panel is not None:
            panel.draw()
            return
        self._draw_diagram_base()
        self._draw_diagram_dots()

    # === Diagram resize (corner grip) ==========================================
    def _diagram_display_size(self, scale):
        base_w, base_h = get_template(self.template).native_size
        if getattr(self, "annotation_type", "Touch") == "Pose":
            from domain.pose_geometry import POSE_SIZE
            base_w, base_h = POSE_SIZE
        return int(base_w * scale), int(base_h * scale)

    def _diagram_image_path(self):
        definition = get_template(self.template)
        if self.video is None:
            return asset_path(definition.startup_diagram)
        return asset_path(definition.diagram)

    def preview_diagram_scale(self, scale):
        """Cheap repaint while the grip is dragged: bilinear image plus the dots.

        Zone labels and the hover highlighter wait for commit_diagram_scale;
        the pointer is on the grip during the drag, so nothing hovers anyway.
        """
        scale = float(scale)
        self.diagram_scale = scale
        w, h = self._diagram_display_size(scale)
        self.diagram_canvas.config(width=w, height=h)
        panel = self.__dict__.get("_pose_panel")
        if panel is not None:
            panel.draw()
            return
        self.diagram_canvas.delete("all")
        path = self._diagram_image_path()
        cache = getattr(self, "_diagram_native_cache", None)
        if cache is None:
            cache = self._diagram_native_cache = {}
        native = cache.get((path, repr(getattr(self, "coding_setup", None)), self.option_var_1.get()))
        if native is None and self.video is not None:   # no video: the diagram stays empty
            try:
                with Image.open(path) as img:
                    native = img.convert("RGBA")
                    if getattr(self, "coding_setup", None):
                        native = render_channel_diagram(self.coding_setup, self.option_var_1.get(), self._zone_masks).convert("RGBA")
                    cache[(path, repr(getattr(self, "coding_setup", None)), self.option_var_1.get())] = native
            except Exception:
                logger.debug("diagram preview skipped: %s unreadable", path)
                native = None
        if native is not None:
            self.photo = ImageTk.PhotoImage(native.resize((w, h), Image.BILINEAR), master=self)
            self.diagram_canvas.create_image(0, 0, anchor="nw", image=self.photo, tags=("diagram",))
        if self._highlighter is not None:
            self._highlighter.canvas_cleared()
        self._draw_diagram_dots()

    def commit_diagram_scale(self, scale):
        """Grip released: full redraw at `scale` and remember it in config.json.

        Stored click coordinates are native diagram pixels, so only the display
        changes. The Settings dialog no longer edits this value; it writes the
        live scale back so an open dialog cannot undo the drag.
        """
        scale = self.apply_diagram_scale(scale)
        try:
            cfg = config.load_config()
            cfg["diagram_scale"] = round(scale, 3)
            config.save_config(cfg)
            self.config = config.load_app_config()
        except Exception:
            logger.exception("could not store the diagram scale in config.json")

    def apply_diagram_scale(self, scale):
        """Full diagram redraw at `scale` without saving it (window fit, commit)."""
        scale = float(scale)
        self.diagram_scale = scale
        w, h = self._diagram_display_size(scale)
        self.diagram_canvas.config(width=w, height=h)
        if self.video is None:
            self.diagram_canvas.delete("all")
            draw_startup_diagram(self, scale)
        else:
            self.on_radio_click()
        # Each scale adds a LANCZOS photo per limb to the cache; keep only the
        # current scale so repeated drags do not accumulate old sizes.
        cache = getattr(self, "_diagram_photo_cache", None)
        if cache:
            for key in [key for key in cache if key[1] != scale]:
                del cache[key]
        logger.debug("diagram scale set to %.3f (%sx%s px)", scale, w, h)
        return scale

    def _draw_diagram_dots(self):
        """Repaint only the current frame's dots + the open-onset ghost.

        Cheap (deletes and recreates a handful of cached sprites), so it runs
        on every frame change, including each playback step.
        """
        panel = self.__dict__.get("_pose_panel")
        if panel is not None:
            panel.refresh()
            panel.draw_frame()
            return
        self.diagram_canvas.delete(DIAGRAM_DOT_TAG)
        if not self.video:
            return
        dot_size = getattr(self, "dot_size", 10)
        scale = getattr(self, "diagram_scale", 1.0)
        sel = self.option_var_1.get()
        if sel == "RH":
            data = self.video.dataRH
        elif sel == "LH":
            data = self.video.dataLH
        elif sel == "RF":
            data = self.video.dataRF
        elif sel == "LF":
            data = self.video.dataLF
        else:
            data = {}
        self.find_last_green(data)
        frame_data: FrameRecord | dict = data.get(self.video.current_frame, {})
        xs = frame_data.get('X', []) if frame_data else []
        ys = frame_data.get('Y', []) if frame_data else []
        onset = frame_data.get('Onset', "OFF") if frame_data else "OFF"
        for x, y in zip(xs, ys):
            color = theme.DOT_ONSET if onset == "ON" else theme.DOT_OFFSET
            self.diagram_canvas.create_image(
                x * scale,
                y * scale,
                image=theme.dot_sprite(color, dot_size),
                tags=(DIAGRAM_DOT_TAG,),
            )
        array_xy = getattr(self.video, "last_green", [(None, None)])
        for (x_last, y_last) in array_xy:
            if x_last is not None:
                self.diagram_canvas.create_image(
                    x_last * scale,
                    y_last * scale,
                    image=theme.dot_sprite(theme.DOT_ONSET, dot_size, hollow=True),
                    tags=(DIAGRAM_DOT_TAG,),
                )

    def _refresh_after_annotation_edit(self):
        """Show an edit right away: the dots and both timelines can change."""
        self._draw_diagram_dots()
        self.draw_timeline()
        self.draw_timeline2()

    def on_diagram_click(self, event, is_onset):
        panel = self.__dict__.get("_pose_panel")
        if panel is not None:
            panel.click(event.x, event.y, ZoneEvent.ON if is_onset else ZoneEvent.OFF)
            return
        if self.video is None:
            return
        onset = "ON" if is_onset else "OFF"
        display_scale = getattr(self, "diagram_scale", 1.0)
        x_pos = event.x * (1.0 / display_scale)
        y_pos = event.y * (1.0 / display_scale)
        zone_results = list(self.find_image_with_white_pixel(x_pos, y_pos))  # list for stability

        current_frame = self.video.current_frame
        option = self.option_var_1.get()

        # OBSERVABILITY: an unmatched click is not an error the app can fix, but
        # it silently enters the dataset as the NN sentinel (~0.1% of the canvas
        # matches no mask at all, plus anything outside the mask bounds). Say so
        # here, where the frame and limb are known, so the annotator can go back
        # and re-place the dot instead of finding NN rows after the study.
        if zone_results == [NO_ZONE]:
            logger.warning(
                "click hit no zone mask - recorded as '%s' frame=%s limb=%s "
                "onset=%s x=%.1f y=%.1f (diagram pixels); delete the dot and "
                "click further inside a zone",
                NO_ZONE,
                current_frame,
                option,
                onset,
                x_pos,
                y_pos,
            )

        if not LabelingApp._lock_before_annotation(self):
            return
        setattr(self.video, f"is_touch{option}", True)

        rec = annotation_service.add_click(
            self.video.frames, current_frame, option, x_pos, y_pos, onset, zone_results
        )

        self.mark_bundle_changed()  # also repaints the dots and timelines
        highlighter = getattr(self, "_highlighter", None)  # absent on the unit-test stubs
        if highlighter is not None:
            highlighter.flash(zone_results[0], theme.DOT_ONSET if is_onset else theme.DOT_OFFSET)

        annotation_logger.info(
            "f=%s %s click %s zones=%s points=%s",
            current_frame,
            option,
            rec.get("Onset"),
            zone_results,
            len(rec.get("X", [])),
        )

    def preview_before_save(self, changed_only: bool = True):
        """
        Print a compact preview of what would be saved right now.
        Shows base/state/export dirs and per-frame summaries.
        """
        if not self.video:
            logger.debug("save preview skipped: no video loaded")
            return

        paths = ProjectPaths(self.video_name)
        lines = preview_lines_for_save(self.video.frames, self.video.total_frames, changed_only=changed_only)
        logger.debug(
            "save preview: video_dir=%s state_db=%s export_csv=%s changed=%s%s",
            paths.video_dir,
            paths.state_db,
            paths.export_csv,
            len(lines),
            "\n" + "\n".join(lines) if lines else "",
        )
    
    def find_last_green(self, _unused_data=None):
        """
        Set self.video.last_green to the last 'ON' points for the selected limb
        at or before the current frame; clear when an 'OFF' is encountered first.
        The pure backward scan lives in domain.touch.find_last_open_onset.
        """
        if not (self.video and isinstance(self.video.frames, dict)):
            self.video.last_green = [(None, None)]
            return

        limb = self.option_var_1.get()  # "LH"/"RH"/"LF"/"RF"
        frame = self.video.current_frame
        # Reuse the previous answer while video, limb and annotations are
        # unchanged: playback then scans one frame per step, not back to the
        # last ON/OFF (possibly frame 0) on every step.
        key = (self.video, limb, getattr(self, "_annotation_version", 0))
        cache = getattr(self, "_ghost_cache", None)
        known = cache[1] if cache is not None and cache[0] == key else None
        points = find_last_open_onset(self.video.frames, limb, frame, known=known)
        self._ghost_cache = (key, (frame, points))
        self.video.last_green = points

    def _on_limb_selected(self):
        selected = self.option_var_1.get()
        previous = getattr(self, "_logged_limb", None)
        if previous is not None and previous != selected:
            annotation_logger.info("limb %s -> %s", previous, selected)
        self._logged_limb = selected
        self.on_radio_click()

    def on_radio_click(self):
        """Limb or diagram display settings changed: repaint everything that
        depends on the selected limb."""
        self._redraw_diagram()
        if self.video is None:
            return
        self.draw_timeline()
        self.draw_timeline2()
        self.update_limb_parameter_buttons()

    def _draw_diagram_base(self):
        """Clear the diagram and draw the limb image and zone labels."""
        self.diagram_canvas.delete("all")
        if self.video is None:
            return
        definition = get_template(self.template)
        expected_dir = asset_path(definition.masks_directory)
        if getattr(self, "_zone_dir", None) != expected_dir:
            self._reset_zone_cache()
            self._load_zone_masks()
        image_path = self._diagram_image_path()
        setup = getattr(self, "coding_setup", None)
        image_key = (image_path, repr(setup), self.option_var_1.get())

        scale = getattr(self, "diagram_scale", 1.0)
        # Cache the decoded+resized PhotoImage per (path, scale) so switching
        # limbs back and forth does not re-read and resize the PNG. The flat
        # RGB copy beside it is what the hover highlight tints.
        cache = getattr(self, "_diagram_photo_cache", None)
        if cache is None:
            cache = self._diagram_photo_cache = {}
        cached = cache.get((image_key, scale))
        if cached is None:
            with Image.open(image_path) as source:
                img = (render_channel_diagram(setup, self.option_var_1.get(), self._zone_masks)
                       if setup else source.convert("RGB"))
                resized = img.resize(
                    (int(img.width * scale), int(img.height * scale)), Image.LANCZOS
                )
            white = Image.new("RGBA", resized.size, (255, 255, 255, 255))
            flat = Image.alpha_composite(white, resized.convert("RGBA")).convert("RGB")
            cached = cache[(image_key, scale)] = (ImageTk.PhotoImage(resized, master=self), flat)
        self.photo, base_rgb = cached
        self.diagram_canvas.create_image(0, 0, anchor="nw", image=self.photo, tags=("diagram",))
        draw_zone_labels(self.diagram_canvas, self.zone_display, self._zone_label_positions, scale)

        key = (self._zone_dir, scale)
        if self._highlighter is None or self._highlighter_key != key:
            if self._highlighter is not None:
                self._highlighter.destroy()
            self._highlighter = DiagramHighlighter(
                self.diagram_canvas, self._zone_masks, scale, base_rgb.size, self._hover_tooltip
            )
            self._highlighter.set_enabled(self.diagram_hover_effects)
            self._highlighter_key = key
        self._highlighter.set_base(base_rgb)
        self._highlighter.canvas_cleared()  # delete("all") above dropped its items

    # === Zone Masks & Lookups ==================================================
    def _load_zone_masks(self):
        if getattr(self, "annotation_type", "Touch") == "Pose":
            from adapters.pose_diagram import pose_zone_masks
            import numpy as np
            self._zone_masks = [(name, np.asarray(mask)) for name, mask in pose_zone_masks()]
            self._zone_label_positions = zone_label_positions(self._zone_masks)
            return
        directory = asset_path(get_template(self.template).masks_directory)
        if getattr(self, "_zone_dir", None) == directory and getattr(self, "_zone_masks", None):
            return
        self._zone_dir = directory
        self._zone_masks = load_zone_masks(directory)
        self._zone_label_positions = zone_label_positions(self._zone_masks)

    def find_image_with_white_pixel(self, x, y):
        # NOTE: historically misleading name — the masks are BLACK shapes on
        # white, so a hit is pixel == 0. domain.touch.zones_at owns the rule:
        # overlapping masks resolve by precedence (real zone > BOX* > OUTSIDE >
        # LINE) and a miss is the ['NN'] sentinel the exports rely on.
        with self.perf.time("find_image_with_white_pixel"):
            if not getattr(self, "_zone_masks", None):
                self._load_zone_masks()
            return zones_at(self._zone_masks, x, y)

    # === Timelines =============================================================
    def on_timeline_click(self, event):
        if self._open_timeline_note(event):
            return "break"
        if self.video and self.video.total_frames > 0:
            self.stop_video()
            click_position = event.x
            canvas_width = self.timeline_canvas.winfo_width()
            frame_number = timeline_click_frame(click_position, canvas_width, self.video.number_frames_in_zone)
            if self.video.total_frames >= frame_number + self.video.number_frames_in_zone * self.video.current_frame_zone:
                panel = self.__dict__.get("_pose_panel")
                if panel is not None:
                    panel.pending = None
                self.video.current_frame = frame_number + self.video.number_frames_in_zone * self.video.current_frame_zone
                self.display_first_frame()
                # display_first_frame refreshes the controls only; move both playheads.
                self.draw_timeline()
                self.draw_timeline2()
            else:
                logger.error("invalid frame number")

    def on_timeline2_click(self, event):
        if self._open_timeline_note(event):
            return "break"
        if self.video and self.video.total_frames > 0:
            self.stop_video()
            click_position = event.x
            canvas_width = self.timeline2_canvas.winfo_width()
            new_frame = timeline_click_frame(click_position, canvas_width, self.video.total_frames)
            panel = self.__dict__.get("_pose_panel")
            if panel is not None:
                panel.pending = None
            self.video.current_frame = new_frame
            self.video.current_frame_zone = new_frame // self.video.number_frames_in_zone
            logger.debug("jumping to exact frame: %s", new_frame)
            self.display_first_frame()
            # display_first_frame refreshes the controls only; the zone may have
            # changed, so repaint the zone timeline and move both playheads.
            self.draw_timeline()
            self.draw_timeline2()

    def _open_timeline_note(self, event):
        """Resolve note clicks before the canvas's approximate frame jump."""
        if self.video is None:
            return False
        for tag in event.widget.gettags("current"):
            if tag.startswith("note_frame:"):
                frame = int(tag.split(":", 1)[1])
                panel = self.__dict__.get("_pose_panel")
                if panel is not None:
                    panel.pending = None
                self.stop_video()
                self.video.current_frame = frame
                self.video.current_frame_zone = frame // self.video.number_frames_in_zone
                self.display_first_frame()
                self.draw_timeline()
                self.draw_timeline2()
                self.focus_set()
                return True
        return False

    def draw_timeline(self):
        if self.__dict__.get("_pose_panel") is not None:
            if self.video and self.video.total_frames >= 0:
                index = self._get_pose_timeline_index()
                count = self.video.number_frames_in_zone
                zone = self.video.current_frame // count if count else self.video.current_frame_zone
                self.video.current_frame_zone = zone
                self._pose_detail_timeline.draw(
                    index, self.video.total_frames, self.video.current_frame,
                    offset=zone * count, count=count,
                    defer=self.__dict__.get("_defer_timeline_content", False))
            return
        self._assert_ui_thread()
        with self.perf.time("draw_timeline"):
            if not (self.video and self.video.total_frames > 0):
                return
            video = self.video
            count = video.number_frames_in_zone
            zone = video.current_frame // count if count else video.current_frame_zone
            video.current_frame_zone = zone
            projection = self._detail_timeline.draw_detail(
                video.frames, self.option_var_1.get(), video.total_frames, zone, count,
                False if zone == 0 else video.touch_to_next_zone[zone],
                self.color_during, video.current_frame,
            )
            if projection is not None:
                self.is_touch_timeline = projection.active
                # Retain the historical cross-zone cache independently of drawing.
                if count:
                    if zone + 1 < len(video.touch_to_next_zone):
                        video.touch_to_next_zone[zone + 1] = projection.carry
                    elif zone + 1 == len(video.touch_to_next_zone):
                        video.touch_to_next_zone.append(projection.carry)

    def draw_timeline2(self):
        if self.__dict__.get("_pose_panel") is not None:
            if self.video and self.video.total_frames >= 0:
                index = self._get_pose_timeline_index()
                self._pose_overview_timeline.draw(
                    index, self.video.total_frames, self.video.current_frame,
                    defer=self.__dict__.get("_defer_timeline_content", False))
            return
        self._assert_ui_thread()
        with self.perf.time("draw_timeline2"):
            if not (self.video and self.video.total_frames > 0):
                return
            self._overview_timeline.draw_overview(
                self.video.frames, self.option_var_1.get(), self.video.total_frames,
                self.video.current_frame,
            )

    def _get_pose_timeline_index(self):
        labels = self.pose_session.labels
        index = self.__dict__.get("_pose_timeline_index")
        if index is None or index.labels is not labels:
            index = self._pose_timeline_index = PoseTimelineIndex(labels, self.video.frames)
            self._pose_detail_timeline = PoseTimelineView(self.timeline_canvas, POSE_DETAIL_FLUSH_INTERVAL_S)
            self._pose_overview_timeline = PoseTimelineView(self.timeline2_canvas)
        return index

    def _pose_annotation_changed(self, frame):
        """Update recorded Pose/shared marks without invalidating Touch caches."""
        if self.video is None or self.__dict__.get("_pose_panel") is None:
            return
        index = self._get_pose_timeline_index()
        events_changed = index.update(frame, self.video.frames.get(frame, {}))
        self._pose_detail_timeline.changed(frame, events_changed)
        self._pose_overview_timeline.changed(frame, events_changed)
        if getattr(self, "_play_ui_pending", False):
            # A played frame's carry: _refresh_playback_ui draws both timelines
            # (dirty columns included) on its next playhead move, and always
            # when playback pauses or stalls.
            return
        self.draw_timeline()
        self.draw_timeline2()

    def update_frame_counter(self):
        # Runs on every control refresh (25 Hz in playback): each call below is
        # a no-op when nothing changed, and the counters have a fixed width.
        self.frame_nav.set_enabled("select", self.video is not None)
        if self.video:
            self.frame_counter_label.set(self.video.current_frame, self.video.total_frames)

            if self.video.frame_rate:
                current_time = self.video.current_frame / self.video.frame_rate * 1000
                total_time = self.video.total_frames / self.video.frame_rate * 1000
                self.time_counter_label.set(format_counter_time(int(current_time), int(total_time)),
                                            format_counter_time(int(total_time), int(total_time)))
            else:
                # FPS probe returned 0/None for this container; time is unknowable.
                self.time_counter_label.set("--:--", "--:--")

        else:
            self.frame_counter_label.set(0, 0)
            return

        self.video.current_frame_zone = int(self.video.current_frame / self.video.number_frames_in_zone)

    def _format_duration(self, seconds):
        if seconds is None:
            return "--:--"
        seconds = int(max(0, seconds))
        minutes, secs = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours}:{minutes:02}:{secs:02}"
        return f"{minutes}:{secs:02}"

    def _open_frame_progress_window(self):
        return self._open_progress_window("Preparing Frames", "Preparing frames...")

    def _open_video_copy_progress_window(self):
        return self._open_progress_window("Copying Video", "Copying video to project...")

    def _open_data_progress_window(self):
        return self._open_progress_window("Loading Data", "Loading labeled data...")

    def _open_progress_window(self, title, heading, *, frame_job=None):
        win = tk.Toplevel(self)   # hidden until settled and centred (gui.window_reveal)
        win.title(title)
        win.geometry(f"{theme.px(PROGRESS_WINDOW_W)}x{theme.px(PROGRESS_WINDOW_H)}")
        win.resizable(False, False)
        win.transient(self)
        theme.bind_colors(win, bg="WIN")

        # Layout: one shared left/right edge for every row.
        #   Heading
        #   Stage ......................... percent
        #   [=============== bar ===============]
        #   count / total ...... Elapsed m:ss   Remaining m:ss
        # Nothing may wiggle while values change. Numbers use the theme's
        # numeric font (equal-width digits) and are anchored so they only ever
        # grow away from their neighbours: percent and Remaining from the right
        # edge leftwards, the count leftwards from the "/".
        content = ttk.Frame(win, padding=(theme.px(20), theme.px(16)))
        content.pack(fill="both", expand=True)
        ttk.Label(content, text=heading, font=theme.FONT_TITLE,
                  anchor="w").pack(fill="x", pady=(0, theme.px(10)))

        stage_row = ttk.Frame(content)
        stage_row.pack(fill="x")
        percent_label = ttk.Label(stage_row, text="0.0%", font=theme.FONT_NUMERIC_MEDIUM,
                                  anchor="e")
        percent_label.pack(side="right")
        status = ttk.Label(stage_row, text="Starting...", font=theme.FONT_BASE, anchor="w")
        status.pack(side="left", fill="x", expand=True)

        bar = ttk.Progressbar(
            content,
            mode="determinate",
            length=theme.px(PROGRESS_BAR_LENGTH),
        )
        bar.pack(fill="x", pady=(theme.px(6), theme.px(8)))

        detail_row = ttk.Frame(content)
        detail_row.pack(fill="x")
        count_label = ttk.Label(detail_row, text="0", font=theme.FONT_NUMERIC_SMALL, anchor="e")
        count_label.pack(side="left")
        total_label = ttk.Label(detail_row, text=" / --", font=theme.FONT_NUMERIC_SMALL,
                                anchor="w")
        total_label.pack(side="left")

        eta_label = ttk.Label(detail_row, text="--:--", font=theme.FONT_NUMERIC_SMALL,
                              width=PROGRESS_TIME_WIDTH, anchor="e")
        eta_label.pack(side="right")
        ttk.Label(detail_row, text="Remaining", font=theme.FONT_SMALL,
                  style="Muted.TLabel").pack(side="right")
        elapsed_label = ttk.Label(detail_row, text="0:00", font=theme.FONT_NUMERIC_SMALL,
                                  width=PROGRESS_TIME_WIDTH, anchor="w")
        elapsed_label.pack(side="right", padx=(0, theme.px(16)))
        ttk.Label(detail_row, text="Elapsed ", font=theme.FONT_SMALL,
                  style="Muted.TLabel").pack(side="right")
        window_reveal.place_on_reveal(win, lambda: center_over_parent(win, self))

        stage_starts = {}  # stage -> (count, elapsed_s) at its first report

        def update(count, total, stage, elapsed_s):
            try:
                if not win.winfo_exists():
                    return
                total = max(1, int(total))
                count = min(int(count), total)
                bar["maximum"] = total
                bar["value"] = count
                pct = (count / total) * 100 if total else 0
                status.config(text=stage)
                total_text = f"{total:,}"
                # Reserve the total's width so the count fills in right-aligned.
                count_label.config(text=f"{count:,}", width=len(total_text))
                total_label.config(text=f" / {total_text}")
                percent_label.config(text=f"{pct:.1f}%")
                # Measure speed only over work done since this stage's first
                # report. A resumed run starts counting at the first missing
                # frame, so count / elapsed would credit the frames that were
                # already there to this run and report far too little time.
                start_count, start_s = stage_starts.setdefault(stage, (count, elapsed_s))
                done = count - start_count
                eta_s = None
                if done > 0 and elapsed_s > start_s:
                    rate = (elapsed_s - start_s) / done
                    eta_s = max(0.0, (total - count) * rate)
                elapsed_label.config(text=self._format_duration(elapsed_s))
                eta_label.config(text=self._format_duration(eta_s))
                if frame_job is None:
                    win.update_idletasks()
                    win.update()
            except tk.TclError:
                pass

        def close():
            try:
                if win.winfo_exists():
                    win.destroy()
            except tk.TclError:
                # The root may have been destroyed while update() was pumping
                # events for a long-running operation.
                pass

        if frame_job is not None:
            def cancel():
                frame_job.cancel()
                status.config(text="Cancelling... Keeping completed frames.")

            def poll():
                if not frame_job.thread.is_alive():
                    close()
                    return
                if not frame_job.cancel_event.is_set() and frame_job.progress is not None:
                    update(*frame_job.progress)
                win.after(FRAME_PREPARATION_POLL_MS, poll)

            win.protocol("WM_DELETE_WINDOW", cancel)
            window_reveal.modal_grab(win)
            frame_job.start()
            win.after(FRAME_PREPARATION_POLL_MS, poll)
            # Tk continues handling input while the Python load flow waits.
            # Only this thread reads SQLite or accesses any Tk widgets.
            win.wait_window()
        return update, close

    def _run_frame_extraction(self, video_path, paths, mode, expected_last_frame):
        job = FramePreparationJob(lambda **kwargs: project_service.extract_frames(
            video_path, paths, mode, **kwargs))
        self._frame_extraction_job = job
        self._frame_extraction_cancel = job.cancel_event
        try:
            self._open_progress_window("Preparing Frames", "Preparing frames...", frame_job=job)
            job.result()
            if not project_service.frames_ready(paths, expected_last_frame):
                raise FrameExtractionError("The extracted frame sequence is incomplete. Resume preparation to retry.")
        finally:
            self._frame_extraction_cancel = None
            self._frame_extraction_job = None

    def _run_export_with_progress(self, export_fn):
        """Run a full export off the Tk thread while a modal stays responsive.
        Returns what `export_fn` returned; re-raises what it raised."""
        return LabelingApp._run_with_progress(
            self, export_fn, title="Saving Data", heading="Building full export...",
            status="Writing export snapshot", thread_name="data-export",
        )

    def _run_with_progress(self, work, *, title, heading, status, thread_name="background-work"):
        """Run blocking `work()` on a worker thread behind a modal window with
        a moving bar and an elapsed-time line, so the app never looks frozen.

        `work` must not touch Tk or the state database (both belong to this
        thread). Returns what `work` returned; re-raises what it raised.
        """
        self._assert_ui_thread()
        win = tk.Toplevel(self)   # hidden until settled and centred (gui.window_reveal)
        win.title(title)
        win.geometry(f"{theme.px(PROGRESS_WINDOW_W)}x{theme.px(EXPORT_WINDOW_H)}")
        win.resizable(False, False)
        win.transient(self)
        theme.bind_colors(win, bg="WIN")
        win.protocol("WM_DELETE_WINDOW", lambda: None)

        content = ttk.Frame(win, padding=theme.px(16))
        content.pack(fill="both", expand=True)
        ttk.Label(content, text=heading, font=theme.FONT_TITLE).pack(
            pady=(2, 8)
        )
        # A fixed character width: the elapsed digits are proportional in the UI
        # font, so the label would otherwise resize (and re-centre) every second.
        status_text = f"{status} - elapsed {self._format_duration(0)}"
        status_label = ttk.Label(content, text=status_text, font=theme.FONT_BASE,
                                 width=len(status_text) + EXPORT_STATUS_SLACK_CHARS, anchor="center")
        status_label.pack()
        bar = ttk.Progressbar(
            content,
            mode="indeterminate",
            length=theme.px(PROGRESS_BAR_LENGTH),
        )
        bar.pack(pady=10)
        bar.start(12)
        window_reveal.place_on_reveal(win, lambda: center_over_parent(win, self))
        window_reveal.modal_grab(win)

        started = time.perf_counter()
        result = {}
        done = Event()

        def worker():
            try:
                result["value"] = work()
            except Exception as exc:
                result["error"] = exc
            finally:
                done.set()

        Thread(target=worker, name=thread_name, daemon=True).start()

        def poll_worker():
            if done.is_set():
                bar.stop()
                win.destroy()
                return
            elapsed = time.perf_counter() - started
            status_label.config(text=f"{status} - elapsed {self._format_duration(elapsed)}")
            win.after(100, poll_worker)

        win.after(100, poll_worker)
        win.wait_window()
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def _prepare_video_copy(self, source_path):
        """Ensure the video lives inside the project videos folder; returns the
        path to use, or None when the copy failed. The decision is the
        service's; the progress window and warnings are ours."""
        dest_path, action, size_mismatch = project_service.plan_video_copy(source_path)

        if action == "in_place":
            return dest_path

        if action == "existing":
            if size_mismatch:
                messagebox.showwarning(
                    "Video Copy Skipped",
                    "A video with the same name already exists in the videos folder.\n"
                    "Using the existing copy to avoid overwriting."
                )
            return dest_path

        progress_update, progress_close = self._open_video_copy_progress_window()
        try:
            project_service.copy_file_with_progress(source_path, dest_path, progress_update)
        except Exception as exc:
            logger.exception("failed to copy video to %s", dest_path)
            messagebox.showerror("Video Copy Failed", f"Failed to copy video:\n{exc}")
            return None
        finally:
            progress_close()

        logger.info("copied video to %s", dest_path)
        return dest_path

    # === Frame Buffer Boundary (GUI side of adapters.frame_buffer) =============
    def _buffer_context(self):
        """Per-tick state snapshot for the buffering thread, built on demand.

        Workers must NOT touch Tk widgets (H1), so instead of winfo_width/height
        this hands over the geometry cache maintained on the main thread
        (on_resize + load_video).
        """
        if self._suspend_frame_workers or self.video is None or self.video.frames_dir is None:
            return None
        return BufferContext(
            frames_dir=self.video.frames_dir,
            current_frame=self.video.current_frame,
            total_frames=self.video.total_frames,
            display_w=self._display_w,
            display_h=self._display_h,
            downscale=float(getattr(self, "video_downscale", 1.0) or 1.0),
            jump_frame_count=max(1, getattr(self, "jump_frame_count", 1)),
            last_step_sign=self._last_step_sign,
            resize_in_worker=getattr(self, "_gpu_video", None) is None,
        )

    def _apply_play_advance(self, next_frame, direction):
        """Apply one playback step: move to `next_frame` and redraw.

        Called by _play_tick on the Tk thread, like every other writer of
        video.current_frame (next_frame, timeline clicks, select_frame).
        """
        if self.video is None:
            logger.debug("play advance skipped: no video (shutdown/reload)")
            return
        if getattr(self, "_selecting_frame", False):
            return  # Discard an advance queued just before the dialog paused playback.
        panel = self.__dict__.get("_pose_panel")
        if panel is not None:
            navigation = (Navigation.FORWARD_HOLD if direction > 0 and getattr(self, "_hold_play_active", False)
                          else Navigation.PLAY)
            panel.request_navigation(self.video.current_frame, next_frame, navigation)
        self.video.current_frame = next_frame
        self._last_step_sign = direction
        self._play_ui_pending = True
        try:
            self.display_first_frame(refresh_ui=False)
            self._refresh_playback_ui()
        except tk.TclError as exc:
            # Expected only when the app is being torn down mid-playback.
            logger.debug("play advance redraw aborted during teardown: %s", exc)

    def _on_playback_boundary(self, current_frame, direction):
        """Playback hit the edge it was moving toward — stop cleanly."""
        self.stop_video()
        self._hold_play_active = False
        self.play_dir = 1
        logger.debug("playback stopped at boundary: frame=%s direction=%s", current_frame, direction)

    @staticmethod
    def _compute_play_step(current_frame, total_frames, direction):
        """Pure play-step decision: (next_frame, stop). No Tk, no side effects.
        Lives in domain.playback.compute_play_step; kept here as the
        stable entry point the H1 tests pin."""
        return compute_play_step(current_frame, total_frames, direction)

    def _buffer_reset(self):
        """Drop the whole buffer and bump its generation (see FrameBuffer.reset)."""
        self.frame_buffer.reset()

    # === Frame Display =========================================================
    def _prepare_video_renderer(self):
        if self.config.video_renderer == "cpu":
            self._renderer_status.set("CPU")
            label = getattr(self, "frame_label", None)
            if label is not None:
                label.pack(expand=True)
            return
        if self._gpu_video is not None or self._gpu_failed:
            return
        label = getattr(self, "frame_label", None)
        if label is not None:
            label.pack_forget()
        try:
            self._gpu_video = GpuVideoSurface(
                self.video_frame, self._on_gpu_redraw_failure, theme.WIN)
            self._gpu_video.set_corners(theme.px(VIDEO_CORNER_RADIUS))
            self._refresh_video_badge()
        except (ImportError, OSError, RuntimeError, tk.TclError) as error:
            self._gpu_failed = True
            self._renderer_status.set("CPU (GPU unavailable)")
            logger.warning("GPU renderer unavailable; using CPU: %s", error)
            if label is not None:
                label.pack(expand=True)
        else:
            self._renderer_status.set("GPU")
            logger.info("Video rendering: GPU (%s)", self._gpu_video.name)

    def _disable_gpu(self, error):
        surface = self._gpu_video
        self._gpu_video = None
        self._gpu_failed = True
        if surface is not None:
            surface.close()
        label = getattr(self, "frame_label", None)
        if label is not None:
            label.pack(expand=True)
        self._renderer_status.set("CPU (GPU unavailable)")
        logger.warning("GPU drawing failed; using CPU: %s", error)
        self._buffer_reset()  # Discard in-flight GPU-sized decodes before CPU mode.

    def _on_gpu_redraw_failure(self, error):
        source = self._displayed_image
        self._disable_gpu(error)
        if source is not None:
            # Keep the last confirmed frame visible until the buffer is rebuilt.
            self._show_frame_image(source)

    def _show_frame_image(self, pil_img):
        """Show `pil_img` (GPU or CPU) and line the timeline card up with the frame."""
        # Called through the class so display-pipeline unit tests can bind
        # this method onto a lightweight stub that lacks the helpers.
        size = LabelingApp._paint_frame_image(self, pil_img)
        if size and getattr(self, "timeline_card", None) is not None:
            align_timeline_to_video(self, max(0, (int(self._display_w) - int(size[0])) // 2))
        return size

    def _paint_frame_image(self, pil_img):
        """Put `pil_img` on the video label, reusing the PhotoImage on screen.

        Pasting new pixels into the image that is already displayed skips
        creating a Tk image, deleting the old one and reconfiguring the label
        — the dominant UI-thread cost per frame on big panels (~30 % less,
        SMOOTHNESS_PLAN.md step 4). paste() only copies pixels into the
        existing image, so a frame of another size or mode (after a resize)
        still gets a fresh one.
        """
        surface = getattr(self, "_gpu_video", None)
        if surface is not None:
            try:
                surface.show(pil_img, self.video_downscale)
                return compute_target_size(*pil_img.size, self._display_w, self._display_h,
                                           self.video_downscale)
            except VideoRendererError as error:
                self._disable_gpu(error)
        if isinstance(pil_img, GpuFrame):
            # A failed upload leaves a GPU buffer frame (B, G, R, X bytes) to
            # draw on the CPU until the buffer is rebuilt.
            pil_img = pil_img.to_image()
        if getattr(self, "_gpu_failed", False):
            # That frame is GPU-sized (never enlarged). Fit it immediately on
            # the CPU as well as rebuilding the future buffer.
            pil_img = resize_for_buffer(pil_img, self._display_w, self._display_h,
                                       self.video_downscale)
            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")
        shown = self._displayed_image
        if (self.image is not None and shown is not None
                and shown.size == pil_img.size and shown.mode == pil_img.mode):
            self.image.paste(pil_img)
            LabelingApp._patch_frame_overlays(self, pil_img)
            return pil_img.size
        photo_img = ImageTk.PhotoImage(pil_img, master=self)
        if getattr(self, "frame_label", None):
            self.frame_label.configure(image=photo_img)
        else:
            self.frame_label = tk.Label(
                self.video_frame,
                image=photo_img,
                bg=theme.WIN,
                bd=0,
                highlightthickness=0,
            )
            self.frame_label.pack(expand=True)
            theme.bind_colors(self.frame_label, bg="WIN")
        self.image = photo_img  # the label does not keep the Python object alive
        LabelingApp._patch_frame_overlays(self, pil_img)
        return pil_img.size

    def _patch_frame_overlays(self, pil_img):
        """Round the shown CPU frame's corners and blend the name badge on it.

        Only small regions are touched: each is cut from `pil_img` (never
        modified: it may live in the buffer), composed, and copied into the
        displayed PhotoImage, so the per-frame cost stays tiny.
        """
        photo_img = self.image
        if not hasattr(photo_img, "tk"):   # no Tk photo on screen (or a test stub)
            return
        w, h = pil_img.size
        if (photo_img.width(), photo_img.height()) != (w, h):
            return
        badge = getattr(self, "name_label", None)
        badge_img = badge.image() if badge is not None else None
        inset = theme.px(BADGE_INSET)
        if badge_img is not None and badge_img.width + 2 * inset <= w and badge_img.height + 2 * inset <= h:
            x, y = w - inset - badge_img.width, inset
            region = pil_img.crop((x, y, x + badge_img.width, y + badge_img.height)).convert("RGBA")
            region = Image.alpha_composite(region, badge_img).convert(pil_img.mode)
            key = (region.size, pil_img.mode)
            if getattr(self, "_badge_photo_key", None) != key:
                self._badge_photo = ImageTk.PhotoImage(pil_img.mode, region.size, master=self)
                self._badge_photo_key = key
            self._badge_photo.paste(region)
            photo_img.tk.call(str(photo_img), "copy", str(self._badge_photo), "-to", x, y)
        r = min(theme.px(VIDEO_CORNER_RADIUS), w // 2, h // 2)
        if r <= 0:
            return
        key = (r, pil_img.mode, theme.WIN)
        if getattr(self, "_corner_key", None) != key:
            top_left = rounded_corner_mask(r)
            flips = (None, Image.Transpose.FLIP_LEFT_RIGHT, Image.Transpose.FLIP_TOP_BOTTOM,
                     Image.Transpose.ROTATE_180)
            self._corner_masks = [top_left if f is None else top_left.transpose(f) for f in flips]
            self._corner_fill = Image.new(pil_img.mode, (r, r), theme.WIN)
            self._corner_photos = [ImageTk.PhotoImage(pil_img.mode, (r, r), master=self) for _ in flips]
            self._corner_key = key
        for (x, y), mask, photo in zip(((0, 0), (w - r, 0), (0, h - r), (w - r, h - r)),
                                       self._corner_masks, self._corner_photos):
            part = pil_img.crop((x, y, x + r, y + r))
            part.paste(self._corner_fill, mask=mask)
            photo.paste(part)
            photo_img.tk.call(str(photo_img), "copy", str(photo), "-to", x, y)

    def _refresh_video_badge(self):
        """Redraw the name badge after its text (or the renderer) changed."""
        badge = getattr(self, "name_label", None)
        if badge is None:
            return
        surface = getattr(self, "_gpu_video", None)
        if surface is not None:
            try:
                surface.set_overlay(badge.image(), theme.px(BADGE_INSET))
            except VideoRendererError as error:
                self._disable_gpu(error)
            return
        shown = getattr(self, "_displayed_image", None)
        if isinstance(shown, GpuFrame):
            # Still the frame a failed GPU upload left on screen (drawn on the
            # CPU by _paint_frame_image): patch the same fitted RGB picture.
            shown = resize_for_buffer(shown.to_image(), self._display_w, self._display_h,
                                      self.video_downscale)
        if shown is not None:
            LabelingApp._patch_frame_overlays(self, shown)

    def display_first_frame(self, frame_number=None, *, refresh_ui=True):
        self._assert_ui_thread()
        with self.perf.time("display_first_frame"):
            if frame_number is None:
                frame_number = self.video.current_frame
            else:
                self.video.current_frame = frame_number
            if frame_number < 0 or frame_number > self.video.total_frames:
                logger.error("frame number out of bounds: %s", frame_number)
                return
            pil_img = self.frame_buffer.get(frame_number)
            if pil_img is not None:
                with self.perf.time("display_frame_photo"):
                    painted_size = self._show_frame_image(pil_img) or pil_img.size
                self._show_buffer_status(True)
                self._displayed_image = pil_img
                self.displayed_frame = frame_number
                for listener in self.frame_paint_listeners:
                    listener(frame_number, painted_size)
            else:
                logger.debug("frame not in buffer: %s", frame_number)
                self._show_buffer_status(False)

            if refresh_ui:
                # Exact navigation and asynchronous repaints refresh immediately.
                self._play_next_due = None
                if getattr(self, "_play_ui_pending", False):
                    self._refresh_playback_ui(force=True)
                else:
                    self._refresh_frame_controls()

    def _refresh_frame_controls(self):
        """Synchronize frame-bound controls, retaining a renderer-switch draft."""
        if self.video is None:
            return
        frame = self.video.current_frame
        preserve = self.__dict__.get("_preserve_note_on_paint")
        same_note_frame = (preserve is not None and preserve[0] is self.video
                           and preserve[1] == frame)
        note_draft = self._get_note_entry_text() if same_note_frame else None
        self.update_note_entry()
        if same_note_frame:
            self._set_note_entry_text(note_draft)
        current_image_painted = (
            self.displayed_frame == frame and self._displayed_image is not None
            and self._displayed_image is self.frame_buffer.get(frame)
        )
        if preserve is not None and (current_image_painted or not same_note_frame):
            self._preserve_note_on_paint = None
        self.update_frame_counter()
        self.update_limb_parameter_buttons()
        self.update_button_colors()
        self._draw_diagram_dots()
        self._play_ui_pending = False

    def _refresh_playback_ui(self, *, force=False):
        """Move the playheads up to 60 times/second; other controls at most 25.

        Up to 60 FPS the playheads follow every frame, like single steps do.
        `force` (pause, stall, exact navigation) always moves them, so they
        rest exactly on the painted frame.
        """
        if self.video is None:
            self._play_ui_pending = False
            return
        now = time.perf_counter()
        head_due = getattr(self, "_playhead_next_due", None)
        if force or head_due is None or now >= head_due - PLAYBACK_PLAYHEAD_JITTER_S:
            # A played frame may batch its Pose scale-trace update (see
            # gui.pose_timeline); a forced refresh shows everything at once.
            self._defer_timeline_content = not force
            try:
                self.draw_timeline()
                self.draw_timeline2()
            finally:
                self._defer_timeline_content = False
            on_time = head_due is not None and now - head_due < PLAYBACK_PLAYHEAD_INTERVAL_S
            self._playhead_next_due = (head_due if on_time else now) + PLAYBACK_PLAYHEAD_INTERVAL_S
        due = self._play_ui_next_due
        if not force and due is not None and now < due:
            return
        self._refresh_frame_controls()
        # Anchor on the due time, not on when this refresh finished: otherwise
        # 25-30 fps playback skips every other refresh (12-15 Hz).
        if due is not None and 0 <= now - due < PLAYBACK_UI_INTERVAL_S:
            self._play_ui_next_due = due + PLAYBACK_UI_INTERVAL_S
        else:
            self._play_ui_next_due = now + PLAYBACK_UI_INTERVAL_S

    def _flush_playback_ui(self):
        """Complete a deferred refresh before pausing, editing, or stalling."""
        if getattr(self, "_play_ui_pending", False):
            self._refresh_playback_ui(force=True)
        # Pose scale traces that the last played frames left batched.
        for name in ("_pose_detail_timeline", "_pose_overview_timeline"):
            view = self.__dict__.get(name)
            if view is not None:
                view.flush()

    # === Labeling-time accumulator (service_layer.project_service) =============
    def _current_video_time_s(self) -> float:
        return self.labeling_timer.current_s()

    def _persist_video_time(self):
        """Checkpoint the accumulator, session keeps running."""
        if self.video is None or self.state_repo is None:
            return
        if getattr(self, "annotation_type", "Touch") == "Pose":
            return
        self.labeling_timer.persist(self.state_repo)

    def _finalize_video_time(self):
        """Checkpoint the accumulator and end the session."""
        if self.video is None or self.state_repo is None:
            return
        if getattr(self, "annotation_type", "Touch") == "Pose":
            self.labeling_timer.cancel_session()
            return
        self.labeling_timer.finalize(self.state_repo)

    def _stop_video_timer_if_any(self):
        """Stop the labeling-time timer without persisting, discarding the
        current session's elapsed time. Used when a load aborts after the
        timer was already started (e.g. frame extraction failed)."""
        self.labeling_timer.cancel_session()

    # === Parameter Toggles & Coloring ==========================================
    def update_button_colors(self):
        if self.video is None:
            return
        idx = self.video.current_frame
        b = self.video.frames.get(idx, {})
        params = (b.get("Params") or {})

        for i, btn in ((1, self.par1_btn), (2, self.par2_btn), (3, self.par3_btn)):
            key = self._param_key_for_index(i)
            state = params.get(key)
            theme.set_button_state(btn, state)

    def parameter_dic_insert(self, parameter_index: int):
        """Toggle Param_i (1..3) for the CURRENT frame directly on the bundle."""
        if self.video is None:
            return
        if not LabelingApp._lock_before_annotation(self):
            return
        idx = self.video.current_frame
        new_state = annotation_service.toggle_global_param(
            self.video.frames, idx, parameter_index,
            shared_only=getattr(self, "annotation_type", "Touch") == "Pose",
        )

        # color the right button immediately
        button = {1: self.par1_btn, 2: self.par2_btn, 3: self.par3_btn}[parameter_index]
        theme.set_button_state(button, new_state)

        # mark frame dirty (also redraws the timelines)
        self.mark_bundle_changed(idx)
        annotation_logger.info("f=%s param P%s -> %s", idx, parameter_index, new_state)

    def toggle_limb_parameter(self, param_number: int):
        if getattr(self, "annotation_type", "Touch") == "Pose":
            return
        if not LabelingApp._lock_before_annotation(self):
            return
        limb = self.option_var_1.get()
        frame = self.video.current_frame
        new_state = annotation_service.toggle_limb_param(
            self.video.frames, frame, limb, param_number
        )

        # reflect on button color
        btn = {1: self.limb_par1_btn, 2: self.limb_par2_btn, 3: self.limb_par3_btn}[param_number]
        theme.set_button_state(btn, new_state)

        # mark frame dirty (also redraws the timelines)
        self.mark_bundle_changed(frame)
        annotation_logger.info(
            "f=%s %s limbparam LP%s -> %s", frame, limb, param_number, new_state
        )

    def update_limb_parameter_buttons(self):
        if self.__dict__.get("_pose_panel") is not None:
            return
        if not self.video:
            return
        limb = self.option_var_1.get()
        frame = self.video.current_frame
        b = self.video.frames.get(frame, {})
        rec = b.get(limb, {}) if isinstance(b, dict) else {}
        limb_params = rec.get("LimbParams", {}) if isinstance(rec, dict) else {}

        for i, btn in ((1, self.limb_par1_btn), (2, self.limb_par2_btn), (3, self.limb_par3_btn)):
            key = self._limb_param_key_for_index(i)
            state = limb_params.get(key)
            theme.set_button_state(btn, state)
    
    # === Notes & Frame Selection ===============================================
    def _get_note_entry_text(self):
        return self.note_entry.get("1.0", "end-1c")

    # The note field is disabled without a video; these programmatic edits
    # unlock it for the change and restore its state afterwards.
    def _clear_note_entry(self):
        state = self.note_entry.cget("state")
        self.note_entry.config(state="normal")
        self.note_entry.delete("1.0", tk.END)
        self.note_entry.config(state=state)

    def _set_note_entry_text(self, text):
        self._clear_note_entry()
        state = self.note_entry.cget("state")
        self.note_entry.config(state="normal")
        self.note_entry.insert("1.0", text)
        self.note_entry.config(state=state)

    def select_frame(self):
        """Pause navigation and ask for an absolute frame in a modal dialog."""
        if self.video is None or self._selecting_frame:
            return
        self.stop_video()
        self._cancel_arrow_hold_state()
        self._cancel_wheel_scroll()
        self._selecting_frame = True
        try:
            target = FrameDialog(
                self, self.video.current_frame, self.video.total_frames,
            ).result
        finally:
            self._selecting_frame = False
        self.focus_set()
        if target is not None and target != self.video.current_frame:
            self.next_frame(target - self.video.current_frame, navigation=Navigation.JUMP)

    def save_note(self):
        if not LabelingApp._annotation_frame_ready(self):
            return
        idx = self.video.current_frame
        note_text = self._get_note_entry_text().strip()
        if note_text and not LabelingApp._lock_before_annotation(self):
            return

        changed = annotation_service.set_note(
            self.video.frames, idx, note_text,
            shared_only=getattr(self, "annotation_type", "Touch") == "Pose")
        if changed:
            # mark_bundle_changed already emits the notify_bundle_changed summary.
            self.mark_bundle_changed(idx)
            annotation_logger.info("f=%s note -> %r", idx, note_text)
        self.focus_set()

    def update_note_entry(self):
        if self.video is None:
            return
        idx = self.video.current_frame
        note_text = ""

        b = self.video.frames.get(idx)
        if isinstance(b, dict):
            note_text = (b.get("Note") or "")

        # Playback calls this 25 times a second: rewriting an unchanged note
        # costs eight Tk calls and a Text relayout (about 1 ms), reading it one.
        if self._get_note_entry_text() != note_text:
            self._set_note_entry_text(note_text)

    # === Save / Export =========================================================
    def _save_pose_workspace(self):
        """Save the Pose working state (the database only; `save_data` exports next)."""
        session = self.pose_session
        dialog = self.__dict__.get("_special_zones_app")
        if dialog is not None and dialog.top_level.winfo_exists():
            from service_layer.pose_project_service import special_zone_rows
            session.special_zones = special_zone_rows(dialog.dots, dialog.diagram_scale, self._zone_masks)
            session.special_note = dialog.note()
            session.special_scale = dialog.diagram_scale
        # The save below clears the dirty trackers, so note here that the
        # published CSV no longer matches; only a successful export restores it.
        if pose_export_service.has_unexported_changes(session.labels, self.video.frames):
            self.video.published_export_csv = None
        session.save_workspace(
            self.video.frames, last_frame=self.video.current_frame,
            total_frames=self.video.total_frames,
            labeling_time_seconds=self._current_video_time_s(),
            special_zones=session.special_zones, special_note=session.special_note,
            special_scale=session.special_scale,
        )
        return True

    def _publish_pose_export(self) -> SaveOutcome:
        """Publish the Pose CSV and metadata after a successful database save.

        The CSV is written on a worker thread from detached copies; the SQLite
        connection stays on this thread. A save with nothing edited since this
        session's last export rewrites only the small metadata file, inline.
        Never raises: a failure is `EXPORT_STALE`, the labels are in the DB.
        """
        video = self.video
        # Only a successful export below may vouch for the published CSV again.
        published_csv = getattr(video, "published_export_csv", None)
        video.published_export_csv = None
        started = time.perf_counter()
        try:
            session = self.pose_session
            paths = ProjectPaths(self.video_name, annotation_type="Pose")
            metadata = pose_export_service.PoseExportMetadata(
                program_version=video.program_version,
                video_name=self.video_name,
                labeling_mode=self.labeling_mode,
                coding_setup=getattr(self, "coding_setup", None) or self.state_repo.load_coding_setup(),
                special_zones=tuple(special_zone_ids(session.special_zones)),
                special_zones_note=session.special_note,
                labeling_time_seconds=self._current_video_time_s(),
            )
            frame_rate, total_frames = self.frame_rate, video.total_frames
            if pose_export_service.csv_can_be_reused(paths, published_csv):
                stamp = pose_export_service.run_pose_export(
                    paths, frame_rate, total_frames, metadata, None)
            else:
                content = pose_export_service.capture_content(session.labels, video.frames)
                stamp = self._run_export_with_progress(
                    lambda: pose_export_service.run_pose_export(
                        paths, frame_rate, total_frames, metadata, content))
        except Exception:
            logger.exception("Pose annotations saved to the state database, but the export was NOT updated")
            return SaveOutcome.EXPORT_STALE
        video.published_export_csv = stamp
        logger.info("Pose export published for %s in %.2fs", self.video_name,
                    time.perf_counter() - started)
        return SaveOutcome.SAVED

    def save_from_button(self):
        """The Save button: save, then report anything that did not reach disk.
        Pose reports a failed database save inside `save_data`."""
        outcome = self.save_data()
        if getattr(self, "annotation_type", "Touch") == "Pose" and outcome is SaveOutcome.NOT_SAVED:
            return
        _report_save_outcome(self, outcome)

    def save_data(self) -> SaveOutcome:
        """Save the open project and return what reached disk.

        Touch never raises and shows no dialog here: each caller decides how
        to tell the user (`save_from_button`, `on_close`, `analysis`, ...).
        The state DB is written first and is the source of truth, so a failed
        export alone is `EXPORT_STALE`, not a lost save. Pose follows the same
        order (`_save_pose_workspace`, then `_publish_pose_export`) but shows
        its own error when the database save fails.
        """
        if not self.video or not self.video.frames_dir:
            logger.info("save skipped: no video loaded")
            return SaveOutcome.SAVED
        if self.state_repo is None:
            logger.error("save skipped: no state database is open")
            return SaveOutcome.NOT_SAVED
        if getattr(self, "annotation_type", "Touch") == "Pose":
            try:
                saved = self._save_pose_workspace()
            except Exception as exc:
                logger.exception("Pose workspace save failed; session retained for retry")
                messagebox.showerror("Save failed", f"The Pose project remains open for retry.\n{exc}", parent=self)
                return SaveOutcome.NOT_SAVED
            if not saved:
                return SaveOutcome.NOT_SAVED
            logger.info("Pose workspace saved for %s", self.video_name)
            return self._publish_pose_export()
        started = time.perf_counter()
        video = self.video
        dirty_count = count_unsaved_frames(video.frames)
        paths = ProjectPaths(self.video_name)
        logger.info("saving %s changed frames", dirty_count)
        logger.debug(
            "save paths: video=%s state=%s export=%s frames=%s",
            paths.video_dir,
            paths.state_db,
            paths.export_csv,
            video.frames_dir,
        )

        # 1) Dirty frames -> state DB, one transaction. UI thread (the repo
        #    enforces that itself); this is the source of truth.
        try:
            self._persist_video_time()
            self.preview_before_save(changed_only=True)
            os.makedirs(paths.state_dir, exist_ok=True)
            save_service.persist_state(self.state_repo, video.total_frames, video.frames)
        except Exception:
            logger.exception("save failed: the state database was not updated")
            return SaveOutcome.NOT_SAVED

        # Only a successful export below may vouch for the published CSV again.
        published_csv, video.published_export_csv = video.published_export_csv, None
        try:
            # Non-tabular inputs gathered here: the button labels are Tk reads and
            # the labeling clock must be sampled on the UI thread.
            metadata = save_service.MetadataInputs(
                program_version=video.program_version,
                video_name=self.video_name,
                labeling_mode=self.labeling_mode,
                special_zones_list=save_service.load_special_zones(self.state_repo),
                special_zones_note=save_service.load_special_zones_note(self.state_repo),
                param_labels={
                    "Parameter_1": (self.par1_btn.cget("text") or "Par1"),
                    "Parameter_2": (self.par2_btn.cget("text") or "Par2"),
                    "Parameter_3": (self.par3_btn.cget("text") or "Par3"),
                },
                limb_param_labels=self._limb_param_labels_for_export(),
                labeling_time_seconds=self._current_video_time_s(),
                template=self.state_repo.load_template().template,
                zone_labels=dict(self.zone_display.labels),
                coding_setup=getattr(self, "coding_setup", None),
            )

            # 2) Snapshot BEFORE the worker-thread export so concurrent edits can
            #    neither tear the export nor be wrongly marked clean afterwards.
            snapshot = save_service.build_save_snapshot(video.frames)
            total_frames = video.total_frames
            frame_rate = self.frame_rate

            # 3) Export (metadata, diagram, and the CSV unless it is unchanged)
            #    on a worker thread while a modal progress dialog keeps the UI
            #    responsive.
            stamp = self._run_export_with_progress(
                lambda: save_service.run_export(
                    snapshot, paths, frame_rate, metadata, total_frames,
                    published_csv=published_csv,
                )
            )
        except Exception:
            logger.exception("annotations saved to the state database, but the export was NOT updated")
            return SaveOutcome.EXPORT_STALE
        video.published_export_csv = stamp
        logger.info(
            "save complete: changed_frames=%s export_rows=%s duration=%.2fs",
            dirty_count,
            total_frames + 1,
            time.perf_counter() - started,
        )

        # 4) Clear Changed ONLY where the live bundle still equals its snapshot:
        #    a frame edited DURING the export stays dirty for the next save.
        save_service.clear_clean_flags(video.frames, snapshot)
        return SaveOutcome.SAVED

    def _limb_param_labels_for_export(self):
        """Limb-parameter button labels for the export metadata, or None when
        the limb controls have not been built yet."""
        if self.limb_par1_btn and self.limb_par2_btn and self.limb_par3_btn:
            return {
                "XX_Parameter_1": (self.limb_par1_btn.cget("text") or "CP1"),
                "XX_Parameter_2": (self.limb_par2_btn.cget("text") or "CP2"),
                "XX_Parameter_3": (self.limb_par3_btn.cget("text") or "CP3"),
            }
        return None

    # === Analysis / Sort / Playback ============================================
    def analysis(self):
        """Save, then run the Analysis use case and open its master HTML.

        The service does all reading/computing/writing and hands back the master
        page path; opening the browser stays here (a GUI concern) so the service
        remains headless and testable. The saved project template is passed
        down for validation against the export metadata.
        """
        if not self.video or getattr(self, "annotation_type", "Touch") == "Pose":
            return
        if not self._resolve_open_touches_before_analysis():
            return
        outcome = self.save_data()
        if outcome is not SaveOutcome.SAVED:
            # Analysis reads the export files; never report on an outdated one.
            reason = (EXPORT_STALE_MESSAGE if outcome is SaveOutcome.EXPORT_STALE
                      else NOT_SAVED_MESSAGE)
            messagebox.showerror("Analysis not run",
                                 f"Analysis was not run.\n\n{reason}", parent=self)
            return
        paths = ProjectPaths(self.video_name)
        try:
            result = analysis_service.run_analysis(
                paths,
                frame_rate=self.frame_rate,
                template=self.state_repo.load_template().template,
            )
        except Exception as exc:
            logger.exception("analysis failed for %s", self.video_name)
            messagebox.showerror("Analysis failed", f"Could not complete analysis:\n{exc}")
            return

        if result.warnings:
            messagebox.showwarning(
                "Analysis finished with warnings", "\n\n".join(result.warnings)
            )
        logger.info("opening analysis dashboard: %s", result.master_html)
        webbrowser.open(result.master_html)

    def _channel_display_label(self, key: str) -> str:
        """Coder-facing name of a channel: the coding-setup label when the
        project has one, else the internal key."""
        setup = getattr(self, "coding_setup", None)
        if setup is not None:
            try:
                return setup.channel_labels[key]
            except (KeyError, TypeError):
                pass
        return key

    def _resolve_open_touches_before_analysis(self) -> bool:
        """Surface every onset without an offset, and every offset without an
        onset, before analysis runs.

        Returns True when analysis should proceed (nothing unpaired, or "Skip
        and analyze") and False when the coder cancelled or chose to go and fix
        a mark by hand. Neither is an error for the analysis (an open touch is
        censored and reported as unterminated, a stray offset is ignored), but
        the coder should see them first and decide.
        """
        touches = find_open_touches(self.video.frames, LIMBS)
        return self._resolve_open_touches(touches) is not None

    def _resolve_open_touches(self, touches, *, closing=False):
        """Let the coder navigate, cancel, or continue with touches left open.

        Returns how to continue (ANALYZE_ANYWAY; SAVE_AND_CLOSE or
        DISCARD_AND_CLOSE when closing), or None to stay where we are.
        """
        if not touches:
            return SAVE_AND_CLOSE if closing else ANALYZE_ANYWAY
        operation = "close" if closing else "analysis"
        self.stop_video()
        self._cancel_arrow_hold_state()
        self._cancel_wheel_scroll()
        logger.info(
            "%s: %d unpaired onset/offset mark(s): %s", operation, len(touches),
            ", ".join(f"{t.kind} {t.limb}@{t.start_frame}" for t in touches),
        )
        result = OpenTouchesDialog(
            self, touches, self._channel_display_label, closing=closing,
        ).result
        self.focus_set()
        if result is None:
            logger.info("%s cancelled at the open-touch prompt", operation)
            return None
        action, index = result
        if action == GO_TO_ONSET:
            target = touches[index].start_frame
            logger.info("%s postponed: jumping to unpaired %s %s@%s",
                        operation, touches[index].kind, touches[index].limb, target)
            if target != self.video.current_frame:
                self.next_frame(target - self.video.current_frame)
            return None
        if action not in ((SAVE_AND_CLOSE, DISCARD_AND_CLOSE) if closing else (ANALYZE_ANYWAY,)):
            return None
        logger.info("%s proceeding (%s) with %d unpaired mark(s) left as they are",
                    operation, action, len(touches))
        return action

    def play_video(self):
        if self.video is None:
            logger.error("cannot play: select a video first")
            return
        # Always play forward when the user clicks Play, regardless of any
        # prior arrow-hold state that may have left play_dir = -1.
        self._hold_play_active = False
        self._start_playback(1)
        sync_play_control(self)

    def stop_video(self):
        # Keep the held direction until key-up, so an OS repeat cannot re-arm
        # playback after Stop, annotation, or entering the note editor.
        start_id = getattr(self, "_arrow_start_id", None)
        if start_id is not None:
            self.after_cancel(start_id)
            self._arrow_start_id = None
        self.play = False
        self._pending_buffer_step = None
        self._play_next_due = None
        self._precise_timers.release("playback")
        self._flush_playback_ui()
        sync_play_control(self)

    def toggle_play(self, event=None):
        if self.play:
            self.stop_video()
        else:
            self.play_video()

    # === Video Load & Init =====================================================
    def _annotation_frame_ready(self, *, pause_navigation=True):
        video = getattr(self, "video", None)
        if video is None:
            return True
        ready = getattr(self, "displayed_frame", video.current_frame) == video.current_frame
        if pause_navigation and (getattr(self, "play", False) or getattr(self, "_play_ui_pending", False)
                or getattr(self, "_arrow_start_id", None) is not None):
            self.stop_video()
        if not ready:
            logger.debug("Annotation skipped: frame %s has not been painted yet", video.current_frame)
        return ready

    def _lock_before_annotation(self, *, pause_navigation=True):
        if not LabelingApp._annotation_frame_ready(self, pause_navigation=pause_navigation):
            return False
        if getattr(self, "annotation_type", "Touch") == "Pose":
            return True
        repo = getattr(self, "state_repo", None)
        if repo is None:
            return True
        try:
            repo.lock_template()
            return True
        except (OSError, sqlite3.Error, ValueError) as exc:
            logger.exception("could not lock project template")
            messagebox.showerror("Annotation not added", f"Could not save the project template lock:\n{exc}", parent=self)
            return False

    def ask_template(self):
        initial = DEFAULT_TEMPLATE
        return choose_template(self, initial, center=center_over_parent)

    def _apply_active_template(self, template):
        if getattr(self, "annotation_type", "Touch") == "Pose":
            return
        self.template = template
        self.zone_display = self.state_repo.load_zone_display(template)
        self._reset_zone_cache()
        self._load_zone_masks()
        self.rebuild_annotation_controls()
        if self.video is not None and getattr(self, "coding_setup", None):
            load_parameter_names_into(self.video,
                {1: self.par1_btn, 2: self.par2_btn, 3: self.par3_btn},
                {1: self.limb_par1_btn, 2: self.limb_par2_btn, 3: self.limb_par3_btn}, self.coding_setup)
        self._redraw_diagram()

    def _save_zone_display(self, settings):
        if getattr(self, "annotation_type", "Touch") == "Pose":
            return False
        try:
            self.state_repo.save_zone_display(self.template, settings)
        except (OSError, ValueError, sqlite3.Error) as exc:
            logger.exception("Could not save project zone names")
            messagebox.showerror("Cannot save zone names", str(exc), parent=self)
            return False
        self.zone_display = settings
        self._redraw_diagram()
        if self._special_zones_app and self._special_zones_app.top_level.winfo_exists():
            self._special_zones_app.set_zone_display(settings, self._zone_label_positions)
        # The DB is authoritative; a failed export is retryable via Save.
        _report_save_outcome(self, self.save_data())
        return True

    def edit_project_zone_names(self):
        if getattr(self, "annotation_type", "Touch") == "Pose":
            return
        if self.state_repo and self.state_repo.load_preparation_state() == "ready":
            messagebox.showinfo("Coding setup locked", "Prepared video coding labels are read-only.", parent=self)
            return
        if self.video is None or self.state_repo is None:
            return

        def apply(labels):
            # Visibility is a separate Settings toggle; keep the saved value.
            return self._save_zone_display(ZoneDisplaySettings(labels, self.zone_display.show_names))

        edit_zone_names(
            self._settings_win, editable_zone_names(self.template), self.zone_display,
            apply, center=center_over_parent,
        )

    def change_project_template(self):
        if getattr(self, "annotation_type", "Touch") == "Pose":
            return
        if self.video is None:
            return
        state = self.state_repo.load_template()
        if state.locked:
            messagebox.showinfo("Template locked", "This project's body template is locked.", parent=self)
            return
        if self._special_zones_app and self._special_zones_app.top_level.winfo_exists():
            messagebox.showinfo("Close Special Zones", "Close the Special Zones window before changing the template.", parent=self)
            return
        selected = choose_template(self, state.template, center=center_over_parent)
        if selected is None:
            return
        try:
            self.state_repo.save_template(state.choose(selected))
        except ValueError as exc:
            messagebox.showerror("Template locked", str(exc), parent=self)
            return
        self._apply_active_template(selected)
        _report_save_outcome(self, self.save_data())
        if getattr(self, "_settings_win", None) and self._settings_win.winfo_exists():
            self._settings_win.destroy()
            self.open_settings()

    def ask_labeling_mode(self):
        """Modal mode picker; see gui.app_dialogs.ask_labeling_mode."""
        return app_dialogs.ask_labeling_mode(self)

    def _unload_current_video(self) -> bool:
        """Persist and fully detach the open project — the same writes
        `on_close` performs, without tearing the Tk app down. Returns False
        when the final save failed (after telling the user) or when the user
        chose to keep the video open because its export is out of date; the
        project is then left open untouched so nothing can be lost.

        ORDERING (the data-mixing guard): every writer runs against the OLD
        repo first; then `self.video` drops to None, which idles the
        buffer/playback threads (their context providers return None); then
        the buffer generation is bumped so in-flight decodes of old frames
        discard their result; the state DB closes last.
        """
        if self.video is None:
            return True
        logger.info("unloading video %r (save and close state DB)", self.video_name)

        # Stop playback / arrow-hold before the video identity changes.
        self.stop_video()
        self._cancel_arrow_hold_state()
        self._cancel_wheel_scroll()

        # A leftover Special Zones window writes its dots through the CURRENT repo
        # on close, so close it now, while that repo is still the right one.
        if self._special_zones_app and self._special_zones_app.top_level.winfo_exists():
            logger.debug("closing Special Zones window before unloading")
            if self._special_zones_app.on_close() is False:
                messagebox.showerror("Save Failed", UNLOAD_SAVE_FAILED_MESSAGE, parent=self)
                return False
        self._special_zones_app = None

        try:
            outcome = self.save_data()
        except Exception:
            logger.exception("final save failed while unloading %r", self.video_name)
            outcome = SaveOutcome.NOT_SAVED
        if outcome is SaveOutcome.NOT_SAVED:
            logger.error(
                "unload aborted: final save failed; keeping current video open"
            )
            messagebox.showerror("Save Failed", UNLOAD_SAVE_FAILED_MESSAGE, parent=self)
            return False
        if outcome is SaveOutcome.EXPORT_STALE and not messagebox.askyesno(
            "Export not updated",
            f"{_export_stale_message(self)}\n\nOpen the other video anyway?",
            parent=self,
        ):
            logger.info("unload cancelled: export out of date; keeping current video open")
            return False
        self.save_last_position()
        self._finalize_video_time()

        # Drop the video FIRST: from here on the worker threads see a None
        # context and go idle instead of touching a half-swapped state.
        self.video = None
        self.video_name = None
        self._ghost_cache = None  # drop the reference to the old video
        self._redraw_diagram()
        self.displayed_frame = None
        self._displayed_image = None
        self._last_step_sign = 0
        self._buffer_reset()
        self.frame_buffer.buffer_ready = False

        self._close_state_repo()
        self._reset_zone_cache()
        LabelingApp._restore_empty_annotation_controls(self)

        # UI bits tied to the old project.
        self.update_frame_counter()
        self._set_note_entry_text("")
        theme.set_button_state(self.special_zones_btn, None)
        self.name_label.config(text="Video Name: -----")
        self.framerate_label.config(text="Frame Rate: -----")
        self._refresh_jump_label()
        self._set_mode_button_states()
        return True

    def _abort_load_to_clean_state(self):
        """A load failed AFTER the previous project was already detached.
        Return to the well-defined startup state (no video, no repo, no
        timer, empty buffer) instead of leaving a half-loaded session."""
        logger.info("video load aborted; returning to clean no-video state")
        self._stop_video_timer_if_any()
        self._close_state_repo()
        self._reset_zone_cache()
        self.video = None
        self.video_name = None
        LabelingApp._restore_empty_annotation_controls(self)
        self._ghost_cache = None  # drop the reference to the old video
        self._redraw_diagram()
        self.displayed_frame = None
        self._displayed_image = None
        self._buffer_reset()
        self.update_frame_counter()
        self._set_mode_button_states()

    def open_startup_project(self, last_project):
        """What the app shows first: the project that was open at the last
        close (`(name, annotation type)`, resumed on its saved frame), or the
        video library when there was none or it can no longer be resumed."""
        entry = find_resumable(list_projects(), last_project)
        if last_project is not None and entry is None:
            logger.info("last project %r cannot be resumed; opening the library", last_project)
        self.load_video(entry)

    def load_video(self, choice=None):
        """Load Video button (`choice` None: ask in the library). Suspends the buffer/playback workers until the
        new video is fully published so they can never observe a
        half-published one (_publish_loaded_video wakes them itself, so the
        first frame can be painted while the content swap still covers the
        window), and wakes them once the load finished (successfully or not —
        an aborted load ends with video=None, which keeps them idle anyway)."""
        self._suspend_frame_workers = True
        try:
            self._load_video_flow(choice)
        finally:
            self._suspend_frame_workers = False
            self.frame_buffer.poke()

    def _load_video_flow(self, choice=None):
        if choice is None:
            choice = choose_video(self, list_projects(), center=center_over_parent)
        if choice is None:
            return
        if choice == "new":
            with center_native_file_dialog(self):
                video_path = filedialog.askopenfilename(parent=self, title="Select Video File",
                    filetypes=(("Video files", "*.mp4 *.MP4 *.mov *.MOV *.avi *.AVI *.mkv *.MKV *.flv *.FLV *.wmv *.WMV"), ("All files", "*.*")))
            if not video_path:
                return
            annotation_type = choose_annotation_type(self, center=center_over_parent)
            if annotation_type is None:
                return
            mode = self.ask_labeling_mode()
            if mode is None:
                return
            raw_video_name = os.path.splitext(os.path.basename(video_path))[0]
            candidate_paths = ProjectPaths.for_video(raw_video_name, reliability=mode == "Reliability", annotation_type=annotation_type)
            if os.path.exists(candidate_paths.state_db):
                copy_paths = next_copy_project(candidate_paths)
                duplicate_choice = choose_existing_video(
                    self, candidate_paths.video_name, copy_paths.video_name,
                    center=center_over_parent,
                )
                if duplicate_choice is None:
                    return
                if duplicate_choice == "copy":
                    candidate_paths = copy_paths
                    mode = "Normal"
        else:
            video_path = choice.source
            candidate_paths = choice.paths
            annotation_type = candidate_paths.annotation_type
            mode = "Reliability" if candidate_paths.is_reliability else "Normal"

        fingerprints = {}

        def fingerprint(path):
            """SHA-256 of a source video: hashed once per load, off the Tk
            thread (a 3-hour file takes seconds when the disk cache is cold)."""
            key = os.path.abspath(path)
            if key not in fingerprints:
                fingerprints[key] = self._run_with_progress(
                    lambda: project_service.source_fingerprint(path),
                    title=LOAD_PROGRESS_TITLE, heading="Checking the video file...",
                    status="Verifying the source video", thread_name="video-fingerprint",
                )
            return fingerprints[key]

        try:
            setup, ready = project_service.inspect_coding_setup(candidate_paths)
            state = (SqliteRepository.inspect_template(candidate_paths.state_db)
                     if annotation_type == "Touch" else None)
            if not ready and not project_service.can_resume_preparation(candidate_paths):
                setup = (configure_pose_video(self, setup, center=center_over_parent)
                         if annotation_type == "Pose" else
                         configure_video(self, setup, center=center_over_parent, locked_template=bool(state and state.locked)))
                if setup is None:
                    return
            if setup is None:
                raise ValueError("Review and prepare this video's coding setup first.")
            template_plan = (project_service.plan_project_template(candidate_paths, setup.template)
                             if annotation_type == "Touch" else None)
            project_service.validate_source_association(
                candidate_paths, video_path, hash_source=fingerprint)
        except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
            messagebox.showerror("Cannot open video", str(exc), parent=self)
            return

        # 2) Read-only preparation of the NEW video (copy + probe) while the
        #    current project, if any, is still fully alive — a failure here
        #    cancels the load without disturbing it.
        try:
            copied_path = self._prepare_video_copy(video_path)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Cannot copy video", str(exc), parent=self)
            return
        if not copied_path:
            logger.info("video load cancelled: copy failed")
            return
        video_path = copied_path

        # Probe once (adapter); the Video model itself does no I/O anymore.
        raw_frame_count, fps = video_probe.probe(video_path)

        # 3) Persist and detach the current project (no-op on first load).
        #    From here on the app is in the clean "no video" state; any later
        #    failure aborts back to it instead of leaving a half-loaded mix.
        if not self._unload_current_video():
            return  # the user was already told why the current video stays open

        # Commit the mode only now that the load is actually going ahead.
        self.annotation_type = annotation_type
        self.labeling_mode = mode
        annotation_logger.info("mode %s selected for video %s", mode, os.path.basename(video_path))
        self.mode_label.set(
            theme.STATUS_WARN if mode == "Reliability" else theme.STATUS_OK,
            f"{annotation_type} / {mode}"
        )

        # 4) Build the new session against a LOCAL Video object. self.video
        #    is assigned only at the commit point below, once the state DB is
        #    open and the frames exist — until then the buffer/playback
        #    threads idle on a None context, so frames of two videos can
        #    never mix in the buffer.
        video = Video(video_path, total_frames=raw_frame_count - 1)
        video.frame_rate = fps
        self.frame_rate = video.frame_rate
        self.framerate_label.config(text=f"Frame Rate: {self.frame_rate}")
        self.jump_frame_count = max(1, round(self.frame_rate * self.jump_seconds))
        logger.debug(
            "fast jump set to %s frames (%ss at %s fps)",
            self.jump_frame_count,
            self.jump_seconds,
            self.frame_rate,
        )
        min_length_in_frames = self.minimal_touch_length * self.frame_rate / 1000
        self.min_touch_length_label.config(text=f"Minimal Touch Length: {min_length_in_frames}")
        raw_video_name = candidate_paths.original.video_name
        # The "_reliability" suffix rule and directory creation live in the
        # service (ProjectPaths.for_video underneath).
        paths = project_service.prepare_project(raw_video_name, self.labeling_mode, annotation_type)
        video_name = paths.video_name

        video.frames_dir = paths.frames_dir

        # --- Working state: open (or create) state/<video>.db. The progress
        # window covers the whole phase because `load_frames` below reads every
        # row of a long project.
        data_progress_update, data_progress_close = self._open_data_progress_window()
        try:
            self.state_repo = project_service.open_state(
                paths,
                fps=self.frame_rate,
                program_version=video.program_version,
            )
            if template_plan is not None:
                project_service.apply_project_template(self.state_repo, template_plan)
            if annotation_type == "Pose":
                from service_layer.pose_project_service import PoseProjectSession
                self.pose_session = PoseProjectSession.from_repository(self.state_repo)
            self.state_repo.save_coding_setup(setup, preparation_state="ready" if ready else "draft")
            self.state_repo.set_meta(SOURCE_META, os.path.abspath(video_path))
            self.state_repo.set_meta("source_video_sha256", fingerprint(video_path))
            self.coding_setup = setup
            # ORDERING (unchanged): the labeling timer starts BEFORE the frame
            # load so the session is already accumulating; an extraction abort
            # below rolls it back via _stop_video_timer_if_any().
            self.labeling_timer.start(self.state_repo)
            video.frames = self.state_repo.load_frames(
                progress_cb=data_progress_update
            )
        except Exception as exc:
            logger.exception("could not open working state for %s", video_name)
            messagebox.showerror(
                "Load Failed",
                f"Could not open the working state for this video:\n\n{exc}\n\n"
                "The video was not loaded.",
            )
            self._abort_load_to_clean_state()
            return
        finally:
            data_progress_close()

        # Frames generation/check
        # Listing the frames folder of a long video takes seconds (344k files:
        # 1-9 s), so it runs off the Tk thread behind a progress window.
        logger.debug("checking frames folder: %s", paths.frames_dir)
        frames_complete = ready and self._run_with_progress(
            lambda: project_service.frames_ready(paths, video.total_frames),
            title=LOAD_PROGRESS_TITLE, heading="Checking video frames...",
            status="Counting the prepared frames", thread_name="frames-check",
        )
        if not frames_complete:
            logger.info("frame set incomplete; extracting frames for %s", video_name)
            if not ready:
                self.state_repo.set_meta("preparation_state", "preparing")
            try:
                self._run_frame_extraction(video_path, paths, self.labeling_mode, video.total_frames)
            except FrameExtractionCancelled:
                logger.info("frame extraction cancelled; saved preparation retained")
                if self._closing:
                    self._stop_video_timer_if_any()
                else:
                    self._abort_load_to_clean_state()
                return
            except FrameExtractionError as exc:
                logger.error("frame extraction failed for %s: %s", video_name, exc)
                messagebox.showerror(
                    "Frame Extraction Failed",
                    f"Could not extract frames from this video:\n\n{exc}\n\n"
                    "The file may be unreadable or use an unsupported codec. "
                    "The video was not loaded.",
                )
                # Roll back the labeling timer and the state DB opened above,
                # ending in the clean "no video loaded" state.
                self._abort_load_to_clean_state()
                return
        else:
            logger.debug("frame set is complete for %s", video_name)

        try:
            self.state_repo.mark_prepared()
        except (ValueError, OSError, sqlite3.Error) as exc:
            messagebox.showerror("Preparation failed", str(exc), parent=self)
            self._abort_load_to_clean_state()
            return

        # 5) COMMIT POINT: the state DB is open, the frames exist on disk, and
        #    every dialog of the load (library, wizard, progress windows) is
        #    closed. Rebuild the main window for the new video behind a cover
        #    that stays until its first frame is painted, so the window
        #    switches from the old picture to the finished one in one step.
        #    The cover drops at the timeout if the frame is late, if the
        #    publish raises, or if a dialog or message box activates meanwhile.
        try:
            content_swap.swap_content(
                self, lambda: self._publish_loaded_video(video, video_name),
                ready=lambda: self._first_frame_shown(video),
                timeout_ms=LOAD_FIRST_FRAME_TIMEOUT_MS,
            )
        except Exception as exc:
            logger.exception("Could not publish loaded video")
            self._abort_load_to_clean_state()
            messagebox.showerror("Load failed", str(exc), parent=self)

    def _first_frame_shown(self, video):
        """The load's swap may end: `video`'s current frame is on screen, or
        `video` is no longer the published one (closed or replaced)."""
        return self.video is not video or self.displayed_frame == video.current_frame

    def _publish_loaded_video(self, video, video_name):
        """Publish the loaded session to the app and rebuild the window for it.

        Runs inside the load's content swap. The frame workers stay suspended
        until the last lines, so they never see a half-published session.
        """
        # Names for parameters (update button text)
        load_parameter_names_into(
            video,
            {1: self.par1_btn, 2: self.par2_btn, 3: self.par3_btn},
            {1: self.limb_par1_btn, 2: self.limb_par2_btn, 3: self.limb_par3_btn},
            setup=getattr(self, "coding_setup", None),
        )
        self.video = video
        self.video_name = video_name
        self._prepare_video_renderer()
        if getattr(self, "annotation_type", "Touch") == "Pose":
            self.template = self.coding_setup.template
            self.zone_display = ZoneDisplaySettings(self.coding_setup.zone_labels, show_names=bool(self.coding_setup.zone_labels))
            self._reset_zone_cache()
            self._load_zone_masks()
            self.rebuild_annotation_controls()
            self._redraw_diagram()
        else:
            self._apply_active_template(self.state_repo.load_template().template)
        self._refresh_jump_label()

        self._detail_timeline.reset()
        self._overview_timeline.reset()

        self.restore_last_position()

        t_draw = time.time()
        self.display_first_frame()
        self.draw_timeline()
        self.draw_timeline2()
        logger.debug("initial video draw completed in %.1fs", time.time() - t_draw)
        self.name_label.config(
            text=f"Video: {video_name} | FPS: {self.frame_rate} | Version: {self.video.program_version}"
        )

        # Seed the geometry cache on the main thread before the buffer thread
        # runs — workers read _display_w/_display_h instead of winfo_* (H1).
        self._display_w = self.video_frame.winfo_width()
        self._display_h = self.video_frame.winfo_height()

        # Lazily started once; on a reload it is already alive and simply
        # picks the new video up from its context provider. The buffer itself
        # was emptied (generation-bumped) in _unload_current_video, BEFORE the
        # new video was published, so it cannot hold stale frames here.
        if not self.background_thread.is_alive():
            self.background_thread.start()

        self.update_note_entry()

        # Special Zones presence => colorize button
        theme.set_button_state(self.special_zones_btn, None)
        if self.state_repo.has_special_zones():
            theme.set_button_state(self.special_zones_btn, "ON")
        # NOTE: self.special_zones_diagram_scale stays the DISPLAY scale. The scale the
        # dots were stored at lives in meta.special_zones_diagram_scale and is only
        # used as the rescale source (project_service.rescale_special_zone_points),
        # exactly as the sidecar's DiagramScale line was.

        for b in self.video.frames.values():
            if isinstance(b, dict):
                b["Changed"] = False
        self._set_mode_button_states()
        logger.info(
            "video %s loaded: %s frames at %s fps, resuming at frame %s",
            video_name,
            video.total_frames + 1,
            self.frame_rate,
            video.current_frame,
        )
        # Fully published: let the workers decode and paint the first frame
        # now; the swap's cover waits for that paint.
        self._suspend_frame_workers = False
        self.frame_buffer.poke()

    # === Special Zones Side Window =============================================
    def open_special_zones_app(self):
        if self.video is None:
            logger.error("cannot open Special Zones: select a video first")
        else:
            if self._special_zones_app and self._special_zones_app.top_level.winfo_exists():
                self._special_zones_app.top_level.lift()
                self._special_zones_app.top_level.focus_force()
                return
            scale = self.special_zones_diagram_scale or DEFAULT_SPECIAL_ZONES_DIAGRAM_SCALE
            initial_points = project_service.load_special_zone_points_from_repo(
                self.state_repo, scale, DEFAULT_SPECIAL_ZONES_DIAGRAM_SCALE
            )
            self.special_zones_btn.config(state=tk.DISABLED)

            def on_save(dots, diagram_scale=None, note=None):
                return self.update_data_special_zones(dots, diagram_scale, note)

            def on_close(dots, diagram_scale=None, note=None):
                if self.update_data_special_zones(dots, diagram_scale, note) is False:
                    return False
                self.special_zones_btn.config(state=tk.NORMAL)
                self._special_zones_app = None
                return True

            pose = getattr(self, "annotation_type", "Touch") == "Pose"
            if pose:
                from adapters.pose_diagram import render_pose_diagram
                session = self.pose_session
                initial_points = project_service.rescale_special_zone_points(
                    [(row[1], row[2]) for row in session.special_zones],
                    session.special_scale, scale, DEFAULT_SPECIAL_ZONES_DIAGRAM_SCALE)

            try:
                self._special_zones_app = SpecialZonesApp(
                    self,
                    on_save,
                    on_close,
                    initial_points=initial_points,
                    initial_note=self.pose_session.special_note if pose else self.state_repo.special_zones_note(),
                    diagram_scale=scale,
                    diagram_path=None if pose else template_diagram(self.state_repo.load_template().template),
                    diagram_image=render_pose_diagram() if pose else None,
                    on_first_mark=self._lock_before_annotation,
                    zone_display=self.zone_display,
                    zone_positions=self._zone_label_positions,
                    masks=self._zone_masks,
                    hover_effects=self.diagram_hover_effects,
                )
            except Exception:
                self.special_zones_btn.config(state=tk.NORMAL)
                self._special_zones_app = None
                logger.exception("failed to open Special Zones window")

    def update_data_special_zones(self, dots, diagram_scale=None, note=None):
        if getattr(self, "annotation_type", "Touch") == "Pose":
            from service_layer.pose_project_service import special_zone_rows
            scale = diagram_scale or DEFAULT_SPECIAL_ZONES_DIAGRAM_SCALE
            session = self.pose_session
            session.special_zones = special_zone_rows(dots, scale, self._zone_masks)
            session.special_note = note
            session.special_scale = scale
            try:
                outcome = self.save_data()
                if outcome is SaveOutcome.NOT_SAVED:
                    return False
                # The Special Zones are in the database; only the export is behind.
                _report_save_outcome(self, outcome)
            except Exception as exc:
                logger.exception("Pose Special Zones save failed")
                messagebox.showerror("Save failed", f"Special Zones remain open for retry.\n{exc}", parent=self)
                return False
            theme.set_button_state(self.special_zones_btn, "ON" if dots else None)
            return True
        self.data_special_zones = dots
        self.special_zones_note = note
        if diagram_scale:
            self.special_zones_diagram_scale = float(diagram_scale)
        annotation_logger.info(
            "special zones updated dots=%s note=%s", len(self.data_special_zones), bool(note)
        )
        self.save_special_zones()
        theme.set_button_state(self.special_zones_btn, "ON" if dots else None)

    def save_special_zones(self):
        """Full replace of the special zone dots and the project note in the
        state DB (the dots were the `state/<video>_clothes.txt` sidecar).

        The per-dot `zones` value stays the COMMA-JOINED string the sidecar
        held, because the export metadata's "Special Zones" list is
        a frozen contract built on that tokenization (see
        `SqliteRepository.special_zone_list`).
        """
        if self.state_repo is None:
            logger.error("cannot save special zones: no state database is open")
            return
        scale = self.special_zones_diagram_scale or DEFAULT_SPECIAL_ZONES_DIAGRAM_SCALE

        rows = []
        for dot_id, (x, y) in self.data_special_zones.items():
            if scale == 0:
                scale = DEFAULT_SPECIAL_ZONES_DIAGRAM_SCALE
            zones = self.find_image_with_white_pixel(x / scale, y / scale)
            rows.append((dot_id, x, y, ','.join(zones)))

        self.state_repo.save_special_zones(rows, scale, self.special_zones_note)
        logger.info("special zones saved: dots=%s", len(rows))

    

    # === App Lifecycle (close, position) =======================================
    def destroy(self):
        surface = self.__dict__.get("_gpu_video")
        if surface is not None:
            self._gpu_video = None
            surface.close()  # Native resources must go before Tk's child HWND.
        super().destroy()

    def close_before_project(self):
        """Close without a prompt while no video is open (main.close_for_update).

        `project_at_close` stays unset, so main.py keeps the remembered last
        project and the next start resumes it.
        """
        if getattr(self, "_closing", False) or self.video is not None:
            return
        self._closing = True
        try:
            self.frame_buffer.shutdown(wait=False, cancel_futures=True)
        except Exception:
            logger.warning("loader pool shutdown failed", exc_info=True)
        self._cancel_pending_timers()
        self.destroy()

    def on_close(self):
        if getattr(self, "_closing", False):
            return
        choice = self._ask_how_to_close()
        if choice is None:
            return
        self._closing = True
        if self.video is not None and choice == CLOSE_DISCARD:
            # The DB and the export files keep the last saved version. Position
            # and labeling time are not labels, so they are still recorded.
            logger.info("closing without saving: changes since the last save are discarded")
            self.save_last_position()
            self._finalize_video_time()
        elif self.video is not None:
            try:
                outcome = self.save_data()
            except Exception:
                logger.exception("final save failed while closing")
                outcome = SaveOutcome.NOT_SAVED
            if outcome is SaveOutcome.NOT_SAVED and getattr(self, "annotation_type", "Touch") == "Pose":
                self._closing = False
                messagebox.showerror("Save failed", "The Pose project remains open. Retry Save before closing.", parent=self)
                return
            if outcome is SaveOutcome.EXPORT_STALE and not messagebox.askyesno(
                "Export not updated",
                f"{_export_stale_message(self)}\n\nClose anyway? The export files stay out of date "
                "until the next save of this video.",
            ):
                self._closing = False
                return
            if outcome is SaveOutcome.NOT_SAVED and not messagebox.askyesno(
                "Save failed",
                "Saving failed - your latest changes are NOT on disk (see the log).\n"
                "Close anyway and lose them?",
            ):
                self._closing = False
                return
            self.save_last_position()
            self._finalize_video_time()
        extraction_cancel = getattr(self, "_frame_extraction_cancel", None)
        if extraction_cancel is not None:
            extraction_cancel.set()
        extraction_job = getattr(self, "_frame_extraction_job", None)

        def finish_close():
            if extraction_job is not None and extraction_job.thread.is_alive():
                # Keep Tk responsive until ffmpeg/OpenCV releases its files.
                self.after(FRAME_PREPARATION_POLL_MS, finish_close)
                return
            # Every DB writer and the extraction worker have now finished.
            # main.py stores this, so the next start reopens the same project.
            self.project_at_close = (
                (getattr(self, "video_name", None), getattr(self, "annotation_type", "Touch"))
                if self.video is not None else None)
            self._close_state_repo()
            try:
                self.frame_buffer.shutdown(wait=False, cancel_futures=True)
            except Exception:
                logger.warning("loader pool shutdown failed", exc_info=True)
            self._cancel_pending_timers()
            self.destroy()

        finish_close()

    def _ask_how_to_close(self):
        """CLOSE_SAVE, CLOSE_DISCARD, or None when the app should stay open.

        Exactly one prompt: the open-touch list when Touch marks are unpaired,
        the close confirmation otherwise. A discard is confirmed separately.
        """
        if self.video is None:
            unsaved = 0
        elif getattr(self, "annotation_type", "Touch") == "Pose":
            unsaved = None  # Pose labels live outside the frame bundles: count unknown
        else:
            unsaved = count_unsaved_frames(self.video.frames)
        touches = (find_open_touches(self.video.frames, LIMBS)
                   if self.video is not None and getattr(self, "annotation_type", "Touch") == "Touch" else [])
        if touches:
            action = self._resolve_open_touches(touches, closing=True)
            if action is None:
                return None
            choice = CLOSE_DISCARD if action == DISCARD_AND_CLOSE else CLOSE_SAVE
        else:
            choice = custom_confirm_close(self, unsaved_changes=unsaved)
            if not choice:
                return None
        if choice != CLOSE_DISCARD:
            return CLOSE_SAVE
        if unsaved != 0 and not self._confirm_discard(unsaved):
            logger.info("close without saving cancelled at the discard confirmation")
            return None
        return CLOSE_DISCARD

    def _confirm_discard(self, unsaved) -> bool:
        what = ("all changes made since the last save" if unsaved is None
                else f"the changes to {unsaved} frame{'s' if unsaved != 1 else ''} made since the last save")
        return confirm_discard(self, "Close without saving", f"Discard {what}?")

    def _cancel_pending_timers(self):
        """Cancel our own repeating `after()` timers before the root goes away.

        Without this the display pump, a running playback tick, a pending
        resize (and any pending arrow release) fire into a destroyed
        interpreter and Tcl prints `invalid command name "..."` on every close.
        """
        self._cancel_arrow_hold_state()
        self.play = False
        self._precise_timers.release_all()
        if self._highlighter is not None:
            self._highlighter.destroy()  # drops its fade timer, if one is running
        resize_id = getattr(self, "_resize_after_id", None)
        if resize_id is not None:
            try:
                self.after_cancel(resize_id)
            except Exception:
                logger.warning("could not cancel pending resize", exc_info=True)
            self._resize_after_id = None
        play_id = getattr(self, "_play_tick_id", None)
        if play_id is not None:
            try:
                self.after_cancel(play_id)
            except Exception:
                logger.warning("could not cancel playback tick", exc_info=True)
            self._play_tick_id = None
        pump_id = getattr(self, "_display_pump_id", None)
        if pump_id is not None:
            try:
                self.after_cancel(pump_id)
            except Exception:
                logger.warning("could not cancel display pump", exc_info=True)
            self._display_pump_id = None

    def _close_state_repo(self):
        """Release the state DB connection (called before opening another
        project and on app close). Safe to call when nothing is open."""
        panel = self.__dict__.pop("_pose_panel", None)
        if panel is not None:
            panel.detach()
        self._pose_timeline_index = None
        self.__dict__.pop("pose_session", None)
        if self.state_repo is not None:
            self.state_repo.close()
            self.state_repo = None

    def _restore_empty_annotation_controls(self):
        """Remove project-specific controls and painted content after detach."""
        self.annotation_type = "Touch"
        self.template = DEFAULT_TEMPLATE
        self.coding_setup = None
        self.zone_display = ZoneDisplaySettings()
        if self.__dict__.get("mode_controls_frame") is not None:
            self.rebuild_annotation_controls()
            self.diagram_canvas.delete("all")
            self.timeline_canvas.delete("all")
            self.timeline2_canvas.delete("all")
        badge = self.__dict__.get("mode_label")
        if badge is not None:
            badge.set(theme.STATUS_OK, "No video")

    def save_last_position(self):
        if self.video is None or self.state_repo is None:
            return
        if getattr(self, "annotation_type", "Touch") == "Pose":
            return
        self.state_repo.save_last_position(
            self.video.current_frame, self.video.total_frames
        )

    def restore_last_position(self):
        """Resume where the researcher left off (state DB `meta.last_frame`)."""
        if self.state_repo is None:
            return
        frame = self.state_repo.read_last_position(self.video.total_frames)
        if frame is None:
            return
        self.video.current_frame = frame
        self.video.current_frame_zone = int(self.video.current_frame / self.video.number_frames_in_zone)
        logger.debug("restored last position: frame=%s", self.video.current_frame)

    # === Settings ==============================================================
    def open_settings(self):
        return app_dialogs.open_settings(self)

    def _open_logs_folder(self):
        try:
            open_logs_folder()
        except Exception as exc:
            logger.exception("could not open logs folder")
            messagebox.showerror(
                "Logs unavailable",
                f"Could not open the logs folder:\n{exc}",
                parent=getattr(self, "_settings_win", self),
            )

    def apply_runtime_settings(self, cfg: dict):
        previous = self.config
        # Refresh the one AppConfig snapshot the app holds (build_ui and other
        # readers consume self.config instead of re-reading config.json).
        self.config = config.load_app_config()
        renderer_changed = self.config.video_renderer != previous.video_renderer
        display_changed = renderer_changed or any(
            getattr(self.config, name) != getattr(previous, name)
            for name in ("video_downscale", "diagram_scale", "dot_size")
        )
        if display_changed:
            self.stop_video()
            if self.video is not None:
                self._preserve_note_on_paint = (self.video, self.video.current_frame)
        # Playback controls may lag the painted frame until stop_video flushes
        # them. Capture the synchronized note, never a prior frame's text.
        note_draft = self._get_note_entry_text()
        if renderer_changed:
            self._buffer_reset()
            if self._gpu_video is not None:
                self._gpu_video.close()
                self._gpu_video = None
            self._gpu_failed = False
            self._displayed_image = None
            if self.video is not None:
                self._prepare_video_renderer()
            else:
                self._renderer_status.set("Not initialized")
        if self.config.appearance != previous.appearance:
            theme.apply_appearance(self, self.style, self.config.appearance)
            if self._gpu_video is not None:
                try:
                    self._gpu_video.set_background(theme.WIN)
                except VideoRendererError as error:
                    self._on_gpu_redraw_failure(error)
            self.color_start = theme.TOUCH_START
            self.color_during = theme.TL_DURING
            self.color_end = theme.TOUCH_END
            self._detail_timeline.invalidate()
            self._overview_timeline.invalidate()
            self.draw_timeline()
            self.draw_timeline2()

        # Appearance and label changes do not invalidate decoded video frames
        # or the diagram. Preserve unsaved notes and avoid interrupting playback.
        self.perf.enabled = bool(cfg.get("perf_enabled", False))
        self.perf.log_every_s = float(cfg.get("perf_log_every_s", 2.0))
        self.perf.top_n = int(cfg.get("perf_log_top_n", 6))

        new_downscale = float(cfg.get("video_downscale", 1.0))
        if new_downscale <= 0:
            new_downscale = 1.0
        self.video_downscale = new_downscale

        new_jump_seconds = float(cfg.get("jump_seconds", 1.0))
        if new_jump_seconds <= 0:
            new_jump_seconds = 1.0
        self.jump_seconds = new_jump_seconds
        if self.video is not None and getattr(self, "frame_rate", None):
            self.jump_frame_count = max(1, round(self.frame_rate * self.jump_seconds))
            logger.debug(
                "fast jump updated to %s frames (%ss at %s fps)",
                self.jump_frame_count,
                self.jump_seconds,
                self.frame_rate,
            )
        else:
            logger.debug("fast jump updated to %ss (no video loaded)", self.jump_seconds)
        self._refresh_jump_label()

        # Realtime arrow-hold toggle. If user disables it mid-session while a
        # hold-driven playback is active, tear that playback down cleanly.
        new_realtime = bool(cfg.get("realtime_arrow_hold", True))
        if not new_realtime:
            self._cancel_arrow_hold_state()
        self.realtime_arrow_hold = new_realtime
        logger.debug("realtime arrow hold: %s", self.realtime_arrow_hold)

        self.diagram_hover_effects = bool(cfg.get("diagram_hover_effects", True))
        if self._highlighter is not None:
            self._highlighter.set_enabled(self.diagram_hover_effects)
        if self._special_zones_app is not None:
            self._special_zones_app.set_hover_effects(self.diagram_hover_effects)
        logger.debug("diagram hover effects: %s", self.diagram_hover_effects)

        new_scale = float(cfg.get("diagram_scale", 1.0))
        new_dot = float(cfg.get("dot_size", 10))
        self.diagram_scale = new_scale
        self.dot_size = new_dot

        # Refresh parameter labels on buttons (and on the active video if present).
        try:
            target = self.video if self.video is not None else self
            load_parameter_names_into(
                target,
                {1: self.par1_btn, 2: self.par2_btn, 3: self.par3_btn},
                {1: self.limb_par1_btn, 2: self.limb_par2_btn, 3: self.limb_par3_btn},
                setup=getattr(self, "coding_setup", None) if self.video else None,
            )
            if self.video is not None:
                self.update_button_colors()
                self.update_limb_parameter_buttons()
        except Exception:
            pass

        if not display_changed:
            return

        # Same path as the window fit: the startup diagram without a video,
        # and never taller than the window leaves room for.
        try:
            self.apply_diagram_scale(min(clamp_scale(new_scale), max_diagram_scale(self)))
        except Exception:
            logger.debug("diagram redraw after settings failed", exc_info=True)

        # Flush buffer so new resolution takes effect immediately.
        self._buffer_reset()
        self._detail_timeline.reset()
        self._overview_timeline.reset()
        if getattr(self, "video", None):
            self.display_first_frame()
            self._set_note_entry_text(note_draft)

    # === Frame Stepping ========================================================
    def next_frame(self, number_of_frames, play=False, *, preserve_arrow_hold=False, navigation=None):
        if self.video is None:
            logger.debug("frame movement skipped: no video loaded")
            return
        if not play and not preserve_arrow_hold:
            self.stop_video()
        previous_frame = self.video.current_frame
        if number_of_frames > 0:
            self.video.current_frame = min(self.video.total_frames, self.video.current_frame + number_of_frames)
            self._last_step_sign = 1
        elif number_of_frames < 0:
            self.video.current_frame = max(0, self.video.current_frame + number_of_frames)
            self._last_step_sign = -1
        else:
            logger.warning("frame movement skipped: delta is zero")
            return

        panel = self.__dict__.get("_pose_panel")
        if panel is not None:
            intent = navigation or (Navigation.FORWARD_STEP if number_of_frames == 1 and not play
                                    else Navigation.JUMP)
            panel.request_navigation(previous_frame, self.video.current_frame, intent)

        # Wake the buffering thread if the destination isn't cached so it gets
        # loaded with priority before any prefetch fills.
        if self.video.current_frame not in self.frame_buffer:
            self.frame_buffer.poke()

        self.display_first_frame()
        if not play: self.draw_timeline()
        self.draw_timeline2()
