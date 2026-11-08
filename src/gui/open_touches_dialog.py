"""Pre-analysis prompt for touches whose onset has no offset.

Shown by the Analysis button when `domain.touch.find_open_touches` finds an
`ON` with no later `OFF`. The analysis never fails on such a touch (it is
censored and reported as "open (unterminated)"), but the coder should see it
before the report does. Deliberately minimal: one line, the list, three
buttons. "Go to onset" jumps to the selected onset so the coder can place the
offset by hand; "Skip and analyze" runs the analysis with the touch left out.
"""
import tkinter as tk
from tkinter import ttk

from gui import theme

GO_TO_ONSET = "goto"
ANALYZE_ANYWAY = "analyze"

LIST_ROWS = 6
LIST_WIDTH_CHARS = 44


def describe_open_touch(touch, channel_label: str) -> str:
    """One listbox row: channel and onset frame."""
    return f"{channel_label}: onset at frame {touch.start_frame}"


class OpenTouchesDialog:
    """Modal prompt. `result` is `(action, index)` after the window closes, or
    None when cancelled. `index` is the selected list row for GO_TO_ONSET."""

    def __init__(self, parent, touches, channel_label):
        self.result = None
        self.touches = list(touches)
        win = self.win = tk.Toplevel(parent)
        win.withdraw()
        win.title("Open touches")
        win.resizable(False, False)
        win.transient(parent)
        theme.bind_colors(win, bg="SURFACE")

        content = ttk.Frame(win, padding=16)
        content.pack(fill="both", expand=True)
        count = len(self.touches)
        ttk.Label(
            content,
            text=f"{count} touch{'es' if count != 1 else ''} without an offset.",
            font=theme.FONT_TITLE,
        ).pack(anchor="w")

        list_frame = ttk.Frame(content)
        list_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.listbox = tk.Listbox(
            list_frame, height=min(LIST_ROWS, max(2, count)), exportselection=False,
            font=theme.FONT_BASE, activestyle="none", width=LIST_WIDTH_CHARS,
        )
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        for touch in self.touches:
            self.listbox.insert(tk.END, describe_open_touch(touch, channel_label(touch.limb)))
        self.listbox.selection_set(0)
        self.listbox.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        buttons = ttk.Frame(content)
        buttons.pack(pady=(14, 0))
        for text, action in (
            ("Go to onset", GO_TO_ONSET),
            ("Skip and analyze", ANALYZE_ANYWAY),
            ("Cancel", None),
        ):
            ttk.Button(
                buttons, text=text, style="Tool.TButton", takefocus=0,
                command=lambda a=action: self._finish(a),
            ).pack(side="left", padx=4)

        self.listbox.bind("<Double-Button-1>", lambda _e: self._finish(GO_TO_ONSET))
        win.bind("<Return>", lambda _e: self._finish(GO_TO_ONSET))
        win.bind("<Escape>", lambda _e: self._finish(None))
        win.protocol("WM_DELETE_WINDOW", lambda: self._finish(None))

        win.update_idletasks()
        _center_over(win, parent)
        win.deiconify()
        win.grab_set()
        self.listbox.focus_set()
        win.wait_window()

    def _finish(self, action):
        if action is None:
            self.result = None
        else:
            selected = self.listbox.curselection()
            index = int(selected[0]) if selected else 0
            self.result = (action, index)
        self.win.destroy()


def _center_over(win, parent):
    try:
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"+{px + max(0, (pw - w) // 2)}+{py + max(0, (ph - h) // 2)}")
    except tk.TclError:
        pass
