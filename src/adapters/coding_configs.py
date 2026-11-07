"""Named, shareable coding files; never reads or writes config.json."""
import json
from pathlib import Path

from adapters.atomic_io import atomic_write
from domain.coding_setup import CodingSetup
from adapters.zone_masks import editable_zone_names


def validate_coding_setup(setup):
    unknown = set(setup.zone_labels) - set(editable_zone_names(setup.template))
    if unknown:
        raise ValueError(f"Unknown zone aliases for {setup.template}: {', '.join(sorted(unknown))}")
    return setup


class CodingConfigStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def list_configs(self):
        return sorted(self.directory.glob("*.json"), key=lambda path: path.name.casefold())

    def load(self, path):
        with Path(path).open(encoding="utf-8") as source:
            return validate_coding_setup(CodingSetup.from_dict(json.load(source)))

    def save(self, setup, filename, overwrite=False):
        if not isinstance(setup, CodingSetup):
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
