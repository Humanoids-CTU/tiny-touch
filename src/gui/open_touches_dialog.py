"""Analysis and app-close prompt for unpaired onsets and offsets.

Shown by the Analysis button when `domain.touch.find_open_touches` finds an
`ON` with no later `OFF`, or an `OFF` with no open `ON` before it. The
analysis never fails on either (an open touch is censored and reported as
"open (unterminated)", a stray offset is ignored), but the coder should see
them before the report does. Deliberately minimal: one line, the list, three
buttons. "Go to frame" jumps to the selected mark so the coder can fix it by
hand; "Skip and analyze" runs the analysis with the marks left as they are.
"""
import tkinter as tk
from tkinter import ttk

from domain.touch import STRAY_OFFSET
from gui import theme, window_reveal
from gui.widgets import RoundedCard

GO_TO_ONSET = "goto"   # jump to the selected mark (onset or stray offset)
ANALYZE_ANYWAY = "analyze"
SAVE_AND_CLOSE = "close"

LIST_ROWS = 6
LIST_WIDTH_CHARS = 44
TEXT_WRAP = 380        # design px
LIST_FIELD_PAD = 6    # design px between the field outline and the list


def describe_open_touch(touch, channel_label: str) -> str:
    """One listbox row: channel, mark kind and frame."""
    if touch.kind == STRAY_OFFSET:
        return f"{channel_label}: offset at frame {touch.start_frame} without an onset"
    return f"{channel_label}: onset at frame {touch.start_frame}"


def describe_title(touches) -> str:
    """Headline: names the one kind present, or both when mixed."""
    offsets = sum(1 for t in touches if t.kind == STRAY_OFFSET)
    onsets = len(touches) - offsets

    open_text = f"{onsets} touch{'es' if onsets != 1 else ''} without an offset"
    stray_text = f"{offsets} offset{'s' if offsets != 1 else ''} without an onset"
    if not offsets:
        return f"{open_text}."
    if not onsets:
        return f"{stray_text}."
    return f"{open_text}, {stray_text}."


class OpenTouchesDialog:
    """Modal prompt. `result` is `(action, index)` after the window closes, or
    None when cancelled. `index` is the selected list row for GO_TO_ONSET."""

    def __init__(self, parent, touches, channel_label, *, closing=False):
        self.result = None
        self.touches = list(touches)
        win = self.win = tk.Toplevel(parent)   # hidden until settled and centred
        win.title("Unpaired onsets and offsets")
        win.resizable(False, False)
        win.transient(parent)
        theme.bind_colors(win, bg="WIN")
        px = theme.px

        content = ttk.Frame(win, padding=px(16))
        content.pack(fill="both", expand=True)
        count = len(self.touches)
        ttk.Label(
            content,
            text=describe_title(self.touches),
            style="Title.TLabel",
            wraplength=px(TEXT_WRAP),
        ).pack(anchor="w")
        if closing:
            ttk.Label(
                content,
                text="You can save now and fix them when you continue labeling.",
                wraplength=px(TEXT_WRAP),
            ).pack(anchor="w", pady=(px(6), 0))
        elif any(t.kind == STRAY_OFFSET for t in self.touches):
            ttk.Label(
                content,
                text="Offsets without an onset are ignored by the analysis.",
                wraplength=px(TEXT_WRAP),
            ).pack(anchor="w", pady=(px(6), 0))

        list_frame = ttk.Frame(content)
        list_frame.pack(fill="both", expand=True, pady=(px(10), 0))
        # The list sits in a rounded field; the scrollbar stays outside it on
        # the window background (scrollbar images are painted opaque on WIN).
        field = RoundedCard(list_frame, fill="BTN", border="BTN_LINE", radius=theme.RADIUS,
                            outer="WIN", pad=px(LIST_FIELD_PAD))
        self.listbox = tk.Listbox(
            field.inner, height=min(LIST_ROWS, max(2, count)), exportselection=False,
            font=theme.FONT_BASE, activestyle="none", width=LIST_WIDTH_CHARS,
            bd=0, highlightthickness=0, relief="flat",
        )
        theme.bind_colors(self.listbox, bg="BTN", fg="TEXT", selectbackground="ACCENT",
                          selectforeground="SELECTION_FG")
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        for touch in self.touches:
            self.listbox.insert(tk.END, describe_open_touch(touch, channel_label(touch.limb)))
        self.listbox.selection_set(0)
        self.listbox.pack(fill="both", expand=True)
        scroll.pack(side="right", fill="y", padx=(px(4), 0))
        field.pack(side="left", fill="both", expand=True)

        buttons = ttk.Frame(content)
        buttons.pack(pady=(px(14), 0))
        for text, action in (
            ("Go to frame", GO_TO_ONSET),
            ("Save and close", SAVE_AND_CLOSE) if closing else ("Skip and analyze", ANALYZE_ANYWAY),
            ("Cancel", None),
        ):
            # Enter runs "Go to frame", so it is the primary action.
            ttk.Button(
                buttons, text=text, style="Primary.TButton" if action == GO_TO_ONSET else "Tool.TButton",
                takefocus=0, command=lambda a=action: self._finish(a),
            ).pack(side="left", padx=theme.toolbar_padx())

        self.listbox.bind("<Double-Button-1>", lambda _e: self._finish(GO_TO_ONSET))
        win.bind("<Return>", lambda _e: self._finish(GO_TO_ONSET))
        win.bind("<Escape>", lambda _e: self._finish(None))
        win.protocol("WM_DELETE_WINDOW", lambda: self._finish(None))

        window_reveal.place_on_reveal(win, lambda: _center_over(win, parent))
        window_reveal.modal_grab(win)
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
