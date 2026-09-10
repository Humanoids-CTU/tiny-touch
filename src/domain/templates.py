"""Anatomical templates and permanent project selection rules."""
from dataclasses import dataclass

DEFAULT_TEMPLATE = "default"
ALTERNATE_TEMPLATE = "alternate"
TEMPLATE_LABELS = {DEFAULT_TEMPLATE: "Default", ALTERNATE_TEMPLATE: "Alternate"}


def validate_template(template: str) -> str:
    if not isinstance(template, str) or template not in TEMPLATE_LABELS:
        raise ValueError(f"Unknown body template: {template!r}. Update TinyTouch or check the project.")
    return template


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
