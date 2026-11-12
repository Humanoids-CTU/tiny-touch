"""Side-effect-free template selection with the actual zone-mask outlines."""
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

from domain.templates import TEMPLATE_LABELS, get_template, validate_template
from gui.resource_utils import asset_path
from gui import theme
from gui.widgets import RoundedCard

# Design px (scaled with theme.px at build time).
TEMPLATE_PREVIEW_SIZE = (250, 310)
EXPLANATION_WRAP = 580
TILE_PAD = 10
TILE_GAP = 4
TILE_BORDER = "LINE"           # unselected template tile outline (palette role)
TILE_SELECTED_BORDER = "ACCENT"


def template_diagram(template):
    return asset_path(get_template(template).diagram)


def template_tile(parent):
    """Bordered white tile on the window background (no shadow: the border shows selection)."""
    return RoundedCard(parent, shadow=False, border=TILE_BORDER, pad=theme.px(TILE_PAD))


def set_tile_selected(tile, selected):
    """Accent outline for the selected tile; repaints only on a change."""
    tile.set_border(TILE_SELECTED_BORDER if selected else TILE_BORDER)


def add_custom_template_placeholder(parent, selection, column):
    """Show the planned template without making it a supported project type."""
    tile = RoundedCard(parent, shadow=False, border=TILE_BORDER, pad=theme.px(TILE_PAD), fill_height=True)
    tile.grid(row=0, column=column, sticky="nsew", padx=theme.px(TILE_GAP))
    ttk.Label(tile.inner, text="Coming soon", style="CardMuted.TLabel").pack(
        expand=True, padx=theme.px(8), pady=theme.px(16),
    )
    ttk.Radiobutton(
        tile.inner, text="Custom", value="custom", variable=selection, state="disabled",
        style="Card.TRadiobutton",
    ).pack(pady=(theme.px(12), theme.px(4)))
    return tile


def choose_template(parent, initial, *, center=None):
    px = theme.px
    validate_template(initial)
    win = tk.Toplevel(parent)
    win.withdraw()
    theme.bind_colors(win, bg="WIN")
    win.title("Template for new projects")
    win.transient(parent)
    content = ttk.Frame(win, padding=px(16))
    content.pack(fill="both", expand=True)
    explanation = (
        "Choose the diagram for a new project.\n"
        "Existing projects restore their saved template; Reliability inherits the original."
    )
    ttk.Label(content, text=explanation, justify="left", wraplength=px(EXPLANATION_WRAP)).pack(pady=(0, px(12)))
    options = ttk.Frame(content)
    options.pack()
    selection = tk.StringVar(value=initial)
    images = []
    tiles = {}
    for column, (template, label) in enumerate(TEMPLATE_LABELS.items()):
        tile = template_tile(options)
        tile.grid(row=0, column=column, sticky="nsew", padx=px(TILE_GAP))
        tiles[template] = tile
        with Image.open(template_diagram(template)) as source:
            preview = source.copy()
        preview.thumbnail((px(TEMPLATE_PREVIEW_SIZE[0]), px(TEMPLATE_PREVIEW_SIZE[1])))
        photo = ImageTk.PhotoImage(preview, master=win)
        images.append(photo)
        ttk.Label(tile.inner, image=photo, style="Card.TLabel").pack()
        ttk.Radiobutton(tile.inner, text=label, value=template, variable=selection,
                        style="Card.TRadiobutton").pack(pady=px(8))
    add_custom_template_placeholder(options, selection, len(TEMPLATE_LABELS))

    def show_selection(*_args):
        for template, tile in tiles.items():
            set_tile_selected(tile, template == selection.get())

    selection_trace = selection.trace_add("write", show_selection)
    show_selection()
    result = None

    def confirm():
        nonlocal result
        if selection.get():
            result = selection.get()
            win.destroy()

    controls = ttk.Frame(content)
    controls.pack(pady=(px(12), 0))
    proceed = ttk.Button(controls, text="Continue", command=confirm, style="Primary.TButton")
    proceed.pack(side="left", padx=px(8))
    if center:
        center(win, parent)
    win.deiconify()
    win.grab_set()
    try:
        win.wait_window()
    finally:
        selection.trace_remove("write", selection_trace)
    return result
