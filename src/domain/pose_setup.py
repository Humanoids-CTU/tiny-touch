"""Immutable Pose study settings, with zone aliases and no Touch channels."""
from dataclasses import dataclass, field
from collections.abc import Mapping
from domain.coding_setup import PARAMETER_KEYS, _labels, _text
from domain.pose import POSE_ZONES
from domain.zone_display import ZoneDisplaySettings

POSE_TEMPLATE = "alternate"


@dataclass(frozen=True)
class PoseCodingSetup:
    name: str = "Pose coding"
    template: str = POSE_TEMPLATE
    parameter_labels: Mapping[str, str] = field(default_factory=lambda: {
        key: f"P{i}" for i, key in enumerate(PARAMETER_KEYS, 1)})
    zone_labels: Mapping[str, str] = field(default_factory=dict)

    @property
    def zone_layout(self):
        return "numbered"

    def __post_init__(self):
        if self.template != POSE_TEMPLATE:
            raise ValueError("3d Pose currently supports only the Alternate template")
        object.__setattr__(self, "name", _text(self.name, "Coding name"))
        object.__setattr__(self, "parameter_labels", _labels(
            self.parameter_labels, PARAMETER_KEYS, "Global parameter labels"))
        labels = ZoneDisplaySettings(self.zone_labels).labels
        if set(self.zone_labels) - set(POSE_ZONES):
            raise ValueError("Unknown Alternate zone ID")
        object.__setattr__(self, "zone_labels", labels)

    def __deepcopy__(self, memo):
        return self

    def to_dict(self):
        return {"schema_version": 1, "name": self.name, "template": self.template,
                "annotation_type": "Pose", "parameter_labels": dict(self.parameter_labels),
                "zone_labels": dict(self.zone_labels)}

    @classmethod
    def from_dict(cls, value):
        if (not isinstance(value, dict) or set(value) - {"zone_labels"} != {
                "schema_version", "name", "template", "annotation_type", "parameter_labels"}
                or type(value["schema_version"]) is not int or value["schema_version"] != 1
                or value["annotation_type"] != "Pose"):
            raise ValueError("Unsupported Pose coding setup")
        return cls(value["name"], value["template"], value["parameter_labels"],
                   value.get("zone_labels", {}))
