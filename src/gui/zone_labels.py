"""Shared canvas overlays for annotation and Special Zones."""

ZONE_LABEL_TAG = "zone-label"


def draw_zone_labels(canvas, settings, positions, scale):
    canvas.delete(ZONE_LABEL_TAG)
    if not settings.show_names:
        return
    width, height = float(canvas.cget("width")), float(canvas.cget("height"))
    for zone, (x, y) in positions.items():
        text = canvas.create_text(
            x * scale, y * scale, text=settings.label(zone),
            font=("TkDefaultFont", max(7, round(11 * scale))),
            fill="#171717", width=max(36, round(85 * scale)), justify="center",
            tags=(ZONE_LABEL_TAG,),
        )
        left, top, right, bottom = canvas.bbox(text)
        dx = max(3 - left, min(0, width - 3 - right))
        dy = max(3 - top, min(0, height - 3 - bottom))
        canvas.move(text, dx, dy)
        left, top, right, bottom = canvas.bbox(text)
        background = canvas.create_rectangle(
            left - 2, top - 2, right + 2, bottom + 2,
            fill="white", outline="#b5b5b5", tags=(ZONE_LABEL_TAG,),
        )
        canvas.tag_lower(background, text)
    # Keep labels above the diagram and below annotation dots.
    canvas.tag_raise(ZONE_LABEL_TAG, "diagram")
