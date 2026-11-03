"""Old or invalid settings must keep a usable renderer preference."""

import pytest

from adapters import config


@pytest.mark.parametrize("value,expected", [
    ("auto", "auto"), ("cpu", "cpu"), (None, "auto"),
    ("gpu", "auto"), ([], "auto"), ({}, "auto"),
])
def test_renderer_preference_has_safe_defaults(monkeypatch, value, expected):
    monkeypatch.setattr(config, "load_config", lambda: {"video_renderer": value})
    assert config.load_app_config().video_renderer == expected


def test_old_config_uses_automatic_renderer(monkeypatch):
    monkeypatch.setattr(config, "load_config", lambda: {})
    assert config.load_app_config().video_renderer == "auto"
