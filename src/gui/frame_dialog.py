"""Frame-number prompt using the application's neutral button style."""
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from gui import theme

# Design px / characters.
DIALOG_PAD = 16       # margin around the content (simpledialog adds 5 px to the body)
ENTRY_WIDTH_CHARS = 24
BUTTON_GAP = 8


class FrameDialog(simpledialog.Dialog):
    def __init__(self, parent, current_frame, last_frame):
        self.current_frame = current_frame
        self.last_frame = last_frame
        super().__init__(parent, "Select Frame")

    def body(self, master):
        px = theme.px
        theme.bind_colors(self, bg="WIN")
        theme.bind_colors(master, bg="WIN")
        ttk.Label(master, text=f"Frame number (0–{self.last_frame}):").pack(
            anchor="w", padx=px(DIALOG_PAD - 5), pady=(px(DIALOG_PAD - 5), px(6)),
        )
        self.entry = ttk.Entry(master, width=ENTRY_WIDTH_CHARS)
        self.entry.pack(fill="x", padx=px(DIALOG_PAD - 5))
        self.entry.insert(0, str(self.current_frame))
        self.entry.selection_range(0, tk.END)
        return self.entry

    def buttonbox(self):
        px = theme.px
        # Right-aligned, sized to their labels: Cancel, then the default OK.
        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=px(DIALOG_PAD), pady=(px(12), px(DIALOG_PAD)))
        for text, command, style in (("OK", self.ok, "Primary.TButton"), ("Cancel", self.cancel, "Tool.TButton")):
            ttk.Button(buttons, text=text, command=command, style=style).pack(
                side="right", padx=(px(BUTTON_GAP) if text == "Cancel" else 0, 0))
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def validate(self):
        try:
            target = int(self.entry.get().strip())
        except ValueError:
            target = -1
        if not 0 <= target <= self.last_frame:
            messagebox.showwarning(
                "Invalid frame",
                f"Enter a whole number from 0 to {self.last_frame}.",
                parent=self,
            )
            return False
        self.result = target
        return True
