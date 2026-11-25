import logging
import sys
import time

import startup_splash

startup_splash.start()

import log_setup
import single_instance
from app_info import PROGRAM_VERSION
from resource_utils import get_app_dir

# Render crisply on scaled Windows displays (per-monitor DPI aware). Tk then
# reports the real DPI and theme.SCALE sizes every control to match.
WINDOWS_DPI_AWARE = True
PROCESS_PER_MONITOR_DPI_AWARE = 2
# Own taskbar identity on Windows, so the taskbar shows the TinyTouch icon
# (gui.app_icon) instead of grouping the window under python.exe.
WINDOWS_APP_USER_MODEL_ID = "CTU.TinyTouch"
# Update notice (adapters.update_check): shown when the main window appears if
# GitHub has answered by then; otherwise at the first moment no modal window or
# video load is active, up to this long after the window appeared, then dropped
# for the session so it never interrupts labeling.
UPDATE_NOTICE_LATE_WINDOW_S = 10.0
UPDATE_NOTICE_POLL_MS = 200

logger = logging.getLogger(__name__)


def enable_dpi_awareness() -> None:
    """Opt into DPI awareness before the first Tk window exists (Windows only)."""
    if not WINDOWS_DPI_AWARE or sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
    except Exception:
        # Older Windows or awareness already set by the host process.
        pass


def set_windows_app_id() -> None:
    """Give the process its own taskbar identity before any window exists (Windows only)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_USER_MODEL_ID)
    except Exception:
        pass   # Cosmetic: the window still works under the default taskbar group.


def start_update_check():
    """Start the background release check; None if it could not start."""
    try:
        from adapters import config, update_check

        return update_check.start_check(PROGRAM_VERSION, config.load_update_skipped_version())
    except Exception:
        logger.warning("update check could not start", exc_info=True)
        return None


def _app_alive(app) -> bool:
    try:
        return bool(app.winfo_exists())
    except Exception:
        return False


def _app_is_free(app) -> bool:
    """No modal window holds a grab and no video load is in progress."""
    try:
        return app.grab_current() is None and not getattr(app, "_suspend_frame_workers", False)
    except Exception:
        return False


def offer_update(app, update) -> None:
    """Show the update notice for a finished check and act on the answer."""
    from adapters import config, update_check
    from gui import app_dialogs

    latest = update.latest
    choice = app_dialogs.show_update_notice(app, update.current, latest)
    logger.info("update notice for %s: %s", latest, choice)
    if choice == app_dialogs.UPDATE_OPEN_PAGE:
        import webbrowser

        try:
            webbrowser.open(update_check.release_page_url(latest))
        except Exception:
            logger.warning("could not open the release page", exc_info=True)
    elif choice == app_dialogs.UPDATE_SKIP:
        try:
            config.save_update_skipped_version(latest)
        except OSError:
            logger.warning("could not remember the skipped version", exc_info=True)


def _poll_late_update(app, update, deadline) -> None:
    """Tk-thread poll for an answer that arrived after the window appeared."""
    if not _app_alive(app):
        return
    if update.done and update.latest is None:
        return
    if time.monotonic() > deadline:
        if update.latest is not None:
            logger.info("update notice for %s dropped: no free moment in time", update.latest)
        else:
            logger.info("update notice dropped: no answer within %.0f s of the window appearing",
                        UPDATE_NOTICE_LATE_WINDOW_S)
        return
    if update.done and _app_is_free(app):
        try:
            offer_update(app, update)
        except Exception:
            logger.warning("update notice failed", exc_info=True)
        return
    app.after(UPDATE_NOTICE_POLL_MS, _poll_late_update, app, update, deadline)


def continue_startup(app, update, last_project, revealed_at) -> None:
    """After the main window appeared: the update notice (if GitHub has
    answered), then the last project or the video library."""
    if update is not None:
        try:
            if update.done:
                if update.latest is not None:
                    offer_update(app, update)
            else:
                _poll_late_update(app, update, revealed_at + UPDATE_NOTICE_LATE_WINDOW_S)
        except Exception:
            logger.warning("update notice failed", exc_info=True)
    if _app_alive(app):
        app.open_startup_project(last_project)


def main() -> None:
    app_dir = get_app_dir()
    if not single_instance.acquire(app_dir):
        # Already running from this folder: show that window instead.
        startup_splash.close()
        single_instance.focus_running_instance()
        return
    log_setup.configure_logging(app_dir)
    log_setup.install_process_exception_hooks()
    # Ask GitHub for a newer release in the background; startup never waits.
    update = start_update_check()

    # Import after the process hooks exist so import/startup failures are also
    # captured in the session log.
    startup_splash.set_status("Loading")
    from labeling_app import LabelingApp
    from gui import window_reveal
    from adapters import config

    enable_dpi_awareness()
    set_windows_app_id()
    startup_splash.set_status("Building the interface")
    try:
        app = LabelingApp()
    except BaseException:
        startup_splash.close()   # never leave the splash over an error dialog
        raise
    # Close the splash when the main window appears (now, if already visible).
    window_reveal.on_reveal(app, startup_splash.close)
    # Then the update notice, if GitHub has answered (continue_startup), and
    # where the coder stopped: the project open at the last close on its saved
    # frame, or the video library. Queued, not called, because both run modal
    # windows and must not hold up the reveal itself.
    last_project = config.load_last_project()

    def after_reveal():
        revealed_at = time.monotonic()
        app.after_idle(lambda: continue_startup(app, update, last_project, revealed_at))

    window_reveal.on_reveal(app, after_reveal)
    # On Windows the root is still withdrawn (gui.window_reveal): it now maps
    # maximized directly, without a restore step or the maximize animation.
    # X11 uses a window attribute for the same maximized state as Windows.
    if app.tk.call("tk", "windowingsystem") == "x11":
        app.attributes("-zoomed", True)
    else:
        app.state("zoomed")
    log_setup.apply_config(app.config.log_level_console, app.config.log_keep_files)
    log_setup.install_tk_exception_hook(app)
    log_setup.log_session_header(
        version=PROGRAM_VERSION,
        config=app.config,
        app_dir=app_dir,
    )
    app.mainloop()
    # Set only by a completed close; a crash keeps the previous value.
    if hasattr(app, "project_at_close"):
        try:
            config.save_last_project(app.project_at_close)
        except OSError:
            logging.getLogger(__name__).warning(
                "could not remember the open project", exc_info=True)
    startup_splash.close()   # fallback if the window was never revealed
    log_setup.log_session_footer()


if __name__ == "__main__":
    main()
