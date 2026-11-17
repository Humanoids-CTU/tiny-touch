"""TinyTouch window icon: a grey baby hand on a transparent background, drawn at runtime.

Used for every window's title bar and the taskbar, so no icon file has to ship
with the app. On Windows it is written once to a cached .ico in the temp folder
(``wm iconbitmap -default``); elsewhere it is set as photos (``wm iconphoto``).
"""

import os
import sys
import tempfile

from PIL import Image, ImageColor, ImageDraw, ImageTk

ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 256)   # incl. 125%/150% title-bar sizes
# Cached .ico for the Windows window icon; bump the suffix when the design changes.
ICO_CACHE_NAME = "TinyTouch-icon-v5.ico"
ICON_HAND = "#8e8e93"             # mid-grey hand; visible on light and dark title bars
HAND_MARGIN = 0.04                # free space around the hand, fraction of the size
HAND_MIN_MARGIN = 0.5             # px; the smallest sizes keep at least this much
SUPERSAMPLE = 8
# Win32 constants for the main window's big icon (see _set_big_icon).
SM_CXICON = 11
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x10
WM_SETICON = 0x80
ICON_BIG = 1
HAND_CURVE_STEPS = 8              # straight pieces per curve segment
# Chubby baby hand: points on its outline, joined by a smooth closed curve
# (Catmull-Rom). Thumb on the left, fingers up.
HAND_OUTLINE = (
    (31.76, 12.1), (29.87, 12.67), (28.43, 14.01), (27.72, 15.86), (27.58, 17.84), (26.28, 16.65),
    (24.61, 15.6), (22.65, 15.39), (20.8, 16.07), (19.44, 17.5), (18.85, 19.39), (18.82, 21.38),
    (18.82, 23.37), (18.82, 25.36), (18.82, 27.36), (18.81, 29.35), (17.59, 30.56), (15.82, 29.67),
    (13.88, 29.3), (11.98, 29.84), (10.51, 31.17), (9.78, 33), (9.94, 34.97), (10.95, 36.67),
    (12.53, 37.88), (14.16, 39.02), (15.79, 40.16), (17.37, 41.38), (18.77, 42.8), (20.06, 44.31),
    (21.43, 45.76), (22.91, 47.09), (24.55, 48.22), (26.35, 49.08), (28.26, 49.63), (30.23, 49.89),
    (32.22, 49.9), (34.21, 49.89), (36.19, 49.63), (38.1, 49.07), (39.89, 48.21), (41.53, 47.07),
    (42.97, 45.7), (44.17, 44.11), (45.1, 42.35), (45.75, 40.47), (46.31, 38.56), (47.36, 36.88),
    (48.83, 35.55), (50.32, 34.22), (51.82, 32.9), (53.27, 31.54), (54.18, 29.79), (54.22, 27.81),
    (53.38, 26.03), (51.84, 24.79), (49.91, 24.37), (47.99, 24.85), (46.39, 26.03), (45.14, 25.28),
    (45.13, 23.28), (45.13, 21.29), (45.13, 19.3), (44.69, 17.37), (43.46, 15.83), (41.67, 14.98),
    (39.7, 15.02), (37.94, 15.93), (36.56, 17.27), (36.22, 15.35), (35.31, 13.6), (33.71, 12.44),
)


def _hand_polygon(scale, origin=(0.0, 0.0)):
    """The hand outline as polygon points: `scale` pixels per outline unit,
    with the outline point `origin` placed at pixel (0, 0)."""
    points = []
    count = len(HAND_OUTLINE)
    for i in range(count):
        (x0, y0), (x1, y1) = HAND_OUTLINE[i - 1], HAND_OUTLINE[i]
        (x2, y2), (x3, y3) = HAND_OUTLINE[(i + 1) % count], HAND_OUTLINE[(i + 2) % count]
        for step in range(HAND_CURVE_STEPS):
            t = step / HAND_CURVE_STEPS
            # Catmull-Rom segment from point 1 to point 2.
            x = 0.5 * (2 * x1 + (x2 - x0) * t + (2 * x0 - 5 * x1 + 4 * x2 - x3) * t * t + (3 * x1 - x0 - 3 * x2 + x3) * t ** 3)
            y = 0.5 * (2 * y1 + (y2 - y0) * t + (2 * y0 - 5 * y1 + 4 * y2 - y3) * t * t + (3 * y1 - y0 - 3 * y2 + y3) * t ** 3)
            points.append(((x - origin[0]) * scale, (y - origin[1]) * scale))
    return points


def render_icon(size):
    """RGBA icon `size` px square: the hand on a transparent background."""
    n = size * SUPERSAMPLE
    xs = [x for x, _ in HAND_OUTLINE]
    ys = [y for _, y in HAND_OUTLINE]
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    margin = max(HAND_MIN_MARGIN, size * HAND_MARGIN) * SUPERSAMPLE
    scale = (n - 2 * margin) / max(width, height)
    origin = (min(xs) - (n / scale - width) / 2, min(ys) - (n / scale - height) / 2)
    # Transparent pixels carry the hand colour, so its soft edge has no halo.
    img = Image.new("RGBA", (n, n), ImageColor.getrgb(ICON_HAND) + (0,))
    ImageDraw.Draw(img).polygon(_hand_polygon(scale, origin), fill=ICON_HAND)
    # Area-average the supersampled image: LANCZOS overshoots at the edge and
    # leaves a light fringe.
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
    _set_big_icon(root, path, root)

    def on_map(event):
        # Tk builds a window's native frame when it is first shown (and when its
        # decorations change), which drops the big icon; set it again then.
        # Children of a window also deliver <Map> to these bindings; skip them.
        if event.widget.winfo_toplevel() is event.widget:
            _set_big_icon(root, path, event.widget)

    root.bind("<Map>", on_map, add="+")
    root.bind_class("Toplevel", "<Map>", on_map, add="+")   # every dialog


def _set_big_icon(root, path, window):
    """Windows: give `window` its own big icon.

    Tk uses the small title-bar icon as the big one too, so the taskbar
    enlarged it and it looked pixelated. Windows loads the big size from the
    .ico here and gets it through WM_SETICON; it then also draws the title-bar
    icon from it, so the main window and every dialog show the same picture.
    Failures leave Tk's icon in place.
    """
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.LoadImageW.restype = ctypes.c_void_p
        user32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, wintypes.UINT,
                                      ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SendMessageW.restype = ctypes.c_void_p
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p]
        icon = getattr(root, "_tt_big_icon", None)
        if icon is None:
            size = user32.GetSystemMetrics(SM_CXICON)
            icon = user32.LoadImageW(None, path, IMAGE_ICON, size, size, LR_LOADFROMFILE)
            if not icon:
                return
            root._tt_big_icon = icon   # one icon for the app's lifetime; Windows frees it at exit
        user32.SendMessageW(int(window.frame(), 16), WM_SETICON, ICON_BIG, icon)
    except Exception:
        pass


def apply_app_icon(root):
    """Set the hand icon as the default for every window of `root`'s app."""
    if sys.platform == "win32":
        try:
            _apply_windows_ico(root)
            return
        except Exception:
            pass   # fall back to the photo icon below
    photos = [ImageTk.PhotoImage(render_icon(size), master=root) for size in ICON_SIZES]
    root.iconphoto(True, *photos)
    root._tt_icon_photos = photos   # Tk does not keep the Python objects alive
