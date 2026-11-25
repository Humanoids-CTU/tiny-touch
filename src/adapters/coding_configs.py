"""Named, shareable coding files; never reads or writes config.json."""
import json
from pathlib import Path

from adapters.atomic_io import atomic_write
from domain.coding_setup import CodingSetup
from domain.pose_setup import PoseCodingSetup
from adapters.zone_masks import editable_zone_names


def validate_coding_setup(setup):
    if isinstance(setup, PoseCodingSetup):
        return setup  # The typed constructor validates Alternate IDs and labels.
    allowed = set(editable_zone_names(setup.template))
    unknown = set(setup.zone_labels) - allowed
    if unknown:
        raise ValueError(f"Unknown zone aliases for {setup.template}: {', '.join(sorted(unknown))}")
    unknown = {zone for zones in setup.channel_zones.values() for zone in zones} - allowed
    if unknown:
        raise ValueError(f"Unknown channel zones for {setup.template}: {', '.join(sorted(unknown))}")
    return setup


class CodingConfigStore:
    def __init__(self, directory, *, pose=False):
        self.directory = Path(directory)
        self.pose = pose

    def list_configs(self):
        """Offer compatible setups; explicit import still reports invalid files."""
        compatible = []
        for path in sorted(self.directory.glob("*.json"), key=lambda path: path.name.casefold()):
            try:
                self.load(path)
            except (ValueError, OSError):
                continue
            compatible.append(path)
        return compatible

    def load(self, path):
        with Path(path).open(encoding="utf-8") as source:
            value = json.load(source)
        if not isinstance(value, dict):
            raise ValueError("A coding configuration must be a JSON object")
        if value.get("annotation_type") == "Pose":
            if not self.pose:
                raise ValueError("Choose a Touch coding configuration")
            return PoseCodingSetup.from_dict(value)
        setup = validate_coding_setup(CodingSetup.from_dict(value))
        if self.pose:
            return PoseCodingSetup(name=setup.name, template=setup.template,
                                   parameter_labels=setup.parameter_labels,
                                   zone_labels=setup.zone_labels)
        return setup

    def save(self, setup, filename, overwrite=False):
        if not isinstance(setup, PoseCodingSetup if self.pose else CodingSetup):
            raise ValueError("A complete coding configuration is required")
        validate_coding_setup(setup)
        filename = str(filename)
        if not filename or filename != filename.rstrip(" .") or any(char in filename for char in '/\\:<>"|?*') or any(ord(char) < 32 for char in filename):
            raise ValueError("Use a filename inside the coding configuration folder")
        stem = filename.split(".", 1)[0].upper()
        if stem in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
            raise ValueError("Use a filename that is portable across Windows and Linux")
        if not filename.lower().endswith(".json"):
            filename += ".json"
        destination = self.directory / filename
        if destination.exists() and not overwrite:
            raise FileExistsError(destination)
        atomic_write(str(destination), lambda file: json.dump(setup.to_dict(), file, ensure_ascii=False, indent=2))
        return destination

    def import_config(self, path, filename=None, overwrite=False):
        setup = self.load(path)  # Validate before touching the destination.
        return self.save(setup, filename or Path(path).name, overwrite=overwrite)
