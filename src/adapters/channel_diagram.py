"""Render selected-channel feedback from the saved zone mapping, without Tk."""
from PIL import Image, ImageChops

from adapters.zone_masks import load_zone_masks, zones_dir
from domain.templates import get_template
from gui.resource_utils import asset_path

CHANNEL_COLOR = (27, 175, 208)


def render_channel_diagram(setup, channel, masks=None):
    """Return the neutral diagram with precisely the mapped zone interiors blue."""
    with Image.open(asset_path(get_template(setup.template).diagram)) as source:
        image = source.convert("RGB")
    if masks is None:
        masks = load_zone_masks(zones_dir(setup.template), coding_setup=setup)
    selected = set(setup.channel_zones.get(channel, ()))
    combined = Image.new("L", image.size, 0)
    for zone, pixels in masks:
        if zone in selected:
            mask = Image.fromarray((pixels == 0).astype("uint8") * 255)
            combined = ImageChops.lighter(combined, mask)
    tint = ImageChops.multiply(image, Image.new("RGB", image.size, CHANNEL_COLOR))
    return Image.composite(tint, image, combined)
