"""Selected channels highlight saved zone assignments, independently of names."""
from dataclasses import replace

import pytest
from PIL import Image, ImageChops

from adapters.channel_diagram import CHANNEL_COLOR, render_channel_diagram
from adapters.zone_masks import load_zone_masks, zones_dir
from domain.coding_setup import default_coding_setup
from domain.templates import general_footer_box


def center(index):
    left, top, right, bottom = general_footer_box(index)
    return ((left + right) // 2, (top + bottom) // 2)


def test_general_mapping_can_highlight_multiple_zones_or_no_zones():
    setup = default_coding_setup("general")
    setup = replace(setup, channel_zones={**setup.channel_zones, "RH": ("9", "11"), "LH": (), "RL": ()})
    selected = render_channel_diagram(setup, "RH")
    neutral = render_channel_diagram(setup, "LH")
    for index in range(4):
        assert selected.getpixel(center(index)) == (CHANNEL_COLOR if index in (0, 2) else (255, 255, 255))
        assert neutral.getpixel(center(index)) == (255, 255, 255)


@pytest.mark.parametrize("template", ("default", "alternate", "general"))
def test_channel_highlight_changes_only_mapped_mask_interiors(template):
    setup = default_coding_setup(template)
    empty = replace(setup, channel_zones={key: () for key in setup.channel_zones})
    neutral = render_channel_diagram(empty, "RH")
    selected = render_channel_diagram(setup, "RH")
    difference = ImageChops.difference(neutral, selected).convert("L")
    assert difference.getbbox() is not None
    masks = dict(load_zone_masks(zones_dir(template), coding_setup=setup))
    for zone in setup.channel_zones["RH"]:
        region = Image.fromarray((masks[zone] == 0).astype("uint8") * 255)
        difference = ImageChops.multiply(difference, ImageChops.invert(region))
    assert difference.getbbox() is None


def test_renaming_zones_does_not_change_selected_channel_image():
    setup = default_coding_setup("general")
    renamed = replace(setup, zone_labels={"9": "Mother"}, channel_labels={**setup.channel_labels, "RH": "Observer"})
    assert ImageChops.difference(render_channel_diagram(setup, "RH"), render_channel_diagram(renamed, "RH")).getbbox() is None
