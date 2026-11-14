"""Project annotation kinds; old untyped projects are Touch projects."""
TOUCH = "Touch"
POSE = "Pose"


def annotation_type(value=TOUCH):
    if value not in (TOUCH, POSE):
        raise ValueError(f"Unsupported annotation type: {value!r}")
    return value
