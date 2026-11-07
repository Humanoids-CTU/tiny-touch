"""Behavior checks for the experimental changed-only widget setters."""

import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "gui_refresh_policy", Path(__file__).resolve().parents[2] / "demos" / "gui_refresh_policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class Widget:
    def __init__(self):
        self.options = {}
        self.calls = []
        self.text = ""

    def configure(self, **options):
        self.calls.append(options)
        self.options.update(options)

    def cget(self, option):
        return self.options.get(option, "")

    def get(self, *args):
        return self.text

    def delete(self, *args):
        self.text = ""

    def insert(self, index, text):
        self.text = text


def test_same_values_skip_writes_but_frame_counter_changes_immediately():
    widget = Widget()
    setter = policy.ConfiguredWidget(widget, skip_unchanged=True)
    setter.configure(text="49 / 100", state="normal")
    setter.configure(text="49 / 100", state="normal")
    setter.configure(text="50 / 100", state="normal")
    assert widget.options == {"text": "50 / 100", "state": "normal"}
    assert widget.calls == [{"text": "49 / 100", "state": "normal"}, {"text": "50 / 100"}]


def test_style_changes_and_external_writes_are_seen():
    widget = Widget()
    setter = policy.ConfiguredWidget(widget, skip_unchanged=True)
    for style in ("neutral", "on", "off", "neutral"):
        setter.configure(style=style)
        assert widget.options["style"] == style
    widget.configure(style="external")
    assert setter.cget("style") == "external"
    setter.configure(style="neutral")
    assert widget.options["style"] == "neutral"


def test_note_compares_actual_text_including_user_draft():
    widget = Widget()
    assert policy.replace_note_if_changed(widget, "same note")
    assert not policy.replace_note_if_changed(widget, "same note")
    widget.text = "unsaved draft"
    assert policy.replace_note_if_changed(widget, "same note")
    assert widget.text == "same note"
    assert policy.replace_note_if_changed(widget, "")
    assert widget.text == ""
