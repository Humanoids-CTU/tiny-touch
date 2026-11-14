"""Viewport padding for outer outlines; the Alternate zone geometry stays fixed."""
POSE_SIZE = (700, 1100)
ORIGINAL_OFFSET = (125, 190)
BODY_ANCHOR = (183, 219)
BACK_HEAD_ANCHOR = (356, 219)
FRONT_HEAD_ZONES = frozenset(("Q", "R", "S", "T"))
BACK_HEAD_ZONES = frozenset(("QB", "RB", "SB", "TB"))


def zone_group(zone):
    if zone in FRONT_HEAD_ZONES:
        return "head"
    if zone in BACK_HEAD_ZONES:
        return "back_head"
    return "boxes" if zone.startswith("BOX") else "body"


def diagram_transform(group, body=1.0, head=1.0):
    factor = 1.0 if group == "boxes" else body if group == "body" else head
    ax, ay = BACK_HEAD_ANCHOR if group == "back_head" else BODY_ANCHOR
    ox, oy = ORIGINAL_OFFSET
    return factor, ox + ax * (1 - factor), oy + ay * (1 - factor)
