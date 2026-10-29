"""Native title-bar behavior without creating or focusing any windows."""

import ctypes
from types import SimpleNamespace

import pytest

from gui import theme


@pytest.mark.parametrize("appearance", ("light", "dark"))
def test_existing_and_new_windows_receive_current_appearance(monkeypatch, appearance):
    calls = []
    monkeypatch.setattr(theme, "apply_title_bar", lambda window, **kw: calls.append((window, kw)))
    monkeypatch.setattr(theme, "_appearance", appearance)
    dialog = SimpleNamespace(winfo_children=lambda: [])
    dialog.winfo_toplevel = lambda: dialog
    root = SimpleNamespace(winfo_children=lambda: [dialog])
    root.winfo_toplevel = lambda: root
    theme._refresh_colors(root)
    assert [window for window, _ in calls] == [root, dialog]
    assert all(options == dict(dark=appearance == "dark", background=theme.SURFACE,
                               foreground=theme.TEXT) for _, options in calls)

    calls.clear()
    theme._on_window_map(SimpleNamespace(widget=dialog))
    assert calls[0][0] is dialog
    assert calls[0][1]["dark"] == (appearance == "dark")

    calls.clear()
    theme._on_window_map(SimpleNamespace(widget=SimpleNamespace(winfo_toplevel=lambda: root)))
    theme._on_window_map(SimpleNamespace(widget=".!combobox.popdown"))
    assert calls == []


def test_unavailable_windows_library_is_nonfatal(monkeypatch, caplog):
    from gui import native_title_bar

    def unavailable():
        raise OSError("DWM unavailable")

    monkeypatch.setattr(native_title_bar.sys, "platform", "win32")
    monkeypatch.setattr(native_title_bar, "_windows_api", unavailable)
    with caplog.at_level("DEBUG"):
        assert not native_title_bar.apply_title_bar(
            None, dark=True, background="#24282f", foreground="#e4e8ef",
        )
    assert "DWM unavailable" in caplog.text


@pytest.mark.parametrize("dark", (False, True))
def test_native_caption_and_text_match_app_colors(monkeypatch, dark):
    from gui import native_title_bar

    calls = []

    def set_attribute(hwnd, attribute, pointer, size):
        value = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32)).contents.value
        calls.append((hwnd, attribute, value, size))
        return 0

    monkeypatch.setattr(native_title_bar.sys, "platform", "win32")
    monkeypatch.setattr(native_title_bar, "_windows_api", lambda: (
        lambda hwnd, flag: 0x123456789, set_attribute,
    ))
    window = SimpleNamespace(winfo_id=lambda: 42)
    assert native_title_bar.apply_title_bar(window, dark=dark, background="#24282f", foreground="#e4e8ef")
    assert calls == [
        (0x123456789, 20, int(dark), 4),
        (0x123456789, 35, 0x2f2824, 4),
        (0x123456789, 36, 0xefe8e4, 4),
    ]


def test_non_windows_does_not_load_windows_libraries(monkeypatch):
    from gui import native_title_bar

    monkeypatch.setattr(native_title_bar.sys, "platform", "linux")
    monkeypatch.setattr(native_title_bar, "_windows_api", lambda: pytest.fail("Windows DLL loaded on Linux"))
    assert not native_title_bar.apply_title_bar(None, dark=True, background="#24282f", foreground="#e4e8ef")


def test_unsupported_windows_attributes_leave_app_usable(monkeypatch, caplog):
    from gui import native_title_bar

    monkeypatch.setattr(native_title_bar.sys, "platform", "win32")
    monkeypatch.setattr(native_title_bar, "_windows_api", lambda: (
        lambda hwnd, flag: 99, lambda *args: -2147024809,
    ))
    with caplog.at_level("DEBUG"):
        assert not native_title_bar.apply_title_bar(
            SimpleNamespace(winfo_id=lambda: 42), dark=True,
            background="#24282f", foreground="#e4e8ef",
        )
    assert "title bar" in caplog.text.lower()
