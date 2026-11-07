"""Immutable study labels, independent of machine preferences and geometry."""
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from domain.templates import get_template
from domain.zone_display import ZoneDisplaySettings

SCHEMA_VERSION = 1
CHANNEL_KEYS = ("RH", "LH", "RL", "LL")
PARAMETER_KEYS = ("Par1", "Par2", "Par3")
PORTABLE_CHANNELS = dict(zip(("Channel1", "Channel2", "Channel3", "Channel4"), CHANNEL_KEYS))


def _text(value, description):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 80:
        raise ValueError(f"{description} must be non-empty text of at most 80 characters")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{description} must be a single line")
    return value.strip()


def _labels(value, keys, description):
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise ValueError(f"{description} must contain exactly {', '.join(keys)}")
    return MappingProxyType({key: _text(value[key], description) for key in keys})


@dataclass(frozen=True)
class CodingSetup:
    name: str
    template: str = "default"
    zone_labels: Mapping[str, str] = field(default_factory=dict)
    channel_labels: Mapping[str, str] = field(default_factory=dict)
    parameter_labels: Mapping[str, str] = field(default_factory=dict)
    limb_parameter_labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self):
        get_template(self.template)
        object.__setattr__(self, "name", _text(self.name, "Coding name"))
        object.__setattr__(self, "zone_labels", ZoneDisplaySettings(self.zone_labels).labels)
        object.__setattr__(self, "channel_labels", _labels(self.channel_labels, CHANNEL_KEYS, "Channel labels"))
        ZoneDisplaySettings(self.channel_labels)  # Reports share the 40-character label limit.
        object.__setattr__(self, "parameter_labels", _labels(self.parameter_labels, PARAMETER_KEYS, "Parameter labels"))
        object.__setattr__(self, "limb_parameter_labels", _labels(self.limb_parameter_labels, PARAMETER_KEYS, "Channel parameter labels"))

    def __deepcopy__(self, memo):
        return self  # Every contained mapping and value is immutable.

    def to_dict(self):
        return {
            "schema_version": SCHEMA_VERSION, "name": self.name, "template": self.template,
            "zone_labels": dict(self.zone_labels),
            "channel_labels": {portable: self.channel_labels[key] for portable, key in PORTABLE_CHANNELS.items()},
            "parameter_labels": dict(self.parameter_labels),
            "channel_parameter_labels": dict(self.limb_parameter_labels),
        }

    @classmethod
    def from_dict(cls, value):
        required = {"schema_version", "name", "template", "zone_labels", "channel_labels", "parameter_labels"}
        parameter_fields = {"channel_parameter_labels", "limb_parameter_labels"}
        if not isinstance(value, dict) or not required <= set(value) or set(value) - required - parameter_fields or not set(value) & parameter_fields:
            raise ValueError("Coding configuration has missing or unknown fields")
        if parameter_fields <= set(value) and value["channel_parameter_labels"] != value["limb_parameter_labels"]:
            raise ValueError("Conflicting channel parameter labels in coding configuration")
        if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION:
            raise ValueError("Unsupported coding configuration version")
        channels = _labels(value["channel_labels"], tuple(PORTABLE_CHANNELS), "Portable channel labels")
        return cls(name=value["name"], template=value["template"], zone_labels=value["zone_labels"],
                   channel_labels={key: channels[portable] for portable, key in PORTABLE_CHANNELS.items()},
                   parameter_labels=value["parameter_labels"],
                   limb_parameter_labels=value["channel_parameter_labels"] if "channel_parameter_labels" in value else value["limb_parameter_labels"])


def default_coding_setup(template="default", parameter_labels=None, limb_parameter_labels=None):
    definition = get_template(template)
    parameter_prefix = "CP" if template == "general" else "LP"
    return CodingSetup(
        name=f"{definition.label} coding", template=template,
        channel_labels={key: definition.channel_label(key) for key in CHANNEL_KEYS},
        parameter_labels=parameter_labels if parameter_labels is not None else {key: f"P{i}" for i, key in enumerate(PARAMETER_KEYS, 1)},
        limb_parameter_labels=limb_parameter_labels if limb_parameter_labels is not None else {key: f"{parameter_prefix}{i}" for i, key in enumerate(PARAMETER_KEYS, 1)},
    )
