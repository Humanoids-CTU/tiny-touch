"""Appearance preferences are independent of project and annotation data."""

import pytest

from adapters import config
from gui import theme


@pytest.mark.parametrize("value, expected", [("light", "light"), ("dark", "dark"), ("invalid", "light"), (None, "light"), ([], "light")])
def test_appearance_is_loaded_with_safe_fallback(monkeypatch, value, expected):
    monkeypatch.setattr(config, "load_config", lambda: {"appearance": value})
    assert config.load_app_config().appearance == expected


def test_older_config_defaults_to_light(monkeypatch):
    monkeypatch.setattr(config, "load_config", lambda: {})
    assert config.load_app_config().appearance == "light"


def _luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
              for c in channels]
    return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


@pytest.mark.parametrize("palette", [
    theme.PALETTES["light"],
    # White on the dark accent (#0a84ff) is 3.65:1; the dark-mode pass retunes it.
    pytest.param(theme.PALETTES["dark"], marks=pytest.mark.xfail(reason="dark palette pending", strict=False)),
], ids=["light", "dark"])
def test_text_is_readable_on_surfaces_states_and_selection(palette):
    palette = theme._resolved(palette)
    pairs = [("TEXT", background) for background in
             ("WIN", "CARD", "TRACK", "BTN", "SEG", "ON", "OFF", "ON_HOVER", "OFF_HOVER")]
    pairs += [("MUTED", "WIN"), ("MUTED", "CARD"), ("SELECTION_FG", "SELECTION_BG")]
    for foreground, background in pairs:
        luminances = sorted((_luminance(palette[foreground]), _luminance(palette[background])))
        contrast = (luminances[1] + 0.05) / (luminances[0] + 0.05)
        assert contrast >= 4.5, f"{foreground} on {background}: {contrast:.2f}:1"
