"""Existing templates keep their assets, channel labels and display ordering."""
from pathlib import Path

import pytest
from PIL import Image

from adapters.plotting import display_limb_order, limb_image_paths
from adapters.zone_masks import zones_dir
from domain.model import LIMBS
from domain.templates import TEMPLATE_LABELS, get_template
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


def test_general_is_not_selectable_yet():
    assert dict(TEMPLATE_LABELS) == {"default": "Default", "alternate": "Alternate"}
    with pytest.raises(ValueError, match="Unknown body template"):
        get_template("general")


@pytest.mark.parametrize("template", [None, True, "future", []])
def test_unknown_template_is_rejected_by_asset_consumers(template):
    for resolve in (get_template, zones_dir, limb_image_paths, template_diagram):
        with pytest.raises(ValueError, match="Unknown body template"):
            resolve(template)
