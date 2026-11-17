import sys

import startup_splash

startup_splash.start()

import log_setup
import single_instance
from app_info import PROGRAM_VERSION
from gui.resource_utils import get_app_dir

# Render crisply on scaled Windows displays (per-monitor DPI aware). Tk then
# reports the real DPI and theme.SCALE sizes every control to match.
WINDOWS_DPI_AWARE = True
PROCESS_PER_MONITOR_DPI_AWARE = 2
# Own taskbar identity on Windows, so the taskbar shows the TinyTouch icon
# (gui.app_icon) instead of grouping the window under python.exe.
WINDOWS_APP_USER_MODEL_ID = "CTU.TinyTouch"


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


def main() -> None:
    app_dir = get_app_dir()
    if not single_instance.acquire(app_dir):
        # Already running from this folder: show that window instead.
        startup_splash.close()
        single_instance.focus_running_instance()
        return
    log_setup.configure_logging(app_dir)
    log_setup.install_process_exception_hooks()

    # Import after the process hooks exist so import/startup failures are also
    # captured in the session log.
    startup_splash.set_status("Loading")
    from labeling_app import LabelingApp
    from gui import window_reveal

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
    startup_splash.close()   # fallback if the window was never revealed
    log_setup.log_session_footer()


if __name__ == "__main__":
    main()
