"""Project display names are aliases; annotation zone IDs never change."""
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType


MAX_ZONE_LABEL_LENGTH = 40


@dataclass(frozen=True)
class ZoneDisplaySettings:
    labels: Mapping[str, str] = field(default_factory=dict)
    show_names: bool = False

    def __post_init__(self):
        if not isinstance(self.show_names, bool) or not isinstance(self.labels, Mapping):
            raise ValueError("Invalid zone display settings")
        normalized = {}
        for zone, name in self.labels.items():
            if not isinstance(zone, str) or not zone or not isinstance(name, str):
                raise ValueError("Zone IDs and names must be text")
            name = name.strip()
            if len(name) > MAX_ZONE_LABEL_LENGTH or any(ord(char) < 32 for char in name):
                raise ValueError(f"Zone {zone}: use one line of at most {MAX_ZONE_LABEL_LENGTH} characters")
            if name and name != zone:
                normalized[zone] = name
        object.__setattr__(self, "labels", MappingProxyType(normalized))

    def label(self, zone: str) -> str:
        return self.labels.get(zone, zone)
