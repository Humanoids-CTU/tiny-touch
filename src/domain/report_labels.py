"""Immutable display labels for a report; calculation keys stay unchanged."""
from dataclasses import dataclass, field
from collections.abc import Mapping
from types import MappingProxyType

from domain.templates import DEFAULT_TEMPLATE, get_template
from domain.zone_display import ZoneDisplaySettings


@dataclass(frozen=True)
class ReportLabels:
    template: str = DEFAULT_TEMPLATE
    zone_labels: Mapping[str, str] = field(default_factory=dict)
    channel_labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self):
        definition = get_template(self.template)
        zones = ZoneDisplaySettings(self.zone_labels).labels
        ZoneDisplaySettings(self.channel_labels)  # validate text and lengths
        if set(self.channel_labels) - {channel.key for channel in definition.channels}:
            raise ValueError("Channel Labels contains an unknown channel ID")
        channels = {channel.key: channel.label for channel in definition.channels}
        channels.update({key: value.strip() for key, value in self.channel_labels.items() if value.strip()})
        object.__setattr__(self, "zone_labels", zones)
        object.__setattr__(self, "channel_labels", MappingProxyType(channels))

    def channel(self, key: str) -> str:
        return self.channel_labels.get(key, key)

    def zone(self, key: str) -> str:
        return f"{self.zone_labels[key]} ({key})" if key in self.zone_labels else key
