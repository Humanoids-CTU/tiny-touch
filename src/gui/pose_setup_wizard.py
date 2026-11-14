"""Draft-only Pose setup; confirmation returns a typed immutable setup."""
from tkinter import ttk
import tkinter as tk
from domain.pose_setup import PoseCodingSetup
from gui import theme, window_reveal
from gui.widgets import SegmentedControl
from gui.app_dialogs import (
    _dialog_frame, _footer, center_over_parent, SECTION_INDENT,
    SMALL_DIALOG_MIN_W, TOGGLE_MIN_SEG,
)


def configure_pose_video(parent, initial=None, *, center=None):
    from gui.coding_setup_wizard import CodingSetupWizard
    return CodingSetupWizard(parent, initial or PoseCodingSetup(), center=center).run()


def choose_annotation_type(parent, *, center=None):
    """Choose type before the independent Normal/Reliability selection."""
    result = None
    win = tk.Toplevel(parent)
    win.title("Annotation type")
    win.transient(parent)
    win.resizable(False, False)
    theme.bind_colors(win, bg="WIN")
    win.minsize(theme.px(SMALL_DIALOG_MIN_W), 1)
    body = _dialog_frame(win)
    ttk.Label(body, text="Choose annotation type:", style="Title.TLabel").pack(
        anchor="w", padx=theme.px(SECTION_INDENT), pady=(0, theme.px(10)))
    selection = tk.StringVar(master=win, value=getattr(parent, "annotation_type", "Touch"))
    SegmentedControl(body, (("Touch", "Touch"), ("Pose", "3d Pose")),
                     variable=selection, gapless=True, min_seg=TOGGLE_MIN_SEG,
                     bg="WIN").pack(anchor="w")

    def finish():
        nonlocal result
        result = selection.get()
        win.destroy()

    foot = _footer(body, top_gap=18)
    ttk.Button(foot, text="Continue", command=finish, style="Primary.TButton",
               takefocus=0).pack(side="right")
    win.bind("<Escape>", lambda event: win.destroy())
    window_reveal.place_on_reveal(win, lambda: (center or center_over_parent)(win, parent))
    window_reveal.modal_grab(win)
    win.wait_window()
    return result
