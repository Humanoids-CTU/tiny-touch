"""Frame-number prompt using the application's neutral button style."""
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from gui import theme


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
            anchor="w", padx=px(10), pady=(px(10), px(6)),
        )
        self.entry = ttk.Entry(master)
        self.entry.pack(fill="x", padx=px(10))
        self.entry.insert(0, str(self.current_frame))
        self.entry.selection_range(0, tk.END)
        return self.entry

    def buttonbox(self):
        px = theme.px
        buttons = ttk.Frame(self)
        buttons.pack(padx=px(14), pady=(px(10), px(14)))
        for text, command, style in (("OK", self.ok, "Primary.TButton"), ("Cancel", self.cancel, "Tool.TButton")):
            ttk.Button(
                buttons, text=text, command=command, width=10,
                style=style,
            ).pack(side="left", padx=theme.toolbar_padx())
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
