import tkinter as tk
import logging
from tkinter import ttk
from PIL import Image, ImageTk

from gui.resource_utils import asset_path
from gui import theme

DEFAULT_SPECIAL_ZONES_DIAGRAM_SCALE = 1.0
DEFAULT_SPECIAL_ZONES_DOT_RADIUS = 7
annotation_logger = logging.getLogger("annot")


class SpecialZonesApp:
    def __init__(
        self,
        master,
        on_save_callback,
        on_close_callback,
        initial_points=None,
        initial_note=None,
        diagram_scale=DEFAULT_SPECIAL_ZONES_DIAGRAM_SCALE,
        dot_radius=DEFAULT_SPECIAL_ZONES_DOT_RADIUS,
        diagram_path=None,
        on_first_mark=None,
    ):
        self.top_level = tk.Toplevel(master)
        self.top_level.title("Special Zones")
        theme.bind_colors(self.top_level, bg="SURFACE")
        self.on_save_callback = on_save_callback
        self.on_close_callback = on_close_callback
        self.diagram_scale = float(diagram_scale)
        self.dot_radius = int(dot_radius)
        self.on_first_mark = on_first_mark

        self.content = ttk.Frame(self.top_level, padding=16)
        self.content.grid(row=0, column=0, sticky="nsew")
        self.top_level.columnconfigure(0, weight=1)
        self.top_level.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)

        # Closing the window saves the dots (see WM_DELETE_WINDOW below).
        self.f = ttk.Frame(self.content)
        self.f.grid(row=0, column=0, sticky="nsew")

        self.dots = {}
        self.img = Image.open(diagram_path or asset_path("icons/diagram.png"))
        self.img = self.img.resize(
            (int(self.img.width * self.diagram_scale), int(self.img.height * self.diagram_scale)),
            Image.LANCZOS,
        )
        self.photo2 = ImageTk.PhotoImage(self.img)
        self.canvas2 = tk.Canvas(
            self.f,
            width=self.img.width,
            height=self.img.height,
            bg=theme.SURFACE,
            highlightthickness=0,
        )

        self.canvas2.pack(padx=10, pady=10)
        theme.bind_colors(self.canvas2, bg="DIAGRAM_BG")

        # Project-wide description of what the marked zones mean.
        self.note_var = tk.StringVar(value=initial_note or "")
        ttk.Label(self.f, text="Note").pack(anchor="w", padx=10)
        self.note_entry = ttk.Entry(self.f, textvariable=self.note_var)
        self.note_entry.pack(fill="x", padx=10, pady=(0, 10))

        self.canvas2.create_image(0, 0, anchor="nw", image=self.photo2)
        self.canvas2.bind("<Button-1>", self.add_dot)    # Left click to add a dot
        self.canvas2.bind("<Button-2>", self.remove_dot) # Middle click to remove a dot
        self.top_level.protocol("WM_DELETE_WINDOW", self.on_close)

        if initial_points:
            for x, y in initial_points:
                self._create_dot(x, y)

        self.top_level.update_idletasks()
        win_w = self.content.winfo_reqwidth()
        win_h = self.content.winfo_reqheight()
        self.top_level.geometry(f"{win_w}x{win_h}")

    def note(self):
        return self.note_var.get().strip()

    def on_save(self):
        if self.on_save_callback:
            self.on_save_callback(self.dots, self.diagram_scale, self.note())

    def on_close(self):
        # Callback with dots and note on close
        if self.on_close_callback:
            self.on_close_callback(self.dots, self.diagram_scale, self.note())
        self.top_level.destroy()

    def _create_dot(self, x, y):
        dot_id = self.canvas2.create_image(
            x,
            y,
            image=theme.dot_sprite(theme.SPECIAL_ZONE_DOT, self.dot_radius),
        )
        self.dots[dot_id] = (x, y)
        return dot_id

    def add_dot(self, event):
        if self.on_first_mark and self.on_first_mark() is False:
            return
        self._create_dot(event.x, event.y)
        annotation_logger.info(
            "special zones click add x=%s y=%s dots=%s", event.x, event.y, len(self.dots)
        )

    def remove_dot(self, event):
        closest_dot = self.canvas2.find_closest(event.x, event.y)[0]
        if closest_dot in self.dots:
            del self.dots[closest_dot]
            self.canvas2.delete(closest_dot)
            annotation_logger.info("special zones click delete dots=%s", len(self.dots))
