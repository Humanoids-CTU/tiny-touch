"""Adopt recorded legacy labels without consulting mutable machine preferences."""
from collections.abc import Mapping
from dataclasses import dataclass, replace

from domain.coding_setup import CodingSetup
from domain.templates import get_template
from adapters.coding_configs import validate_coding_setup


@dataclass(frozen=True)
class LegacyCodingSetupReview:
    setup: CodingSetup
    needs_review: bool
    warning: str = ""


def _recover_parameters(raw, legacy_prefix, display_prefix, missing):
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ValueError("Historical parameter labels must be a mapping")
    allowed = {f"Par{i}" for i in (1, 2, 3)} | {f"{legacy_prefix}{i}" for i in (1, 2, 3)}
    if set(raw) - allowed:
        raise ValueError("Unknown historical parameter label keys")
    labels = {}
    for i in (1, 2, 3):
        internal, historical = f"Par{i}", f"{legacy_prefix}{i}"
        if internal in raw and historical in raw and raw[internal] != raw[historical]:
            raise ValueError("Conflicting historical parameter labels")
        label = raw.get(internal, raw.get(historical))
        if label is None or (isinstance(label, str) and not label.strip()):
            label = f"{display_prefix}{i}"
            missing.append(label)
        labels[internal] = label
    return labels


def inspect_legacy_coding_setup(repo, metadata=None):
    """Recover a review draft without writing project state.

    Known labels always survive partial historical metadata. Missing labels are
    visible placeholders, and the warning identifies every required decision.
    The caller must show this warning before accepting a review draft.
    """
    current = repo.load_coding_setup()
    if current is not None:
        return LegacyCodingSetupReview(current, False)
    metadata = {} if metadata is None else metadata
    if not isinstance(metadata, Mapping):
        raise ValueError("Historical export metadata must be an object")
    template = repo.load_template().template
    if template is None:
        raise ValueError("Historical project has no recorded template")
    if metadata.get("template", template) != template:
        raise ValueError("Historical export template conflicts with the project template")
    recorded_zones = repo.get_meta(f"zone_display:{template}") is not None
    zones = repo.load_zone_display(template).labels if recorded_zones else metadata.get("Zone Labels", {})
    if "Coding Setup" in metadata:
        setup = CodingSetup.from_dict(metadata["Coding Setup"])
        if setup.template != template:
            raise ValueError("Historical coding setup template conflicts with the project template")
        setup = replace(setup, zone_labels=zones if recorded_zones else setup.zone_labels)
        return LegacyCodingSetupReview(validate_coding_setup(setup), False)
    missing = []
    setup = CodingSetup(
        name="Reviewed project coding", template=template, zone_labels=zones,
        zone_layout="legacy" if template == "general" else "numbered",
        channel_labels=metadata.get("Channel Labels", {channel.key: channel.label for channel in get_template(template).channels}),
        parameter_labels=_recover_parameters(metadata.get("Param Labels"), "Parameter_", "P", missing),
        limb_parameter_labels=_recover_parameters(metadata.get("Limb Param Labels"), "XX_Parameter_", "CP", missing),
    )
    validate_coding_setup(setup)
    warning = ("Historical labels are missing for " + ", ".join(missing) + ". The displayed placeholders are not recovered labels. Confirm or replace them before preparing this video.") if missing else ""
    return LegacyCodingSetupReview(setup, bool(missing), warning)


def adopt_legacy_coding_setup(repo, metadata=None):
    """Return a full historical snapshot, or mark missing provenance for review.

    Older projects stored parameter labels only in export metadata. Defaults
    cannot safely reconstruct those labels after preferences have changed.
    """
    current = repo.load_coding_setup()
    if current is not None:
        return current
    try:
        review = inspect_legacy_coding_setup(repo, metadata)
        if review.needs_review:
            repo.set_meta("preparation_state", "needs_review")
            return None
        repo.save_coding_setup(review.setup, preparation_state="ready")
    except ValueError:
        repo.set_meta("preparation_state", "needs_review")
        return None
    return review.setup


def inherit_coding_setup(source_repo, target_repo):
    setup = source_repo.load_coding_setup()
    if setup is None or source_repo.load_preparation_state() != "ready":
        raise ValueError("Review and prepare the source video's coding setup first")
    target_repo.save_coding_setup(setup, preparation_state="draft")
    return setup
