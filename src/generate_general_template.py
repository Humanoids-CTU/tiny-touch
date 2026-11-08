"""Rebuild General's diagram and masks; run from the repository with uv run.

The squares carry no printed numbers: zone IDs (and any project zone names)
are drawn by the labeler when "Show zone names" is enabled in Settings.

The footer boxes are zones too (`9`..`12`, one per channel in
portable order), so a channel can be recorded as the target of a touch the
way a hand or leg can on the anatomical diagrams. Each box carries a small
index in its corner, leaving the centre free for the zone-name overlay, and
`general_<key>.png` fills the box of the selected channel.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))

from domain.coding_setup import PORTABLE_CHANNELS  # noqa: E402
from domain.templates import general_footer_box  # noqa: E402


ICONS_DIR = Path(__file__).resolve().parent / "resources" / "icons"
MASKS_DIR = ICONS_DIR / "zones_general"
CANVAS_SIZE = (450, 696)
SQUARE_SIZE = 128
COLUMNS = 2
ROWS = 4
LEFT_MARGIN = 81
TOP_MARGIN = 24
HORIZONTAL_GAP = 32
VERTICAL_GAP = 16
OUTLINE_WIDTH = 3
# Footer boxes: zone `9` belongs to the first box (channel RH), and so
# on in portable order. Geometry lives in domain.templates.
CHANNEL_ZONES = tuple((str(index), key) for index, key in enumerate(PORTABLE_CHANNELS.values(), 9))  # (zone, channel key)
CHANNEL_HIGHLIGHT = "#1bafd0"
FOOTER_OUTLINE_WIDTH = 2
FOOTER_INDEX_SIZE = 16
FOOTER_INDEX_INSET = (6, 4)


def with_channel_footer(diagram: Image.Image, selected: str | None) -> Image.Image:
    """Fill the selected channel's box and print each box's index in its corner."""
    result = diagram.copy()
    draw = ImageDraw.Draw(result)
    font = ImageFont.load_default(size=FOOTER_INDEX_SIZE)
    for index, (_zone, key) in enumerate(CHANNEL_ZONES):
        left, top, right, bottom = general_footer_box(index)
        draw.rectangle((left, top, right, bottom),
                       fill=CHANNEL_HIGHLIGHT if key == selected else "white",
                       outline="black", width=FOOTER_OUTLINE_WIDTH)
        draw.text((left + FOOTER_INDEX_INSET[0], top + FOOTER_INDEX_INSET[1]),
                  str(index + 9), font=font, fill="black", anchor="la")
    return result


def _zone_mask(bounds: tuple[int, int, int, int], outline_width: int) -> Image.Image:
    """Black interior of `bounds` minus its outline; the outline stays LINE."""
    left, top, right, bottom = bounds
    mask = Image.new("L", CANVAS_SIZE, 255)
    ImageDraw.Draw(mask).rectangle(
        (left + outline_width, top + outline_width,
         right - outline_width, bottom - outline_width),
        fill=0,
    )
    return mask


def main() -> None:
    MASKS_DIR.mkdir(parents=True, exist_ok=True)
    diagram = Image.new("RGB", CANVAS_SIZE, "white")
    draw = ImageDraw.Draw(diagram)
    outside = Image.new("L", CANVAS_SIZE, 0)
    outside_draw = ImageDraw.Draw(outside)

    for row in range(ROWS):
        for column in range(COLUMNS):
            zone = str(row * COLUMNS + column + 1)
            x = LEFT_MARGIN + column * (SQUARE_SIZE + HORIZONTAL_GAP)
            y = TOP_MARGIN + row * (SQUARE_SIZE + VERTICAL_GAP)
            bounds = (x, y, x + SQUARE_SIZE - 1, y + SQUARE_SIZE - 1)
            draw.rectangle(bounds, outline="black", width=OUTLINE_WIDTH)

            # Black pixels are hits. The square's interior is the zone; only
            # its border is reserved for LINE.
            _zone_mask(bounds, OUTLINE_WIDTH).save(MASKS_DIR / f"{zone}.png")
            outside_draw.rectangle(bounds, fill=255)

    # The footer boxes are zones of their own, outlined in LINE like the squares.
    for index, (zone, _key) in enumerate(CHANNEL_ZONES):
        bounds = general_footer_box(index)
        draw.rectangle(bounds, outline="black", width=FOOTER_OUTLINE_WIDTH)
        _zone_mask(bounds, FOOTER_OUTLINE_WIDTH).save(MASKS_DIR / f"{zone}.png")
        outside_draw.rectangle(bounds, fill=255)

    with_channel_footer(diagram, None).save(ICONS_DIR / "general.png")
    for _zone, key in CHANNEL_ZONES:
        with_channel_footer(diagram, key).save(ICONS_DIR / f"general_{key}.png")
    # LINE doubles as the preview, matching the existing template convention.
    diagram.convert("L").point(lambda pixel: 0 if pixel < 128 else 255).save(
        MASKS_DIR / "LINE.png"
    )
    outside.save(MASKS_DIR / "OUTSIDE.png")


if __name__ == "__main__":
    main()
