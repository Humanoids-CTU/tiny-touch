"""Template definitions and permanent project selection rules (no asset I/O)."""
from dataclasses import dataclass
from types import MappingProxyType

DEFAULT_TEMPLATE = "default"
ALTERNATE_TEMPLATE = "alternate"
GENERAL_TEMPLATE = "general"


@dataclass(frozen=True)
class ChannelDefinition:
    key: str
    label: str
    image: str


@dataclass(frozen=True)
class TemplateDefinition:
    label: str
    diagram: str
    masks_directory: str
    channels: tuple[ChannelDefinition, ...]  # selector and report display order
    native_size: tuple[int, int] = (450, 696)
    startup_diagram: str = "icons/diagram0.png"
    channel_noun: str = "Limb"

    def channel(self, key: str) -> ChannelDefinition:
        for channel in self.channels:
            if channel.key == key:
                return channel
        raise KeyError(key)

    def channel_label(self, key: str) -> str:
        """Preserve unknown report keys rather than inventing a display name."""
        return next((channel.label for channel in self.channels if channel.key == key), key)


def _anatomical_template(label: str, masks_directory: str, image_suffix: str) -> TemplateDefinition:
    # The subject's right side appears on the viewer's left. This order is
    # for display only; stored keys and the CSV column order stay unchanged.
    labels = (
        ("RH", "Right Hand"),
        ("LH", "Left Hand"),
        ("RL", "Right Leg"),
        ("LL", "Left Leg"),
    )
    return TemplateDefinition(
        label=label,
        diagram=f"{masks_directory}/LINE.png",
        masks_directory=masks_directory,
        channels=tuple(
            ChannelDefinition(key, name, f"icons/{key}{image_suffix}.png")
            for key, name in labels
        ),
    )


TEMPLATES = MappingProxyType({
    DEFAULT_TEMPLATE: _anatomical_template("Default", "icons/zones3", ""),
    ALTERNATE_TEMPLATE: _anatomical_template("Alternate", "icons/zones3_new_template", "_new_template"),
    GENERAL_TEMPLATE: TemplateDefinition(
        label="General",
        diagram="icons/zones_general/LINE.png",
        masks_directory="icons/zones_general",
        channels=tuple(
            ChannelDefinition(key, f"Channel {index}", "icons/general.png")
            for index, key in enumerate(("RH", "LH", "RL", "LL"), start=1)
        ),
        startup_diagram="icons/general.png",
        channel_noun="Channel",
    ),
})
TEMPLATE_LABELS = MappingProxyType({key: definition.label for key, definition in TEMPLATES.items()})


def validate_template(template: str) -> str:
    if not isinstance(template, str) or template not in TEMPLATES:
        raise ValueError(f"Unknown body template: {template!r}. Update TinyTouch or check the project.")
    return template


def get_template(template: str) -> TemplateDefinition:
    return TEMPLATES[validate_template(template)]


@dataclass(frozen=True)
class TemplateState:
    template: str | None = None
    locked: bool = False

    def __post_init__(self):
        if self.template is not None:
            validate_template(self.template)

    def choose(self, template: str) -> "TemplateState":
        validate_template(template)
        if self.locked and self.template != template:
            raise ValueError("This project's body template is locked. Create a new project to use another template.")
        return TemplateState(template, self.locked)

    def lock(self) -> "TemplateState":
        return TemplateState(self.template, True)


def bundle_has_annotation(bundle: dict) -> bool:
    if bundle.get("Note") or any((bundle.get("Params") or {}).values()):
        return True
    return any(
        rec.get("X") or rec.get("Y") or rec.get("Zones") or rec.get("Onset")
        or any((rec.get("LimbParams") or {}).values())
        for limb in ("LH", "RH", "LL", "RL")
        if isinstance(rec := bundle.get(limb), dict)
    )
