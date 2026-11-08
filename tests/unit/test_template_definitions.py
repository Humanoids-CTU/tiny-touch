"""Existing templates keep their assets, channel labels and display ordering."""
from pathlib import Path

import pytest
from PIL import Image

from adapters.plotting import display_limb_order, limb_image_paths
from adapters.zone_masks import load_zone_masks, zones_dir
from domain.model import LIMBS
from domain.touch import zones_at
from domain.templates import TEMPLATE_LABELS, general_footer_box, get_template
from gui.resource_utils import asset_path
from gui.template_dialog import template_diagram


@pytest.mark.parametrize("template, label, folder, suffix", [
    ("default", "Default", "zones3", ""),
    ("alternate", "Alternate", "zones3_new_template", "_new_template"),
])
def test_existing_template_assets_and_labels(template, label, folder, suffix):
    definition = get_template(template)
    assert definition.label == label
    assert [(channel.key, channel.label) for channel in definition.channels] == [
        ("RH", "Right Hand"), ("LH", "Left Hand"),
        ("RL", "Right Leg"), ("LL", "Left Leg"),
    ]
    assert display_limb_order(template=template) == ["RH", "LH", "RL", "LL"]
    assert Path(zones_dir(template)) == Path(asset_path(f"icons/{folder}"))
    assert Path(template_diagram(template)) == Path(asset_path(f"icons/{folder}/LINE.png"))
    images = limb_image_paths(template)
    assert images == [asset_path(f"icons/{limb}{suffix}.png") for limb in LIMBS]
    for path in [template_diagram(template), *images]:
        with Image.open(path) as image:
            assert image.size == definition.native_size == (450, 696)
    # The historical startup placeholder is narrower and is stretched by the
    # UI. Preserve that asset without confusing its size with annotation pixels.
    with Image.open(asset_path(definition.startup_diagram)) as image:
        assert image.size == (365, 696)


def test_general_template_has_four_channels_and_twelve_clickable_zones():
    assert TEMPLATE_LABELS["general"] == "General"
    definition = get_template("general")
    assert definition.channel_noun == "Channel"
    assert [(channel.key, channel.label) for channel in definition.channels] == [
        ("RH", "Channel 1"), ("LH", "Channel 2"),
        ("RL", "Channel 3"), ("LL", "Channel 4"),
    ]
    assert display_limb_order(template="general") == ["RH", "LH", "RL", "LL"]
    for path in [template_diagram("general"), *limb_image_paths("general")]:
        with Image.open(path) as image:
            assert image.size == definition.native_size == (450, 696)
    masks = load_zone_masks(zones_dir("general"))
    assert {name for name, _ in masks} == (
        {str(n) for n in range(1, 13)} | {"LINE", "OUTSIDE"}
    )
    for row in range(4):
        for column in range(2):
            x, y = 81 + column * 160, 24 + row * 144
            zone = str(row * 2 + column + 1)
            assert zones_at(masks, x + 64, y + 64) == [zone]
            assert zones_at(masks, x, y) == ["LINE"]
    assert zones_at(masks, 225, 100) == ["OUTSIDE"]
    # Footer boxes have stable numeric IDs and remain ordinary touch targets.
    for index in range(4):
        left, top, right, bottom = general_footer_box(index)
        assert zones_at(masks, (left + right) // 2, (top + bottom) // 2) == [str(index + 9)]
        assert zones_at(masks, left, top) == ["LINE"]
    assert zones_at(masks, 15 + 96 + 6, 640) == ["OUTSIDE"]  # the gap between two boxes


@pytest.mark.parametrize("template", [None, True, "future", []])
def test_unknown_template_is_rejected_by_asset_consumers(template):
    for resolve in (get_template, zones_dir, limb_image_paths, template_diagram):
        with pytest.raises(ValueError, match="Unknown body template"):
            resolve(template)
