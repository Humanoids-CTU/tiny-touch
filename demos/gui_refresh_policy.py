"""Experimental widget setters, comparing live widget values before writing.

No frame throttling: changed values are forwarded immediately. This is a demo
policy, not installed on TinyTouch widgets. Live comparisons also observe style
or state changes from another GUI callback; no invalidation protocol is needed.
"""


class ConfiguredWidget:
    def __init__(self, widget, skip_unchanged=False):
        self.widget = widget
        self.skip_unchanged = skip_unchanged
        self.writes = 0

    def cget(self, option):
        return self.widget.cget(option)

    def configure(self, **options):
        changed = options
        if self.skip_unchanged:
            changed = {key: value for key, value in options.items()
                       if str(self.widget.cget(key)) != str(value)}
        if changed:
            self.widget.configure(**changed)
            self.writes += 1

    config = configure

def replace_note_if_changed(widget, text):
    """Compare actual text, including unsaved edits, rather than a note cache."""
    if widget.get("1.0", "end-1c") == text:
        return False
    widget.delete("1.0", "end")
    widget.insert("1.0", text)
    return True
