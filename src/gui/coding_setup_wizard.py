"""Draft-only, reversible coding setup; no project is changed before confirmation."""
from dataclasses import replace
from pathlib import Path
from adapters import config
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageChops, ImageFilter, ImageTk

from domain.coding_setup import CodingSetup, default_coding_setup
from domain.templates import TEMPLATE_LABELS
from domain.zone_display import ZoneDisplaySettings
from adapters.zone_masks import editable_zone_names, load_zone_masks, zone_label_positions, zones_dir
from adapters.coding_configs import CodingConfigStore, validate_coding_setup
from gui import theme
from gui.resource_utils import asset_path
from gui.zone_labels import draw_zone_labels
from domain.templates import get_template
from gui.template_dialog import add_custom_template_placeholder, template_diagram

WINDOW_GEOMETRY = "780x680"
STEP_TITLES = ("1 · Diagram and saved configuration", "2 · Zone labels", "3 · Channels and parameters", "4 · Review coding setup")
# Every step fits the window without scrolling; long zone lists wrap into columns.
ZONE_ROWS_PER_COLUMN = 13
ZONE_ENTRY_WIDTH = 12
ZONE_PREVIEW_SIZE = (245, 380)
CHANNEL_PREVIEW_SIZE = (220, 280)
CHANNEL_OUTLINE_COLOR = "#2563eb"
CHANNEL_OUTLINE_WIDTH = 3
REVIEW_DIAGRAM_SIZE = (300, 360)


class CodingSetupWizard:
    def __init__(self, parent, initial=None, *, center=None, locked_template=False):
        self.parent = parent
        self.setup = replace(initial or default_coding_setup("default"), channel_zones=None)
        self.result = None
        self.step = 0
        self.locked_template = locked_template
        self.store = CodingConfigStore(Path(config.get_config_path()).parent / "config")
        self.win = tk.Toplevel(parent)
        self.win.title("Prepare video")
        self.win.transient(parent)
        theme.bind_colors(self.win, bg="SURFACE")
        self.win.geometry(WINDOW_GEOMETRY)
        self.win.resizable(False, False)
        self.body = ttk.Frame(self.win, padding=20)
        self.body.pack(fill="both", expand=True)
        self.heading = ttk.Label(self.body, font=theme.FONT_TITLE)
        self.heading.pack(anchor="w", pady=(0, 12))
        self.content = ttk.Frame(self.body)
        self.content.pack(fill="both", expand=True)
        self.error = ttk.Label(self.body, foreground=theme.STATUS_BAD, wraplength=700)
        self.error.pack(anchor="w", pady=8)
        buttons = ttk.Frame(self.body)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Cancel", command=self.win.destroy, style="Tool.TButton").pack(side="left")
        self.back = ttk.Button(buttons, text="Back", command=self.previous, style="Tool.TButton")
        self.back.pack(side="left", padx=8)
        self.next_button = ttk.Button(buttons, text="Next", command=self.next, style="Tool.TButton")
        self.next_button.pack(side="right")
        self.win.bind("<Escape>", lambda e: self.win.destroy())
        self.render()
        if center:
            center(self.win, parent)

    def run(self):
        self.win.grab_set()
        try:
            self.win.wait_window()
        finally:
            self.variables.clear()
            self.template = None
            self.config_choice = None
            self.photos = []
            self.zone_photo = None
            self.channel_photo = None
            self.review_photo = None
        return self.result

    def _entry(self, parent, row, label, value, key, *, width=38, column=0):
        ttk.Label(parent, text=label).grid(row=row, column=column * 2, sticky="w", padx=8, pady=4)
        variable = tk.StringVar(value=value)
        entry = ttk.Entry(parent, textvariable=variable, width=width)
        entry.grid(row=row, column=column * 2 + 1, sticky="ew", padx=8, pady=4)
        entry.setup_key = key
        self.variables[key] = variable
        if self.step == 1:
            entry.bind("<FocusIn>", lambda event, zone=key: self.highlight_zone(zone))
        elif self.step == 2 and key in self.setup.channel_labels:
            entry.bind("<FocusIn>", lambda event, channel=key: self.highlight_channel(channel))

    def _description(self, text):
        ttk.Label(self.content, text=text, wraplength=690).pack(anchor="w", pady=(0, 12))

    def render(self):
        for child in self.content.winfo_children():
            child.destroy()
        self.error.configure(text="")
        self.variables = {}
        self.back.configure(state="disabled" if self.step == 0 else "normal")
        self.next_button.configure(text="Prepare video" if self.step == 3 else "Next")
        self.heading.configure(text=STEP_TITLES[self.step])
        if self.step == 0:
            self._description("Choose a diagram or reuse a saved configuration. Geometry and zone IDs stay fixed.")
            self.template = tk.StringVar(value=self.setup.template)
            options = ttk.Frame(self.content)
            options.pack(fill="x")
            self.photos = []
            self.template_cards = {}
            for column in range(len(TEMPLATE_LABELS) + 1):
                options.columnconfigure(column, weight=1, uniform="templates")
            for column, (template, label) in enumerate(TEMPLATE_LABELS.items()):
                frame = tk.Frame(options, padx=8, pady=8, highlightthickness=1)
                theme.bind_colors(frame, bg="TOOLBAR_BG", highlightbackground="BORDER")
                frame.grid(row=0, column=column, sticky="nsew", padx=4)
                self.template_cards[template] = frame
                with Image.open(template_diagram(template)) as source:
                    image = source.copy()
                image.thumbnail((145, 240))
                photo = ImageTk.PhotoImage(image, master=self.win)
                self.photos.append(photo)
                preview = ttk.Label(frame, image=photo, cursor="" if self.locked_template else "hand2")
                preview.template_id = template
                preview.pack()
                if not self.locked_template:
                    preview.bind("<Button-1>", lambda event, value=template: self.select_template(value))
                    frame.bind("<Button-1>", lambda event, value=template: self.select_template(value))
                ttk.Radiobutton(frame, text=label, value=template, variable=self.template, command=self.highlight_template_selection, state="disabled" if self.locked_template else "normal").pack(pady=(12, 4))
            add_custom_template_placeholder(options, self.template, len(TEMPLATE_LABELS))
            self.highlight_template_selection()
            saved_section = ttk.LabelFrame(self.content, text="Reuse a coding configuration", padding=12)
            saved_section.pack(fill="x", pady=(20, 0))
            saved = ttk.Frame(saved_section)
            saved.pack(fill="x")
            configs = self.store.list_configs()
            self.config_paths = {path.stem: path for path in configs}
            self.config_choice = tk.StringVar()
            ttk.Combobox(saved, values=list(self.config_paths), textvariable=self.config_choice, state="readonly", width=38).pack(side="left")
            ttk.Button(saved, text="Use configuration", command=self.use_config, style="Tool.TButton").pack(side="left", padx=8)
            ttk.Button(saved_section, text="Import configuration…", command=self.import_config, style="Tool.TButton", state="normal").pack(anchor="w", pady=(10, 0))
        elif self.step == 1:
            self._description("Add labels to the fixed zone IDs. Select a field to highlight its zone. Labels appear on hover; exports retain the IDs.")
            preview = ttk.Frame(self.content)
            preview.pack(side="left", padx=(0, 12), anchor="n")
            self.zone_preview = ttk.Label(preview)
            self.zone_preview.pack(anchor="n")
            self.highlight_zone(None)
            table = ttk.Frame(self.content)
            table.pack(side="left", fill="both", expand=True, anchor="n")
            for index, zone in enumerate(editable_zone_names(self.setup.template, coding_setup=self.setup)):
                column = index // ZONE_ROWS_PER_COLUMN
                table.columnconfigure(column * 2 + 1, weight=1, uniform="zone-entries")
                self._entry(table, index % ZONE_ROWS_PER_COLUMN, zone, self.setup.zone_labels.get(zone, ""), zone, width=ZONE_ENTRY_WIDTH, column=column)
        elif self.step == 2:
            self._description("Name channels and parameters. Select a channel name to outline its assigned zone in blue.")
            overview = ttk.Frame(self.content)
            overview.pack(fill="x")
            preview = ttk.LabelFrame(overview, text=f"{TEMPLATE_LABELS[self.setup.template]} diagram", padding=10)
            preview.pack(side="left", anchor="n", padx=(0, 12))
            self.channel_preview = ttk.Label(preview)
            self.channel_preview.pack()
            channels = ttk.LabelFrame(overview, text="Channel names", padding=10)
            channels.pack(side="left", fill="x", expand=True, anchor="n")
            channels.columnconfigure(1, weight=1)
            for row, (key, label) in enumerate(self.setup.channel_labels.items()):
                self._entry(channels, row * 2, f"Channel {row + 1}", label, key, width=20)
                ttk.Label(channels, text=f"Zone: {self.channel_zone_labels(key)}",
                          style="Muted.TLabel", wraplength=280).grid(row=row * 2 + 1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 6))
            self.highlight_channel(next(iter(self.setup.channel_labels)))
            parameters = ttk.Frame(self.content)
            parameters.pack(fill="x", pady=(16, 0))
            for column in range(2):
                parameters.columnconfigure(column, weight=1, uniform="parameter-groups")
            for column, (heading, labels, prefix) in enumerate((
                ("Global parameters", self.setup.parameter_labels, "P"),
                ("Channel parameters", self.setup.limb_parameter_labels, "LP"),
            )):
                group = ttk.LabelFrame(parameters, text=heading, padding=10)
                group.grid(row=0, column=column, sticky="nsew", padx=(0, 8) if column == 0 else (8, 0))
                group.columnconfigure(1, weight=1)
                for number in range(1, 4):
                    self._entry(group, number - 1, f"Parameter {number}", labels[f"Par{number}"], f"{prefix}{number}", width=19)
        else:
            self._description("Review the labels before video preparation locks this setup.")
            overview = ttk.Frame(self.content)
            overview.pack(fill="x")
            overview.columnconfigure(1, weight=1)
            diagram = ttk.LabelFrame(overview, text=f"{TEMPLATE_LABELS[self.setup.template]} diagram with zone labels", padding=10)
            diagram.grid(row=0, column=0, rowspan=3, sticky="n", padx=(0, 6), pady=6)
            self.review_diagram(diagram).pack()
            self._review_group(overview, "Channels", tuple((f"Channel {i}", f"{label}; Zones: {self.channel_zone_labels(key)}") for i, (key, label) in enumerate(self.setup.channel_labels.items(), 1)), 0, 1)
            self._review_group(overview, "Global parameters", tuple((f"Parameter {i}", label) for i, label in enumerate(self.setup.parameter_labels.values(), 1)), 1, 1)
            self._review_group(overview, "Channel parameters", tuple((f"Parameter {i}", label) for i, label in enumerate(self.setup.limb_parameter_labels.values(), 1)), 2, 1)
            table = ttk.LabelFrame(self.content, text="Reusable configuration (optional)", padding=10)
            table.pack(fill="x", pady=(6, 0))
            table.columnconfigure(1, weight=1)
            self._entry(table, 0, "Save configuration as", "", "save_name")

    def channel_zone_labels(self, channel):
        """Resolve user-facing labels without changing the stored zone IDs."""
        return ", ".join(self.setup.zone_labels.get(zone, zone)
                         for zone in self.setup.channel_zones[channel]) or "none"

    def select_template(self, template):
        if not self.locked_template:
            self.template.set(template)
            self.highlight_template_selection()

    def highlight_template_selection(self):
        for template, card in self.template_cards.items():
            theme.bind_colors(card, highlightbackground="ACCENT" if template == self.template.get() else "BORDER")

    def _review_group(self, parent, heading, values, row, column):
        group = ttk.LabelFrame(parent, text=heading, padding=10)
        group.grid(row=row, column=column, sticky="nsew", padx=(0, 6) if column == 0 else (6, 0), pady=6)
        group.columnconfigure(1, weight=1)
        for index, (key, label) in enumerate(values):
            ttk.Label(group, text=key, style="Muted.TLabel").grid(row=index, column=0, sticky="nw", padx=(0, 12), pady=2)
            ttk.Label(group, text=label, wraplength=300).grid(row=index, column=1, sticky="nw", pady=2)

    def _preview_image(self):
        with Image.open(template_diagram(self.setup.template)) as source:
            return source.convert("RGBA")

    def highlight_zone(self, zone):
        image = self._preview_image()
        if zone:
            pixels = dict(load_zone_masks(zones_dir(self.setup.template), coding_setup=self.setup))[zone]
            mask = Image.fromarray(pixels).point(lambda value: 110 if value == 0 else 0)
            tint = Image.new("RGBA", image.size, theme.ACCENT)
            image = Image.composite(tint, image, mask)
        image.thumbnail(ZONE_PREVIEW_SIZE)
        self.zone_photo = ImageTk.PhotoImage(image, master=self.win)
        self.zone_preview.configure(image=self.zone_photo)

    def review_diagram(self, parent):
        """Diagram canvas with every zone labelled by its resolved display name."""
        image = self._preview_image()
        native_width = image.width
        image.thumbnail(REVIEW_DIAGRAM_SIZE)
        scale = image.width / native_width
        self.review_photo = ImageTk.PhotoImage(image, master=self.win)
        canvas = tk.Canvas(parent, width=image.width, height=image.height, highlightthickness=0)
        theme.bind_colors(canvas, bg="DIAGRAM_BG")
        canvas.create_image(0, 0, image=self.review_photo, anchor="nw", tags=("diagram",))
        positions = zone_label_positions(load_zone_masks(zones_dir(self.setup.template), coding_setup=self.setup))
        draw_zone_labels(canvas, ZoneDisplaySettings(self.setup.zone_labels, show_names=True), positions, scale)
        return canvas

    def highlight_channel(self, channel):
        """Outline assigned zones at preview scale, leaving their interiors intact."""
        image = self._preview_image()
        image.thumbnail(CHANNEL_PREVIEW_SIZE)
        selected = set(self.setup.channel_zones.get(channel, ()))
        combined = Image.new("L", image.size, 0)
        for zone, pixels in load_zone_masks(zones_dir(self.setup.template), coding_setup=self.setup):
            if zone in selected:
                mask = Image.fromarray((pixels == 0).astype("uint8") * 255)
                mask = mask.resize(image.size, Image.Resampling.NEAREST)
                combined = ImageChops.lighter(combined, mask)
        expanded = combined.filter(ImageFilter.MaxFilter(2 * CHANNEL_OUTLINE_WIDTH + 1))
        outline = ImageChops.subtract(expanded, combined)
        image.paste(CHANNEL_OUTLINE_COLOR, mask=outline)
        self.channel_photo = ImageTk.PhotoImage(image, master=self.win)
        self.channel_preview.configure(image=self.channel_photo)

    def capture(self):
        if self.step == 0 and self.template.get() != self.setup.template:
            previous = default_coding_setup(self.setup.template)
            selected = default_coding_setup(self.template.get())
            def keep_custom(current, old_defaults, new_defaults):
                return {key: new_defaults[key] if value == old_defaults[key] else value for key, value in current.items()}
            self.setup = replace(selected,
                channel_labels=keep_custom(self.setup.channel_labels, previous.channel_labels, selected.channel_labels),
                parameter_labels=keep_custom(self.setup.parameter_labels, previous.parameter_labels, selected.parameter_labels),
                limb_parameter_labels=keep_custom(self.setup.limb_parameter_labels, previous.limb_parameter_labels, selected.limb_parameter_labels))
        elif self.step == 1:
            zone_labels = {key: var.get() for key, var in self.variables.items()}
            self.setup = replace(self.setup, zone_labels=zone_labels)
        elif self.step == 2:
            self.setup = replace(self.setup,
                channel_labels={key: self.variables[key].get() for key in self.setup.channel_labels},
                parameter_labels={f"Par{i}": self.variables[f"P{i}"].get() for i in range(1, 4)},
                limb_parameter_labels={f"Par{i}": self.variables[f"LP{i}"].get() for i in range(1, 4)})

    def next(self):
        try:
            self.capture()
            if self.step == 3:
                name = self.variables["save_name"].get().strip()
                if name:
                    self.setup = replace(self.setup, name=name)
                    self.store.save(self.setup, name)
                validate_coding_setup(self.setup)
                self.result = self.setup
                self.win.destroy()
                return
            self.step += 1
            self.render()
        except (ValueError, OSError) as exc:
            self.error.configure(text=str(exc))

    def previous(self):
        try:
            self.capture()
            self.step = max(0, self.step - 1)
            self.render()
        except ValueError as exc:
            self.error.configure(text=str(exc))

    def use_config(self):
        try:
            path = self.config_paths.get(self.config_choice.get())
            if path:
                setup = self.store.load(path)
                if self.locked_template and setup.template != self.setup.template:
                    raise ValueError("This historical project keeps its original diagram.")
                self.setup = replace(setup, channel_zones=None)
                self.render()
        except (ValueError, OSError) as exc:
            self.error.configure(text=str(exc))

    def import_config(self):
        path = filedialog.askopenfilename(parent=self.win, title="Import coding configuration", filetypes=[("JSON configuration", "*.json")])
        if path:
            try:
                setup = self.store.load(path)
                if self.locked_template and setup.template != self.setup.template:
                    raise ValueError("This historical project keeps its original diagram.")
                self.setup = replace(self.store.load(self.store.import_config(path)), channel_zones=None)
                self.render()
            except (ValueError, OSError) as exc:
                self.error.configure(text=str(exc))


def configure_video(parent, initial=None, *, center=None, locked_template=False):
    return CodingSetupWizard(parent, initial, center=center, locked_template=locked_template).run()
