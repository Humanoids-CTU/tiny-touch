"""Side-effect-free template selection with the actual zone-mask outlines."""
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

from domain.templates import TEMPLATE_LABELS, get_template, validate_template
from gui.resource_utils import asset_path
from gui import theme


def template_diagram(template):
    return asset_path(get_template(template).diagram)


def add_custom_template_placeholder(parent, selection, column):
    """Show the planned template without making it a supported project type."""
    frame = tk.Frame(parent, padx=8, pady=8, highlightthickness=1)
    theme.bind_colors(frame, bg="TOOLBAR_BG", highlightbackground="BORDER")
    frame.grid(row=0, column=column, sticky="nsew", padx=4)
    ttk.Label(frame, text="Coming soon", style="Muted.TLabel").pack(
        expand=True, padx=8, pady=16,
    )
    ttk.Radiobutton(
        frame, text="Custom", value="custom", variable=selection, state="disabled",
    ).pack(pady=(12, 4))


def choose_template(parent, initial, *, center=None):
    validate_template(initial)
    win = tk.Toplevel(parent)
    win.withdraw()
    theme.bind_colors(win, bg="SURFACE")
    win.title("Template for new projects")
    win.transient(parent)
    content = ttk.Frame(win, padding=16)
    content.pack(fill="both", expand=True)
    explanation = (
        "Choose the diagram for a new project.\n"
        "Existing projects restore their saved template; Reliability inherits the original."
    )
    ttk.Label(content, text=explanation, justify="left", wraplength=580).pack(pady=(0, 12))
    options = ttk.Frame(content)
    options.pack()
    selection = tk.StringVar(value=initial)
    images = []
    for column, (template, label) in enumerate(TEMPLATE_LABELS.items()):
        frame = ttk.Frame(options, padding=8)
        frame.grid(row=0, column=column)
        with Image.open(template_diagram(template)) as source:
            preview = source.copy()
        preview.thumbnail((250, 310))
        photo = ImageTk.PhotoImage(preview, master=win)
        images.append(photo)
        ttk.Label(frame, image=photo).pack()
        ttk.Radiobutton(frame, text=label, value=template, variable=selection).pack(pady=8)
    add_custom_template_placeholder(options, selection, len(TEMPLATE_LABELS))
    result = None

    def confirm():
        nonlocal result
        if selection.get():
            result = selection.get()
            win.destroy()

    controls = ttk.Frame(content)
    controls.pack(pady=(12, 0))
    proceed = ttk.Button(controls, text="Continue", command=confirm, style="Tool.TButton")
    proceed.pack(side="left", padx=8)
    if center:
        center(win, parent)
    win.deiconify()
    win.grab_set()
    win.wait_window()
    return result
