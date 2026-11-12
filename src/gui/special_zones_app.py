import tkinter as tk
import logging
from tkinter import ttk
from PIL import Image, ImageTk

from gui.resource_utils import asset_path
from gui import theme
from domain.touch import NO_ZONE
from domain.zone_display import ZoneDisplaySettings
from gui.diagram_highlight import DiagramHighlighter
from gui.zone_labels import draw_zone_labels
from gui.widgets import RoundedCard

DEFAULT_SPECIAL_ZONES_DIAGRAM_SCALE = 1.0
DEFAULT_SPECIAL_ZONES_DOT_RADIUS = 7
WINDOW_PAD = 16       # design px around the card
CARD_PAD = 12         # design px inside the note card
DIAGRAM_CARD_INSET = 4  # design px of white rim around the diagram
CARD_GAP = 12         # design px between the diagram and note cards
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
        zone_display=None,
        zone_positions=None,
        masks=None,
        hover_effects=True,
    ):
        self.top_level = tk.Toplevel(master)
        self.top_level.title("Special Zones")
        # Modal, like the app's other dialogs: it stays above the main window
        # and takes the pointer grab, so a click on the app cannot push it
        # behind (the Special Zones button is disabled while it is open, which
        # used to leave no way to bring it back).
        self.top_level.transient(master)
        theme.bind_colors(self.top_level, bg="WIN")
        self.on_save_callback = on_save_callback
        self.on_close_callback = on_close_callback
        self.diagram_scale = float(diagram_scale)
        self.dot_radius = int(dot_radius)
        self.on_first_mark = on_first_mark
        self.zone_display = zone_display or ZoneDisplaySettings()

        self.content = ttk.Frame(self.top_level, padding=theme.px(WINDOW_PAD))
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
        self.photo2 = ImageTk.PhotoImage(self.img, master=self.top_level)
        # As in the main window: the diagram fills a white card with a thin rim
        # (white in dark mode too), and the note has its own card below.
        # The canvas keeps the diagram's own pixel size: the saved dot
        # coordinates depend on it.
        self.canvas2_border = RoundedCard(self.f, fill="DIAGRAM", shadow="card",
                                          pad=theme.px(DIAGRAM_CARD_INSET))
        self.canvas2_border.pack(fill="x")
        self.canvas2 = tk.Canvas(
            self.canvas2_border.inner,
            width=self.img.width,
            height=self.img.height,
            bd=0,
            highlightthickness=0,
        )

        self.canvas2.pack()
        theme.bind_colors(self.canvas2, bg="DIAGRAM")

        # Project-wide description of what the marked zones mean.
        # fit_width=False: the note card takes the diagram card's width.
        self.note_card = RoundedCard(self.f, pad=theme.px(CARD_PAD), fit_width=False)
        self.note_card.pack(fill="x", pady=(theme.px(CARD_GAP), 0))
        card = self.note_card.inner
        self.note_var = tk.StringVar(value=initial_note or "")
        ttk.Label(card, text="Note", style="CardHead.TLabel").pack(anchor="w", pady=(0, theme.px(6)))
        self.note_entry = ttk.Entry(card, textvariable=self.note_var, style="Card.TEntry")
        self.note_entry.pack(fill="x")

        self.canvas2.create_image(0, 0, anchor="nw", image=self.photo2, tags=("diagram",))
        self.set_zone_display(self.zone_display, zone_positions or {})
        # Same hover highlight and zone tag as the annotation diagram, on the
        # same masks, so the lit zone is the zone the dot will be saved with.
        self._highlighter = None
        if masks:
            white = Image.new("RGBA", self.img.size, (255, 255, 255, 255))
            flat = Image.alpha_composite(white, self.img.convert("RGBA")).convert("RGB")
            self._highlighter = DiagramHighlighter(
                self.canvas2, masks, self.diagram_scale, flat.size, self._hover_tooltip
            )
            self._highlighter.set_base(flat)
            self._highlighter.set_enabled(hover_effects)
            self.canvas2.bind("<Motion>", lambda event: self._highlighter.on_motion(event.x, event.y))
            self.canvas2.bind("<Leave>", lambda _event: self._highlighter.on_leave())
        self.canvas2.bind("<Button-1>", self.add_dot)    # Left click to add a dot
        self.canvas2.bind("<Button-2>", self.remove_dot) # Middle click to remove a dot
        self.top_level.protocol("WM_DELETE_WINDOW", self.on_close)

        if initial_points:
            for x, y in initial_points:
                self._create_dot(x, y)

        # The card sizes itself to its content only once that content has a
        # size, so lay out, fit the card, and lay out again before measuring.
        self.top_level.update_idletasks()
        self.canvas2_border.fit()
        self.note_card.fit()
        self.top_level.update_idletasks()
        win_w = self.content.winfo_reqwidth()
        win_h = self.content.winfo_reqheight()
        self.top_level.geometry(f"{win_w}x{win_h}")
        # Centred over the main window, like every other dialog.
        x = master.winfo_rootx() + (master.winfo_width() - win_w) // 2
        y = master.winfo_rooty() + (master.winfo_height() - win_h) // 2
        self.top_level.geometry(f"{win_w}x{win_h}+{max(0, x)}+{max(0, y)}")
        try:
            self.top_level.grab_set()
        except tk.TclError:  # not viewable yet on this window manager: usable, just not modal
            logging.getLogger(__name__).warning("Special Zones window could not take the grab", exc_info=True)

    def set_zone_display(self, settings, positions):
        self.zone_display = settings
        draw_zone_labels(self.canvas2, settings, positions, self.diagram_scale)

    def set_hover_effects(self, enabled):
        if self._highlighter is not None:
            self._highlighter.set_enabled(enabled)

    def _hover_tooltip(self, zone, _x, _y):
        if zone == NO_ZONE:
            return None
        return self.zone_display.label(zone)

    def note(self):
        return self.note_var.get().strip()

    def on_save(self):
        if self.on_save_callback:
            self.on_save_callback(self.dots, self.diagram_scale, self.note())

    def on_close(self):
        # Callback with dots and note on close
        if self.on_close_callback:
            self.on_close_callback(self.dots, self.diagram_scale, self.note())
        if self._highlighter is not None:
            self._highlighter.destroy()  # stop its timer before the canvas goes
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
        if self._highlighter is not None:
            self._highlighter.flash(self._highlighter.zone_at(event.x, event.y), theme.SPECIAL_ZONE_DOT)
        annotation_logger.info(
            "special zones click add x=%s y=%s dots=%s", event.x, event.y, len(self.dots)
        )

    def remove_dot(self, event):
        # Nearest of OUR dots, not the canvas's nearest item: the hover
        # overlay and the zone tag sit under the pointer too. As before, the
        # click has to land on the dot sprite itself (radius + its 2 px ring).
        if not self.dots:
            return
        closest_dot = min(
            self.dots, key=lambda dot_id: (self.dots[dot_id][0] - event.x) ** 2 + (self.dots[dot_id][1] - event.y) ** 2
        )
        x, y = self.dots[closest_dot]
        if (x - event.x) ** 2 + (y - event.y) ** 2 > (self.dot_radius + 2) ** 2:
            return
        del self.dots[closest_dot]
        self.canvas2.delete(closest_dot)
        annotation_logger.info("special zones click delete dots=%s", len(self.dots))
