import sys

import log_setup
from app_info import PROGRAM_VERSION
from gui.resource_utils import get_app_dir

# Render crisply on scaled Windows displays (per-monitor DPI aware). Tk then
# reports the real DPI and theme.SCALE sizes every control to match.
WINDOWS_DPI_AWARE = True
PROCESS_PER_MONITOR_DPI_AWARE = 2


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


def main() -> None:
    app_dir = get_app_dir()
    log_setup.configure_logging(app_dir)
    log_setup.install_process_exception_hooks()

    # Import after the process hooks exist so import/startup failures are also
    # captured in the session log.
    from labeling_app import LabelingApp

    enable_dpi_awareness()
    app = LabelingApp()
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
    log_setup.log_session_footer()


if __name__ == "__main__":
    main()
