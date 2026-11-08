"""Immutable display labels for a report; calculation keys stay unchanged."""
from dataclasses import dataclass, field
from collections.abc import Mapping
from types import MappingProxyType

from domain.templates import DEFAULT_TEMPLATE, get_template
from domain.zone_display import ZoneDisplaySettings
from domain.coding_setup import CodingSetup


@dataclass(frozen=True)
class ReportLabels:
    template: str = DEFAULT_TEMPLATE
    zone_labels: Mapping[str, str] = field(default_factory=dict)
    channel_labels: Mapping[str, str] = field(default_factory=dict)
    export_format_version: int = 1
    coding_setup: CodingSetup | None = None

    def __post_init__(self):
        definition = get_template(self.template)
        zones = ZoneDisplaySettings(self.zone_labels).labels
        ZoneDisplaySettings(self.channel_labels)  # validate text and lengths
        if set(self.channel_labels) - {channel.key for channel in definition.channels}:
            raise ValueError("Channel Labels contains an unknown channel ID")
        if self.export_format_version >= 2:
            from domain.coding_setup import PORTABLE_CHANNELS
            channels = {key: f"Channel {i}" for i, key in enumerate(PORTABLE_CHANNELS.values(), 1)}
        else:
            channels = {channel.key: channel.label for channel in definition.channels}
        channels.update({key: value.strip() for key, value in self.channel_labels.items() if value.strip()})
        object.__setattr__(self, "zone_labels", zones)
        object.__setattr__(self, "channel_labels", MappingProxyType(channels))

    def channel(self, key: str) -> str:
        return self.channel_labels.get(key, key)

    def zone(self, key: str) -> str:
        return f"{self.zone_labels[key]} ({key})" if key in self.zone_labels else key

    def channel_id(self, key: str) -> str:
        if self.export_format_version >= 2:
            return {"RH":"Channel1", "LH":"Channel2", "RL":"Channel3", "LL":"Channel4"}.get(key,key)
        return key

    @property
    def channel_noun(self) -> str:
        return "Channel" if self.export_format_version >= 2 else get_template(self.template).channel_noun
