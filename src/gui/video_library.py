"""A single themed library window for resuming or preparing local videos."""
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageDraw, ImageTk
from gui import content_swap, theme, window_reveal
from gui.widgets import RoundedCard
from gui.template_dialog import template_diagram
from domain.templates import TEMPLATE_LABELS

# Design px (scaled with theme.px at build time).
LIBRARY_SIZE = (860, 650)
DUPLICATE_WRAP = 460
ROW_TEXT_WRAP = 330
THUMBNAIL_SIZE = (160, 90)
ROW_DIAGRAM_SIZE = (50, 80)
ROW_CARD_PAD = 12
THUMBNAIL_RADIUS = 8    # rounded like the video in the main window
DIAGRAM_RADIUS = 6
DIAGRAM_RIM = 3         # white margin inside the diagram's rounded corners


def _rounded(image, radius, rim=0):
    """`image` with rounded corners on the card colour (plus a white `rim`)."""
    image = image.convert("RGB")
    if rim:
        framed = Image.new("RGB", (image.width + 2 * rim, image.height + 2 * rim), "#ffffff")
        framed.paste(image, (rim, rim))
        image = framed
    s = theme.SUPERSAMPLE
    mask = Image.new("L", (image.width * s, image.height * s), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, image.width * s - 1, image.height * s - 1], radius=radius * s, fill=255)
    mask = mask.resize(image.size, Image.Resampling.LANCZOS)
    return Image.composite(image, Image.new("RGB", image.size, theme.color("CARD")), mask)


def choose_existing_video(parent, name, copy_name, *, center=None):
    """Return resume/copy, or None on cancellation, before any project writes."""
    px = theme.px
    win = tk.Toplevel(parent)   # hidden until settled and centred
    win.title("Video already added")
    win.transient(parent)
    theme.bind_colors(win, bg="WIN")
    body = ttk.Frame(win, padding=px(24))
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="Video already added", style="Title.TLabel").pack(anchor="w")
    ttk.Label(body, text=f'“{name}” already has a coding project.',
              wraplength=px(DUPLICATE_WRAP)).pack(anchor="w", pady=(px(12), px(8)))
    ttk.Label(body, text=f'Resume its saved work, or start “{copy_name}” with a fresh '
              'coding setup and empty annotations. The source video is shared.',
              style="Muted.TLabel", wraplength=px(DUPLICATE_WRAP)).pack(anchor="w")
    result = None

    def finish(value):
        nonlocal result
        result = value
        win.destroy()

    actions = ttk.Frame(body)
    actions.pack(fill="x", pady=(px(24), 0))
    for label, value, style in (("Cancel", None, "Tool.TButton"),
                                ("Create new copy", "copy", "Tool.TButton"),
                                ("Resume existing", "resume", "Primary.TButton")):
        ttk.Button(actions, text=label, style=style,
                   command=lambda value=value: finish(value)).pack(side="left", padx=(0, theme.toolbar_padx()))
    win.bind("<Escape>", lambda event: finish(None))
    if center:
        window_reveal.place_on_reveal(win, lambda: center(win, parent))
    window_reveal.modal_grab(win)
    win.wait_window()
    return result

def choose_video(parent, entries, *, center=None):
    px = theme.px
    win = tk.Toplevel(parent)   # hidden until settled and centred
    win.title("Video library")
    win.transient(parent)
    theme.bind_colors(win, bg="WIN")
    win.geometry(f"{px(LIBRARY_SIZE[0])}x{px(LIBRARY_SIZE[1])}")
    body = ttk.Frame(win, padding=px(20))
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="Video library", style="Title.TLabel").pack(anchor="w")
    ttk.Label(body, text="Resume a video or prepare a new coding project.", style="Muted.TLabel").pack(anchor="w", pady=(px(4), px(14)))
    bar = ttk.Frame(body)
    bar.pack(fill="x")
    search = tk.StringVar()
    ttk.Label(bar, text="Search").pack(side="left", padx=(0, px(8)))
    ttk.Entry(bar, textvariable=search).pack(side="left", fill="x", expand=True)
    result = None
    def finish(value):
        nonlocal result
        result = value
        win.destroy()
    ttk.Button(bar, text="Load new video", command=lambda: finish("new"), style="Primary.TButton").pack(side="right", padx=(px(12), 0))
    area = ttk.Frame(body)
    area.pack(fill="both", expand=True, pady=px(16))
    canvas = tk.Canvas(area, highlightthickness=0, bd=0)
    theme.bind_colors(canvas, bg="WIN")
    scroll = ttk.Scrollbar(area, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y", padx=(px(4), 0))
    canvas.pack(side="left", fill="both", expand=True)
    rows = ttk.Frame(canvas)
    item = canvas.create_window(0, 0, window=rows, anchor="nw")
    rows.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(item, width=e.width))
    photos = []
    def photo(path, size, radius=0, rim=0):
        if not path:
            return None
        try:
            with Image.open(path) as source:
                image = source.copy()
            image.thumbnail((size[0] - 2 * rim, size[1] - 2 * rim))
            if radius:
                image = _rounded(image, radius, rim)
            value = ImageTk.PhotoImage(image, master=win)
            photos.append(value)
            return value
        except (OSError, ValueError, TypeError):
            return None
    def build_row(entry):
        card = RoundedCard(rows, pad=px(ROW_CARD_PAD))
        row = card.inner
        preview = photo(entry.thumbnail, (px(THUMBNAIL_SIZE[0]), px(THUMBNAIL_SIZE[1])),
                        radius=px(THUMBNAIL_RADIUS))
        ttk.Label(row, image=preview, text="No thumbnail" if preview is None else "", width=22,
                  style="Card.TLabel" if preview is not None else "CardMuted.TLabel").pack(side="left", padx=(0, px(16)))
        info = ttk.Frame(row, style="Card.TFrame")
        info.pack(side="left", fill="x", expand=True)
        ttk.Label(info, text=entry.title, style="Card.TLabel", font=theme.FONT_MEDIUM).pack(anchor="w")
        state = {"ready": "Ready", "preparing": "Resume frame generation",
                 "draft": "Setup saved / resume preparation"}.get(
                     entry.preparation_state, "Setup / preparation required")
        ttk.Label(info, text=f"{entry.annotation_type} / {TEMPLATE_LABELS.get(entry.template, entry.template)} / {state}" + (f" / {entry.setup_name}" if entry.setup_name else ""), style="CardMuted.TLabel", wraplength=px(ROW_TEXT_WRAP)).pack(anchor="w", pady=px(5))
        if not entry.source:
            ttk.Label(info, text="Source unavailable — select the source again with Load new video.", style="Card.TLabel", wraplength=px(ROW_TEXT_WRAP)).pack(anchor="w")
        diagram = photo(template_diagram(entry.template) if entry.annotation_type == "Touch" else None, (px(ROW_DIAGRAM_SIZE[0]), px(ROW_DIAGRAM_SIZE[1])),
                        radius=px(DIAGRAM_RADIUS), rim=px(DIAGRAM_RIM))
        ttk.Label(row, image=diagram, style="Card.TLabel").pack(side="left", padx=px(14))
        ttk.Button(row, text="Resume", style="Card.Tool.TButton", command=lambda value=entry: finish(value), state="normal" if entry.source else "disabled").pack(side="right")
        return card
    # Every row is built once; a search only shows or hides rows.
    cards = [(entry, build_row(entry)) for entry in entries]
    empty = ttk.Label(rows, text="No videos yet. Select Load new video to begin.", style="Muted.TLabel")
    def bind_scroll(widget):
        for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(event, lambda e: canvas.yview_scroll(-1 if getattr(e, "num", None) == 4 or getattr(e, "delta", 0) > 0 else 1, "units"))
        for child in widget.winfo_children():
            bind_scroll(child)
    bind_scroll(rows)
    def filter_rows():
        text = search.get().casefold()
        shown = [card for entry, card in cards if text in entry.title.casefold()]
        for _, card in cards:
            card.pack_forget()
        empty.pack_forget()
        for card in shown:
            card.pack(fill="x")
        if not shown:
            empty.pack(pady=px(40))
        canvas.yview_moveto(0)
    def render(*args):
        content_swap.swap_content(win, filter_rows)
    search_trace = search.trace_add("write", render)
    render()
    ttk.Button(body, text="Cancel", command=win.destroy, style="Tool.TButton").pack(anchor="e")
    win.bind("<Escape>", lambda e: win.destroy())
    if center:
        window_reveal.place_on_reveal(win, lambda: center(win, parent))
    window_reveal.modal_grab(win)
    try:
        win.wait_window()
    finally:
        search.trace_remove("write", search_trace)
        search = None
        photos.clear()
    return result
