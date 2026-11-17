"""TinyTouch window icon: a blue rounded square with a white "TT", drawn at runtime.

Used for every window's title bar and the taskbar, so no icon file has to ship
with the app. On Windows it is written once to a cached .ico in the temp folder
(``wm iconbitmap -default``); elsewhere it is set as photos (``wm iconphoto``).
"""

import os
import sys
import tempfile

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageTk

ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 256)   # incl. 125%/150% title-bar sizes
# Cached .ico for the Windows window icon; bump the suffix when the design changes.
ICO_CACHE_NAME = "TinyTouch-icon-v2.ico"
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
    # Transparent pixels carry the tile colour, so the anti-aliased rim blends
    # to the tile colour instead of a light or dark halo.
    img = Image.new("RGBA", (n, n), ImageColor.getrgb(ICON_FILL) + (0,))
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
    # Area-average the supersampled image: LANCZOS overshoots at the rounded
    # corners and left pixels brighter than the tile (a white fringe).
    return img.resize((size, size), Image.Resampling.BOX)


def write_ico(path):
    """Save the icon as a multi-size .ico (also used for the .exe by TinyTouch.spec)."""
    images = [render_icon(size) for size in ICON_SIZES]
    images[-1].save(path, format="ICO", sizes=[(s, s) for s in ICON_SIZES], append_images=images[:-1])


def _apply_windows_ico(root):
    """Windows: load a real .ico, so the title bar and taskbar keep its transparency.

    ``wm iconphoto`` converts the photo itself and leaves the rounded corners
    as a white square; a native .ico lets Windows pick and blend each size.
    """
    path = os.path.join(tempfile.gettempdir(), ICO_CACHE_NAME)
    if not os.path.exists(path):
        partial = f"{path}.{os.getpid()}.tmp"   # atomic: two instances may start at once
        write_ico(partial)
        os.replace(partial, path)
    root.iconbitmap(default=path)


def apply_app_icon(root):
    """Set the TT icon as the default for every window of `root`'s app."""
    if sys.platform == "win32":
        try:
            _apply_windows_ico(root)
            return
        except Exception:
            pass   # fall back to the photo icon below
    photos = [ImageTk.PhotoImage(render_icon(size), master=root) for size in ICON_SIZES]
    root.iconphoto(True, *photos)
    root._tt_icon_photos = photos   # Tk does not keep the Python objects alive
