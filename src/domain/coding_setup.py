"""Immutable study labels, independent of machine preferences and geometry."""
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from domain.templates import get_template
from domain.zone_display import ZoneDisplaySettings

SCHEMA_VERSION = 2
CHANNEL_KEYS = ("RH", "LH", "RF", "LF")
PARAMETER_KEYS = ("Par1", "Par2", "Par3")
PORTABLE_CHANNELS = dict(zip(("Channel1", "Channel2", "Channel3", "Channel4"), CHANNEL_KEYS))
# Serialized for the frozen export metadata contract; it is the only value.
ZONE_LAYOUT = "numbered"
FIELDS = {"schema_version", "name", "template", "zone_labels", "zone_layout", "channel_zones",
          "channel_labels", "parameter_labels", "channel_parameter_labels"}
OLDER_CONFIGURATION = ("This coding configuration was made by an older version of TinyTouch "
                       "and cannot be read. Recreate it in the coding setup wizard.")


def default_channel_zones(template):
    """Defaults match the filled regions in the shipped channel reference images."""
    get_template(template)
    zones = {
        "default": ("N", "M", "B", "A"),
        "alternate": ("L", "K", "B", "A"),
        "general": ("9", "10", "11", "12"),
    }[template]
    return {key: (zone,) for key, zone in zip(CHANNEL_KEYS, zones)}


def _channel_zones(value):
    if not isinstance(value, Mapping) or set(value) != set(CHANNEL_KEYS):
        raise ValueError("Channel zones must contain exactly RH, LH, RF, LF")
    result, claimed = {}, set()
    for key in CHANNEL_KEYS:
        zones = value[key]
        if not isinstance(zones, (list, tuple)) or any(not isinstance(zone, str) or not zone or zone != zone.strip() for zone in zones):
            raise ValueError("Channel zones must be lists of zone IDs")
        if len(set(zones)) != len(zones) or claimed.intersection(zones):
            raise ValueError("Each zone can belong to only one channel")
        result[key] = tuple(zones)
        claimed.update(zones)
    return MappingProxyType(result)


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
    channel_zones: Mapping[str, tuple[str, ...]] | None = None

    def __post_init__(self):
        get_template(self.template)
        zones = default_channel_zones(self.template) if self.channel_zones is None else self.channel_zones
        object.__setattr__(self, "channel_zones", _channel_zones(zones))
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
            "zone_layout": ZONE_LAYOUT,
            "channel_zones": {portable: list(self.channel_zones[key]) for portable, key in PORTABLE_CHANNELS.items()},
            "channel_labels": {portable: self.channel_labels[key] for portable, key in PORTABLE_CHANNELS.items()},
            "parameter_labels": dict(self.parameter_labels),
            "channel_parameter_labels": dict(self.limb_parameter_labels),
        }

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("A coding configuration must be a JSON object")
        version = value.get("schema_version")
        if type(version) is int and version < SCHEMA_VERSION:
            raise ValueError(OLDER_CONFIGURATION)
        if type(version) is not int or version != SCHEMA_VERSION:
            raise ValueError("Unsupported coding configuration version")
        if set(value) != FIELDS:
            raise ValueError("Coding configuration has missing or unknown fields")
        if value["zone_layout"] != ZONE_LAYOUT:  # Only older versions wrote another value.
            raise ValueError(OLDER_CONFIGURATION)
        channels = _labels(value["channel_labels"], tuple(PORTABLE_CHANNELS), "Portable channel labels")
        zones = value["channel_zones"]
        if not isinstance(zones, Mapping) or set(zones) != set(PORTABLE_CHANNELS):
            raise ValueError("Portable channel zones must contain exactly Channel1, Channel2, Channel3, Channel4")
        return cls(name=value["name"], template=value["template"], zone_labels=value["zone_labels"],
                   channel_zones={key: zones[portable] for portable, key in PORTABLE_CHANNELS.items()},
                   channel_labels={key: channels[portable] for portable, key in PORTABLE_CHANNELS.items()},
                   parameter_labels=value["parameter_labels"],
                   limb_parameter_labels=value["channel_parameter_labels"])


def default_coding_setup(template="default", parameter_labels=None, limb_parameter_labels=None):
    definition = get_template(template)
    parameter_prefix = "CP" if template == "general" else "LP"
    return CodingSetup(
        name=f"{definition.label} coding", template=template,
        channel_labels={key: definition.channel_label(key) for key in CHANNEL_KEYS},
        parameter_labels=parameter_labels if parameter_labels is not None else {key: f"P{i}" for i, key in enumerate(PARAMETER_KEYS, 1)},
        limb_parameter_labels=limb_parameter_labels if limb_parameter_labels is not None else {key: f"{parameter_prefix}{i}" for i, key in enumerate(PARAMETER_KEYS, 1)},
    )
