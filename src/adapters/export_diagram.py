"""Portable, labeled diagram reference rendered without a Tk window."""
import hashlib
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from adapters.zone_masks import load_zone_masks, zones_dir, zone_label_positions
from domain.coding_setup import PORTABLE_CHANNELS, PARAMETER_KEYS
from domain.templates import get_template
from gui.resource_utils import asset_path

SCALE = 3
MARGIN = 32
PANEL_WIDTH = 460
TEXT_SIZE = 22
LINE_HEIGHT = 30
BADGE_WIDTH = 210
BADGE_PADDING = 8
BADGE_GAP = 8
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


def _panel_lines(setup, font):
    """The saved study settings, in the same stable order as the CSV."""
    lines = []
    groups = (
        ("Channels", [(portable, setup.channel_labels[key], setup.channel_zones[key])
                      for portable, key in PORTABLE_CHANNELS.items()]),
        ("Parameters", [(f"Parameter_{i}", setup.parameter_labels[key], ())
                        for i, key in enumerate(PARAMETER_KEYS, 1)]),
        ("Channel parameters", [(f"Parameter_{i}", setup.limb_parameter_labels[key], ())
                                for i, key in enumerate(PARAMETER_KEYS, 1)]),
    )
    for heading, rows in groups:
        if lines:
            lines.append(("", False))
        lines.append((heading, True))
        for identifier, label, zones in rows:
            lines.extend((line, False) for line in _wrap_text(f"{identifier}: {label}", font, PANEL_WIDTH))
            if zones:
                lines.extend((line, False) for line in _wrap_text("  Zones: " + ", ".join(zones), font, PANEL_WIDTH))
    return lines


def _overlaps(first, second):
    return (first[0] < second[2] + BADGE_GAP and second[0] < first[2] + BADGE_GAP
            and first[1] < second[3] + BADGE_GAP and second[1] < first[3] + BADGE_GAP)


def _nearby_points(x, y, maximum_radius):
    yield x, y
    for radius in range(12, maximum_radius, 12):
        count = max(8, math.ceil(2 * math.pi * radius / 24))
        for i in range(count):
            angle = i * 2 * math.pi / count
            yield x + radius * math.cos(angle), y + radius * math.sin(angle)


def _label_layout(draw, setup, positions, bounds):
    """Keep whole saved names and IDs visible without overlapping badges.

    Crowded anatomical regions can be smaller than their names. Place those
    badges in the nearest free space and connect them to the original region.
    """
    font = _font(TEXT_SIZE)
    labels = []
    for zone, (x, y) in positions.items():
        name = setup.zone_labels.get(zone, zone)
        text = zone if name == zone else "\n".join(_wrap_text(name, font, BADGE_WIDTH) + [f"({zone})"])
        left, top, right, bottom = draw.multiline_textbbox((0, 0), text, font=font, spacing=4, align="center")
        labels.append({"text": text, "anchor": (MARGIN + x * SCALE, MARGIN + y * SCALE),
                       "size": (right - left + 2 * BADGE_PADDING, bottom - top + 2 * BADGE_PADDING),
                       "offset": (left, top)})
    # Large labels have fewer viable positions; reserve their space first.
    labels.sort(key=lambda label: -(label["size"][0] * label["size"][1]))
    occupied = []
    for label in labels:
        x, y = label["anchor"]
        width, height = label["size"]
        for cx, cy in _nearby_points(x, y, max(bounds[2] - bounds[0], bounds[3] - bounds[1])):
            left = min(max(bounds[0], round(cx - width / 2)), bounds[2] - width)
            top = min(max(bounds[1], round(cy - height / 2)), bounds[3] - height)
            rect = (left, top, left + width, top + height)
            if not any(_overlaps(rect, previous) for previous in occupied):
                label["rect"] = rect
                occupied.append(rect)
                break
        else:
            raise ValueError("Zone names cannot fit in the reference diagram")
    return labels


def write_export_diagram(path, setup):
    """Burn saved zone names and IDs into the diagram, with saved settings beside it.

    The reference has margins and is scaled; annotation coordinates continue
    to refer to native diagram pixels, not to this presentation image.
    """
    definition = get_template(setup.template)
    with Image.open(asset_path(definition.diagram)) as source:
        diagram = source.convert("RGB")
    if diagram.size != definition.native_size:
        raise ValueError("Diagram dimensions do not match the template")
    masks = load_zone_masks(zones_dir(setup.template), coding_setup=setup)
    if not masks or any(mask.shape[::-1] != diagram.size for _, mask in masks):
        raise ValueError("Diagram zone masks are missing or have inconsistent dimensions")
    positions = zone_label_positions(masks)
    font = _font(TEXT_SIZE)
    lines = _panel_lines(setup, font)
    width, height = diagram.size
    panel_x = MARGIN + width * SCALE + MARGIN
    image = Image.new("RGB", (panel_x + PANEL_WIDTH + MARGIN,
                     max(height * SCALE, len(lines) * LINE_HEIGHT) + 2 * MARGIN), "white")
    image.paste(diagram.resize((width * SCALE, height * SCALE), Image.Resampling.NEAREST), (MARGIN, MARGIN))
    draw = ImageDraw.Draw(image)
    labels = _label_layout(draw, setup, positions, (MARGIN, MARGIN, MARGIN + width * SCALE, MARGIN + height * SCALE))
    for label in labels:
        left, top, right, bottom = label["rect"]
        x, y = label["anchor"]
        if not (left <= x <= right and top <= y <= bottom):
            draw.line(((x, y), (min(max(x, left), right), min(max(y, top), bottom))), fill="#505660", width=2)
            draw.ellipse((x-3, y-3, x+3, y+3), fill="#505660")
    for label in labels:
        left, top, right, bottom = label["rect"]
        draw.rounded_rectangle((left, top, right, bottom), radius=5, fill="white", outline="#90969e", width=1)
        draw.multiline_text((left + BADGE_PADDING - label["offset"][0], top + BADGE_PADDING - label["offset"][1]),
                            label["text"], fill="#20242b", font=font, spacing=4, align="center")
    for index, (line, heading) in enumerate(lines):
        draw.text((panel_x, MARGIN + index * LINE_HEIGHT), line, fill="#20242b" if heading else "#505660", font=font)
    image.save(path, format="PNG")
    return {"image": Path(path).name, "image_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
