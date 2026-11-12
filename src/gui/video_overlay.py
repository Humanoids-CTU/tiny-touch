"""Translucent name badge drawn over the video frame (GPU and CPU paths).

Tk widgets cannot be see-through, so the badge is an RGBA image that the
renderer blends onto the frame itself: GpuVideoSurface draws it as a blended
texture, the CPU path composites it into the displayed PhotoImage.
"""

from PIL import Image, ImageDraw, ImageFont

from gui import theme

BADGE_FONT_FILES = ("segoeui.ttf", "SegUIVar.ttf", "DejaVuSans.ttf", "Arial.ttf")
BADGE_FONT_PX = 12          # design px (about 9 pt)
BADGE_PAD_X, BADGE_PAD_Y = 10, 5
BADGE_INSET = 12            # gap from the frame's top-right corner (design px)
BADGE_FILL = (0, 0, 0, 92)          # translucent dark pill
BADGE_TEXT = (255, 255, 255, 235)
BADGE_SUPERSAMPLE = 4


def _font(size):
    for name in BADGE_FONT_FILES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def render_badge(text):
    """RGBA pill with `text`, sized in device px (None for empty text)."""
    if not text:
        return None
    px = theme.px
    font = _font(px(BADGE_FONT_PX))
    left, top, right, bottom = font.getbbox(text)
    ascent, descent = font.getmetrics()
    w = (right - left) + 2 * px(BADGE_PAD_X)
    h = ascent + descent + 2 * px(BADGE_PAD_Y)
    s = BADGE_SUPERSAMPLE
    pill = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    ImageDraw.Draw(pill).rounded_rectangle([0, 0, w * s - 1, h * s - 1], radius=h * s // 2, fill=BADGE_FILL)
    badge = pill.resize((w, h), Image.Resampling.LANCZOS)
    ink = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(ink).text((px(BADGE_PAD_X) - left, px(BADGE_PAD_Y)), text, font=font, fill=BADGE_TEXT)
    return Image.alpha_composite(badge, ink)


class VideoBadge:
    """Text holder with the Label-like API the controller uses (`config(text=)`).

    `on_change()` runs after the text changes so the renderer can redraw.
    """

    def __init__(self, text="", on_change=None):
        self._text = str(text)
        self._on_change = on_change
        self._image_key = None
        self._image = None

    def configure(self, cnf=None, **kw):
        kw = {**(cnf or {}), **kw}
        if "text" in kw and str(kw["text"]) != self._text:
            self._text = str(kw["text"])
            if self._on_change is not None:
                self._on_change()

    config = configure

    def cget(self, key):
        if key != "text":
            raise KeyError(key)
        return self._text

    def image(self):
        """The badge image for the current text and display scale (cached)."""
        key = (self._text, theme.SCALE)
        if key != self._image_key:
            self._image_key, self._image = key, render_badge(self._text)
        return self._image
