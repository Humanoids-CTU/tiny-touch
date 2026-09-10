"""Frame-number prompt using the application's neutral button style."""
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk


class FrameDialog(simpledialog.Dialog):
    def __init__(self, parent, current_frame, last_frame):
        self.current_frame = current_frame
        self.last_frame = last_frame
        super().__init__(parent, "Select Frame")

    def body(self, master):
        ttk.Label(master, text=f"Frame number (0–{self.last_frame}):").pack(
            anchor="w", padx=5, pady=(0, 5),
        )
        self.entry = ttk.Entry(master)
        self.entry.pack(fill="x", padx=5)
        self.entry.insert(0, str(self.current_frame))
        self.entry.selection_range(0, tk.END)
        return self.entry

    def buttonbox(self):
        buttons = ttk.Frame(self)
        buttons.pack(padx=10, pady=10)
        for text, command in (("OK", self.ok), ("Cancel", self.cancel)):
            ttk.Button(
                buttons, text=text, command=command, width=10,
                style="Tool.TButton",
            ).pack(side="left", padx=5)
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
