"""Project zone names, edited independently of global application settings."""
import tkinter as tk
from tkinter import ttk

from domain.zone_display import ZoneDisplaySettings
from gui import theme
from gui.widgets import RoundedCard

# Design px (scaled with theme.px at build time).
LIST_WIDTH = 400
LIST_MAX_HEIGHT = 360
ROW_HEIGHT = 34
CARD_PAD = 12
TEXT_WRAP = 400


def edit_zone_names(parent, zone_ids, settings, on_apply, *, center=None):
    win = tk.Toplevel(parent)
    win.withdraw()
    win.title("Zone names")
    win.transient(parent)
    px = theme.px
    theme.bind_colors(win, bg="WIN")
    content = ttk.Frame(win, padding=px(16))
    content.pack(fill="both", expand=True)
    ttk.Label(content, text="Names are saved with this project. Blank uses the zone ID.").pack(anchor="w", pady=(0, px(10)))

    table = ttk.Frame(content)
    table.pack(fill="x")
    # The list sits on a white card; the scrollbar stays outside it on the
    # window background (scrollbar images are painted opaque on WIN).
    card = RoundedCard(table, pad=px(CARD_PAD))
    canvas = tk.Canvas(card.inner, width=px(LIST_WIDTH), height=min(px(LIST_MAX_HEIGHT), px(ROW_HEIGHT) * (len(zone_ids) + 1)),
                       highlightthickness=0, bd=0)
    theme.bind_colors(canvas, bg="CARD")
    scrollbar = ttk.Scrollbar(table, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y", padx=(px(4), 0))
    card.pack(side="left", fill="x", expand=True)
    canvas.pack(fill="both", expand=True)
    rows = ttk.Frame(canvas, style="Card.TFrame")
    item = canvas.create_window(0, 0, window=rows, anchor="nw")
    rows.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(item, width=event.width))
    ttk.Label(rows, text="Zone ID", style="CardHead.TLabel").grid(row=0, column=0, sticky="w", padx=(0, px(12)), pady=(0, px(4)))
    ttk.Label(rows, text="Name", style="CardHead.TLabel").grid(row=0, column=1, sticky="w", pady=(0, px(4)))
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
        label = ttk.Label(rows, text=zone, style="Card.TLabel")
        label.grid(row=row, column=0, sticky="w", padx=(0, px(12)), pady=px(2))
        variable = tk.StringVar(value=settings.labels.get(zone, ""))
        entry = ttk.Entry(rows, textvariable=variable, width=32, style="Card.TEntry")
        entry.grid(row=row, column=1, sticky="ew", pady=px(2))
        # Explicit ID supports accessibility and GUI tests without relying on row order.
        entry.zone_id = zone
        entries[zone] = variable
        for widget in (entry, label):
            for binding in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                widget.bind(binding, scroll)

    error = theme.bind_colors(ttk.Label(content, text="", wraplength=px(TEXT_WRAP)), foreground="STATUS_BAD")
    error.pack(anchor="w", pady=(px(8), 0))

    def apply():
        try:
            selected = ZoneDisplaySettings({zone: value.get() for zone, value in entries.items()})
        except ValueError as exc:
            error.configure(text=str(exc))
            return
        if on_apply(selected.labels):
            win.destroy()

    buttons = ttk.Frame(content)
    buttons.pack(fill="x", pady=(px(8), 0))
    ttk.Button(buttons, text="Cancel", command=win.destroy, style="Tool.TButton").pack(side="right")
    ttk.Button(buttons, text="Apply", command=apply, style="Primary.TButton").pack(side="right", padx=theme.toolbar_padx())
    win.bind("<Escape>", lambda event: win.destroy())
    if center:
        center(win, parent)
    win.deiconify()
    win.grab_set()
    win.wait_window()
