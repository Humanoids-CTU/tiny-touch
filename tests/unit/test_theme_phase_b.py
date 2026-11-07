"""Headless checks for the Phase B ttkbootstrap theme helpers."""

import sys
from types import SimpleNamespace

import pytest

from gui import theme


class _FakeStyle:
    def __init__(self, theme):
        self.theme = theme
        self.configured = {}
        self.mapped = {}

    def configure(self, name, **kwargs):
        self.configured[name] = kwargs

    def map(self, name, **kwargs):
        self.mapped[name] = kwargs


class _FakeRoot:
    def __init__(self):
        self.options = {}

    def configure(self, **kwargs):
        self.options.update(kwargs)


class _Button:
    def __init__(self):
        self.style = ""
        self.repaints = 0

    def cget(self, option):
        assert option == "style"
        return self.style

    def configure(self, *, style):
        self.style = style
        self.repaints += 1


@pytest.mark.parametrize(
    ("state", "expected_style"),
    [
        ("ON", "StateOn.TButton"),
        ("OFF", "StateOff.TButton"),
        (None, "StateNeutral.TButton"),
        ("None", "StateNeutral.TButton"),
        ("", "StateNeutral.TButton"),
    ],
)
def test_set_button_state_maps_all_supported_values(state, expected_style):
    button = _Button()

    theme.set_button_state(button, state)

    assert button.style == expected_style


def test_unchanged_annotation_state_does_not_request_widget_repaints():
    button = _Button()
    theme.set_button_state(button, "ON")
    for _ in range(100):
        theme.set_button_state(button, "ON")
    assert button.style == "StateOn.TButton"
    assert button.repaints == 1

    theme.set_button_state(button, "OFF")
    assert button.style == "StateOff.TButton"
    assert button.repaints == 2


def test_style_changed_elsewhere_is_restored_without_a_stale_cache():
    button = _Button()
    theme.set_button_state(button, "ON")
    button.configure(style="Tool.TButton")
    theme.set_button_state(button, "ON")
    assert button.style == "StateOn.TButton"
