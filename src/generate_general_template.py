"""Rebuild General's diagram and masks; run from the repository with uv run."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ICONS_DIR = Path(__file__).resolve().parent / "resources" / "icons"
MASKS_DIR = ICONS_DIR / "zones_general"
CANVAS_SIZE = (450, 696)
SQUARE_SIZE = 144
COLUMNS = 2
ROWS = 4
LEFT_MARGIN = 65
TOP_MARGIN = 30
HORIZONTAL_GAP = 32
VERTICAL_GAP = 20
OUTLINE_WIDTH = 3
LABEL_SIZE = 28
CHANNEL_KEYS = ("RH", "LH", "RL", "LL")
CHANNEL_HIGHLIGHT = "#1bafd0"
FOOTER_Y = 674


def with_channel_footer(diagram: Image.Image, selected: str | None) -> Image.Image:
    result = diagram.copy()
    draw = ImageDraw.Draw(result)
    font = ImageFont.load_default(size=12)
    for index, key in enumerate(CHANNEL_KEYS):
        x = 17 + index * 105
        draw.rectangle((x, FOOTER_Y, x + 99, FOOTER_Y + 19),
                       fill=CHANNEL_HIGHLIGHT if key == selected else "white", outline="black")
        draw.text((x + 50, FOOTER_Y + 9), f"Channel {index + 1}", font=font,
                  fill="black", anchor="mm")
    return result


def main() -> None:
    MASKS_DIR.mkdir(parents=True, exist_ok=True)
    diagram = Image.new("RGB", CANVAS_SIZE, "white")
    draw = ImageDraw.Draw(diagram)
    font = ImageFont.load_default(size=LABEL_SIZE)
    outside = Image.new("L", CANVAS_SIZE, 0)
    outside_draw = ImageDraw.Draw(outside)

    for row in range(ROWS):
        for column in range(COLUMNS):
            zone = str(row * COLUMNS + column + 1)
            x = LEFT_MARGIN + column * (SQUARE_SIZE + HORIZONTAL_GAP)
            y = TOP_MARGIN + row * (SQUARE_SIZE + VERTICAL_GAP)
            bounds = (x, y, x + SQUARE_SIZE - 1, y + SQUARE_SIZE - 1)
            draw.rectangle(bounds, outline="black", width=OUTLINE_WIDTH)
            draw.text(
                (x + (SQUARE_SIZE - 1) / 2, y + (SQUARE_SIZE - 1) / 2),
                zone, fill="black", font=font, anchor="mm",
            )

            # Black pixels are hits. Include the printed number in its zone;
            # only the square's border is reserved for LINE.
            mask = Image.new("L", CANVAS_SIZE, 255)
            ImageDraw.Draw(mask).rectangle(
                (x + OUTLINE_WIDTH, y + OUTLINE_WIDTH,
                 x + SQUARE_SIZE - 1 - OUTLINE_WIDTH,
                 y + SQUARE_SIZE - 1 - OUTLINE_WIDTH),
                fill=0,
            )
            mask.save(MASKS_DIR / f"{zone}.png")
            outside_draw.rectangle(bounds, fill=255)

    with_channel_footer(diagram, None).save(ICONS_DIR / "general.png")
    for key in CHANNEL_KEYS:
        with_channel_footer(diagram, key).save(ICONS_DIR / f"general_{key}.png")
    # LINE doubles as the preview, matching the existing template convention.
    # Zone interiors take precedence over the number glyphs during hit testing.
    diagram.convert("L").point(lambda pixel: 0 if pixel < 128 else 255).save(
        MASKS_DIR / "LINE.png"
    )
    outside.save(MASKS_DIR / "OUTSIDE.png")


if __name__ == "__main__":
    main()
