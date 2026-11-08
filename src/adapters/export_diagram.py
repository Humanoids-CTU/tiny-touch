"""Portable, labeled diagram reference rendered without a Tk window."""
import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from adapters.zone_masks import list_zone_names, load_zone_masks, zones_dir, zone_label_positions
from domain.templates import get_template
from gui.resource_utils import asset_path

SCALE = 2
MARGIN = 32
HEADER = 100
LEGEND_WIDTH = 560
TEXT_SIZE = 22
LINE_HEIGHT = 30
FONT_CANDIDATES = ("DejaVuSans.ttf", "segoeui.ttf", "Arial.ttf")


def _font(size):
    for name in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _wrap_text(text, font, width):
    """Wrap even long unbroken labels to measured pixel width."""
    lines = []
    while text:
        end = 1
        while end < len(text) and font.getlength(text[:end + 1]) <= width:
            end += 1
        if end < len(text) and " " in text[:end]:
            end = text.rfind(" ", 0, end) or end
        lines.append(text[:end])
        text = text[end:].lstrip()
    return lines


def write_export_diagram(path, setup):
    """Burn CSV IDs and the complete zone-name legend into one reference PNG.

    The reference has margins and is scaled; annotation coordinates continue
    to refer to native diagram pixels, not to this presentation image.
    """
    definition = get_template(setup.template)
    with Image.open(asset_path(definition.diagram)) as source:
        diagram = source.convert("RGB")
    if diagram.size != definition.native_size:
        raise ValueError("Diagram dimensions do not match the template")
    masks = load_zone_masks(zones_dir(setup.template))
    names = list_zone_names(setup.template)
    if not masks or any(mask.shape[::-1] != diagram.size for _, mask in masks):
        raise ValueError("Diagram zone masks are missing or have inconsistent dimensions")
    positions = zone_label_positions(masks)
    font = _font(TEXT_SIZE)
    badge_font = _font(20)
    lines = []
    for zone in names:
        label = setup.zone_labels.get(zone, zone)
        if zone == "LINE":
            label = "Boundary / ambiguous zone"
        elif zone == "NN":
            label = "No zone matched"
        text = zone if label == zone else f"{zone}  -  {label}"
        lines.extend(_wrap_text(text, font, LEGEND_WIDTH))
    width, height = diagram.size
    legend_x = MARGIN + width * SCALE + MARGIN
    image = Image.new("RGB", (legend_x + LEGEND_WIDTH + MARGIN,
                     max(HEADER + height * SCALE, HEADER + (len(lines) + 3) * LINE_HEIGHT) + MARGIN), "white")
    image.paste(diagram.resize((width * SCALE, height * SCALE), Image.Resampling.NEAREST), (MARGIN, HEADER))
    draw = ImageDraw.Draw(image)
    draw.text((MARGIN, 18), f"{definition.label} | Zone reference", fill="#20242b", font=_font(30))
    draw.text((MARGIN, 58), "IDs match the CSV. Coordinates use native diagram pixels.", fill="#505660", font=font)
    for zone, (x, y) in positions.items():
        bounds = draw.textbbox((0, 0), zone, font=badge_font, anchor="mm")
        half_width = (bounds[2] - bounds[0]) / 2 + 6
        half_height = (bounds[3] - bounds[1]) / 2 + 6
        point = (max(MARGIN + half_width, min(MARGIN + width * SCALE - half_width, MARGIN + x * SCALE)),
                 max(HEADER + half_height, min(HEADER + height * SCALE - half_height, HEADER + y * SCALE)))
        left, top, right, bottom = draw.textbbox(point, zone, font=badge_font, anchor="mm")
        draw.rounded_rectangle((left-5, top-4, right+5, bottom+4), radius=4,
                               fill="white", outline="#505660", width=1)
        draw.text(point, zone, fill="#20242b", font=badge_font, anchor="mm")
    draw.text((legend_x, HEADER), "ZONE ID / SAVED NAME", fill="#20242b", font=font)
    for index, line in enumerate(lines):
        draw.text((legend_x, HEADER + (index + 2) * LINE_HEIGHT), line, fill="#303640", font=font)
    image.save(path, format="PNG")
    return {"image": Path(path).name, "image_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
