"""A single themed library window for resuming or preparing local videos."""
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
from gui import theme
from gui.template_dialog import template_diagram
from domain.templates import TEMPLATE_LABELS


def choose_existing_video(parent, name, copy_name, *, center=None):
    """Return resume/copy, or None on cancellation, before any project writes."""
    win = tk.Toplevel(parent)
    win.title("Video already added")
    win.transient(parent)
    theme.bind_colors(win, bg="SURFACE")
    body = ttk.Frame(win, padding=24)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="Video already added", font=theme.FONT_TITLE).pack(anchor="w")
    ttk.Label(body, text=f'“{name}” already has a coding project.',
              wraplength=460).pack(anchor="w", pady=(12, 8))
    ttk.Label(body, text=f'Resume its saved work, or start “{copy_name}” with a fresh '
              'coding setup and empty annotations. The source video is shared.',
              style="Muted.TLabel", wraplength=460).pack(anchor="w")
    result = None

    def finish(value):
        nonlocal result
        result = value
        win.destroy()

    actions = ttk.Frame(body)
    actions.pack(fill="x", pady=(24, 0))
    for label, value in (("Cancel", None), ("Create new copy", "copy"),
                         ("Resume existing", "resume")):
        ttk.Button(actions, text=label, style="Tool.TButton",
                   command=lambda value=value: finish(value)).pack(side="left", padx=4)
    win.bind("<Escape>", lambda event: finish(None))
    if center:
        center(win, parent)
    win.grab_set()
    win.wait_window()
    return result

def choose_video(parent, entries, *, center=None):
    win = tk.Toplevel(parent)
    win.title("Video library")
    win.transient(parent)
    theme.bind_colors(win, bg="SURFACE")
    win.geometry("860x650")
    body = ttk.Frame(win, padding=20)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="Video library", font=theme.FONT_TITLE).pack(anchor="w")
    ttk.Label(body, text="Resume a video or prepare a new coding project.", style="Muted.TLabel").pack(anchor="w", pady=(4, 14))
    bar = ttk.Frame(body)
    bar.pack(fill="x")
    search = tk.StringVar()
    ttk.Label(bar, text="Search").pack(side="left", padx=(0, 8))
    ttk.Entry(bar, textvariable=search).pack(side="left", fill="x", expand=True)
    result = None
    def finish(value):
        nonlocal result
        result = value
        win.destroy()
    ttk.Button(bar, text="Load new video", command=lambda: finish("new"), style="Tool.TButton").pack(side="right", padx=(12, 0))
    area = ttk.Frame(body)
    area.pack(fill="both", expand=True, pady=16)
    canvas = tk.Canvas(area, highlightthickness=0)
    theme.bind_colors(canvas, bg="SURFACE")
    scroll = ttk.Scrollbar(area, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    rows = ttk.Frame(canvas)
    item = canvas.create_window(0, 0, window=rows, anchor="nw")
    rows.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(item, width=e.width))
    photos = []
    def photo(path, size):
        if not path:
            return None
        try:
            with Image.open(path) as source:
                image = source.copy()
            image.thumbnail(size)
            value = ImageTk.PhotoImage(image, master=win)
            photos.append(value)
            return value
        except (OSError, ValueError, TypeError):
            return None
    def render(*args):
        for child in rows.winfo_children():
            child.destroy()
        photos.clear()
        shown = [entry for entry in entries if search.get().casefold() in entry.title.casefold()]
        if not shown:
            ttk.Label(rows, text="No videos yet. Select Load new video to begin.", style="Muted.TLabel").pack(pady=40)
        for entry in shown:
            row = ttk.Frame(rows, padding=10, relief="solid", borderwidth=1)
            row.pack(fill="x", pady=5)
            preview = photo(entry.thumbnail, (160, 90))
            ttk.Label(row, image=preview, text="No thumbnail" if preview is None else "", width=22).pack(side="left", padx=(0, 16))
            info = ttk.Frame(row)
            info.pack(side="left", fill="x", expand=True)
            ttk.Label(info, text=entry.title, font=theme.FONT_BOLD).pack(anchor="w")
            state = "Ready" if entry.preparation_state == "ready" else "Setup / preparation required"
            ttk.Label(info, text=f"{TEMPLATE_LABELS.get(entry.template, entry.template)} / {state}" + (f" / {entry.setup_name}" if entry.setup_name else ""), style="Muted.TLabel", wraplength=330).pack(anchor="w", pady=5)
            if not entry.source:
                ttk.Label(info, text="Source unavailable — select the source again with Load new video.", wraplength=330).pack(anchor="w")
            diagram = photo(template_diagram(entry.template), (50, 80))
            ttk.Label(row, image=diagram).pack(side="left", padx=14)
            ttk.Button(row, text="Resume", style="Tool.TButton", command=lambda value=entry: finish(value), state="normal" if entry.source else "disabled").pack(side="right")
        def bind_scroll(widget):
            for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                widget.bind(event, lambda e: canvas.yview_scroll(-1 if getattr(e, "num", None) == 4 or getattr(e, "delta", 0) > 0 else 1, "units"))
            for child in widget.winfo_children():
                bind_scroll(child)
        bind_scroll(rows)
    search_trace = search.trace_add("write", render)
    render()
    ttk.Button(body, text="Cancel", command=win.destroy, style="Tool.TButton").pack(anchor="e")
    win.bind("<Escape>", lambda e: win.destroy())
    if center:
        center(win, parent)
    win.grab_set()
    try:
        win.wait_window()
    finally:
        search.trace_remove("write", search_trace)
        search = None
        photos.clear()
    return result
