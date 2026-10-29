"""
adapters/zone_masks.py
Zone-mask PNG loading (cv2 imread), pulled out of LabelingApp._load_zone_masks.
The pure hit-test rule that consumes these masks lives in domain.touch.zones_at.

`zones_dir` / `list_zone_names` resolve the domain template's asset paths:
the labeler loads masks, while analysis only needs their names.
"""

import logging
import os

import cv2

from domain.touch_stats import NO_ZONE, zone_sort_key
from domain.templates import DEFAULT_TEMPLATE, get_template
from gui.resource_utils import asset_path


logger = logging.getLogger(__name__)

_IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg')


def zones_dir(template: str = DEFAULT_TEMPLATE) -> str:
    """Absolute path of the zone-mask directory for the active template."""
    return asset_path(get_template(template).masks_directory)


def list_zone_names(template: str = DEFAULT_TEMPLATE) -> list:
    """Zone NAMES for the active template, sorted for display.

    Directory scan (adding a PNG adds a zone — see ARCHITECTURE.md), so this is I/O
    and belongs in an adapter. The `NN` sentinel is always included because a
    click that hits no mask is recorded as `NN` and must have a heatmap row.
    An unreadable directory yields just `[NN]` with a WARN rather than raising:
    the heatmap axis then still covers whatever zones the data itself contains.
    """
    directory = zones_dir(template)
    names = []
    try:
        for filename in os.listdir(directory):
            if filename.lower().endswith(_IMAGE_SUFFIXES):
                names.append(os.path.splitext(filename)[0])
    except OSError as exc:
        logger.warning("could not list zone names in %r: %r", directory, exc)
        names = []
    if NO_ZONE not in names:
        names.append(NO_ZONE)
    logger.debug(
        "zone list for %s: %d zones", template, len(names)
    )
    return sorted(names, key=zone_sort_key)


def load_zone_masks(directory):
    """Load every readable grayscale mask image in `directory`.

    Returns an ordered list of (zone_name, image) tuples — the zone name is
    the filename minus its last extension. Filenames are SORTED, which is what
    makes `zones_at`'s same-tier tie-break (first match in this list wins)
    alphabetical and reproducible instead of dependent on os.listdir order.
    Overlaps ACROSS tiers are decided by `domain.touch.zone_precedence`, not by
    this order. Unreadable / non-image files are skipped silently.
    """
    masks = []
    if not os.path.isdir(directory):
        logger.warning("Zones directory not found: %s", directory)
        return masks
    for filename in sorted(os.listdir(directory)):
        fp = os.path.join(directory, filename)
        if os.path.isfile(fp) and fp.lower().endswith(('.png', '.jpg', '.jpeg')):
            image = cv2.imread(fp, cv2.IMREAD_GRAYSCALE)
            if image is None:
                continue
            zone_name = filename.rsplit('.', 1)[0]
            masks.append((zone_name, image))
    logger.debug("Loaded touch zone masks from %s: %d masks", directory, len(masks))
    return masks
