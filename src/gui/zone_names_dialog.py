"""Project zone names, edited independently of global application settings."""
import tkinter as tk
from tkinter import ttk

from domain.zone_display import ZoneDisplaySettings
from gui import theme


def edit_zone_names(parent, zone_ids, settings, on_apply, *, center=None):
    win = tk.Toplevel(parent)
    win.withdraw()
    win.title("Zone names")
    win.transient(parent)
    theme.bind_colors(win, bg="SURFACE")
    content = ttk.Frame(win, padding=16)
    content.pack(fill="both", expand=True)
    ttk.Label(content, text="Names are saved with this project. Blank uses the zone ID.").pack(anchor="w", pady=(0, 10))

    table = ttk.Frame(content)
    table.pack(fill="both", expand=True)
    canvas = tk.Canvas(table, width=400, height=min(360, 32 * (len(zone_ids) + 1)), highlightthickness=0)
    theme.bind_colors(canvas, bg="SURFACE")
    scrollbar = ttk.Scrollbar(table, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    rows = ttk.Frame(canvas)
    item = canvas.create_window(0, 0, window=rows, anchor="nw")
    rows.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(item, width=event.width))
    ttk.Label(rows, text="Zone ID", font=theme.FONT_BOLD).grid(row=0, column=0, sticky="w", padx=6)
    ttk.Label(rows, text="Name", font=theme.FONT_BOLD).grid(row=0, column=1, sticky="w", padx=6)
    rows.columnconfigure(1, weight=1)
    entries = {}

    def scroll(event):
        direction = -1 if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0 else 1
        canvas.yview_scroll(direction, "units")
        return "break"

    for widget in (canvas, rows):
        for binding in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(binding, scroll)
    for row, zone in enumerate(zone_ids, start=1):
        label = ttk.Label(rows, text=zone)
        label.grid(row=row, column=0, sticky="w", padx=6, pady=4)
        variable = tk.StringVar(value=settings.labels.get(zone, ""))
        entry = ttk.Entry(rows, textvariable=variable, width=32)
        entry.grid(row=row, column=1, sticky="ew", padx=6, pady=4)
        # Explicit ID supports accessibility and GUI tests without relying on row order.
        entry.zone_id = zone
        entries[zone] = variable
        for widget in (entry, label):
            for binding in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                widget.bind(binding, scroll)

    error = ttk.Label(content, text="", wraplength=400)
    error.pack(anchor="w", pady=(8, 0))

    def apply():
        try:
            selected = ZoneDisplaySettings({zone: value.get() for zone, value in entries.items()})
        except ValueError as exc:
            error.configure(text=str(exc))
            return
        if on_apply(selected.labels):
            win.destroy()

    buttons = ttk.Frame(content)
    buttons.pack(fill="x", pady=(8, 0))
    ttk.Button(buttons, text="Cancel", command=win.destroy).pack(side="right", padx=4)
    ttk.Button(buttons, text="Apply", command=apply, style="Tool.TButton").pack(side="right", padx=4)
    win.bind("<Escape>", lambda event: win.destroy())
    if center:
        center(win, parent)
    win.deiconify()
    win.grab_set()
    win.wait_window()
