"""Alternate artwork, reference silhouette and matching Pose zone masks."""
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageFilter, ImageOps

from adapters.zone_masks import load_zone_masks, zone_label_positions
from domain.pose import POSE_ZONES
from domain.pose_geometry import POSE_SIZE, ORIGINAL_OFFSET, diagram_transform, zone_group
from domain.touch import zones_at, NO_ZONE
from domain.templates import get_template
from gui.resource_utils import asset_path


@lru_cache(maxsize=1)
def _source():
    definition = get_template("alternate")
    with Image.open(asset_path(definition.diagram)) as source:
        diagram = source.convert("RGB")
    masks = {name: Image.fromarray(mask).convert("L")
             for name, mask in load_zone_masks(asset_path(definition.masks_directory))
             if name in POSE_ZONES}
    if set(masks) != set(POSE_ZONES):
        raise ValueError("Alternate Pose masks do not match the supported zone IDs")
    return diagram, masks


def _transform(image, group, body, head, *, mask=False):
    scale, tx, ty = diagram_transform(group, body, head)
    return image.transform(POSE_SIZE, Image.Transform.AFFINE,
                           (1 / scale, 0, -tx / scale, 0, 1 / scale, -ty / scale),
                           resample=Image.Resampling.NEAREST if mask else Image.Resampling.BICUBIC,
                           fillcolor=255)


@lru_cache(maxsize=1)
def _masks():
    _, masks = _source()
    return tuple((zone, _transform(mask, zone_group(zone), 1, 1, mask=True))
                 for zone, mask in masks.items())


def pose_zone_masks(body=1.0, head=1.0):
    # Scale labels only affect the outline, never the clickable zone map.
    return _masks()


def hit_zone(x, y, body=1.0, head=1.0):
    zone = zones_at([(name, np.asarray(mask)) for name, mask in _masks()], x, y)[0]
    return None if zone == NO_ZONE else zone


@lru_cache(maxsize=1)
def _zone_positions():
    return zone_label_positions([(name, np.asarray(mask)) for name, mask in _masks()])


def zone_positions(body=1.0, head=1.0):
    return _zone_positions()


@lru_cache(maxsize=1)
def _outlines():
    diagram, masks = _source()
    layers = []
    for group in ("body", "head"):
        region = Image.new("L", diagram.size, 0)
        for zone, mask in masks.items():
            if zone_group(zone) == group:
                region = ImageChops.lighter(region, ImageOps.invert(mask))
        # Join the thin gaps between adjacent zones, then keep only exterior edges.
        region = region.filter(ImageFilter.MaxFilter(7))
        contours, _ = cv2.findContours(np.asarray(region), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        outline = np.full((diagram.height, diagram.width), 255, dtype=np.uint8)
        cv2.drawContours(outline, contours, -1, 0, 2)
        layers.append((group, Image.fromarray(outline)))
    return tuple(layers)


@lru_cache(maxsize=8)
def render_pose_diagram(body=1.0, head=1.0):
    diagram, _ = _source()
    result = Image.new("RGB", POSE_SIZE, "white")
    changed = body != 1.0 or head != 1.0
    original = ImageOps.colorize(diagram.convert("L"), "#a8a8a8", "white") if changed else diagram
    result.paste(original, ORIGINAL_OFFSET)
    if changed:
        for group, outline in _outlines():
            factor = body if group == "body" else head
            if factor == 1.0:
                continue
            scaled = _transform(outline, group, body, head)
            result = ImageChops.darker(result, ImageOps.colorize(scaled, "#42576b", "white"))
    return result
