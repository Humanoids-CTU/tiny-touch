"""TinyTouch window icon: a blue rounded square with a white "TT", drawn at runtime.

Used for every window's title bar and the taskbar (``wm iconphoto -default``),
so no icon file has to ship with the app.
"""

from PIL import Image, ImageDraw, ImageFont, ImageTk

ICON_SIZES = (16, 24, 32, 48, 64, 256)
ICON_FILL = "#e5e5ea"             # light grey tile, close to the window colour
ICON_TEXT = "#8e8e93"             # mid-grey letters
ICON_RADIUS = 0.24                # corner radius, fraction of the size
ICON_FONT_FILES = ("segoeuib.ttf", "seguisb.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf")
ICON_TEXT_HEIGHT = 0.46           # cap height of "TT", fraction of the size
ICON_LETTER_SPACING = 0.05        # gap between the two T crossbars (fraction of the size)
SUPERSAMPLE = 4


def _font(px):
    for name in ICON_FONT_FILES:
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default(px)


def render_icon(size):
    """RGBA icon `size` px square."""
    s = SUPERSAMPLE
    n = size * s
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, n - 1, n - 1], radius=round(n * ICON_RADIUS), fill=ICON_FILL)
    # Size the font so the capital T is ICON_TEXT_HEIGHT of the icon.
    font = _font(n)
    t_top, t_bottom = font.getbbox("T")[1], font.getbbox("T")[3]
    font = _font(max(1, round(n * n * ICON_TEXT_HEIGHT / max(1, t_bottom - t_top))))
    left, top, right, bottom = font.getbbox("T")
    t_w, t_h = right - left, bottom - top
    gap = round(n * ICON_LETTER_SPACING)
    total = 2 * t_w + gap
    x = (n - total) / 2 - left
    y = (n - t_h) / 2 - top
    draw.text((x, y), "T", font=font, fill=ICON_TEXT)
    draw.text((x + t_w + gap, y), "T", font=font, fill=ICON_TEXT)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def apply_app_icon(root):
    """Set the TT icon as the default for every window of `root`'s app."""
    photos = [ImageTk.PhotoImage(render_icon(size), master=root) for size in ICON_SIZES]
    root.iconphoto(True, *photos)
    root._tt_icon_photos = photos   # Tk does not keep the Python objects alive
