"""adapters.update_check: the startup release check, without network access.

Every test injects the fetch (or monkeypatches urlopen), so nothing here
contacts GitHub.
"""
import io
import json
import socket
import urllib.error

import pytest

from adapters import update_check
from adapters.update_check import (
    find_update,
    parse_plain_version,
    parse_version,
    platform_asset_available,
)

WINDOWS_ASSET = {"name": "TinyTouch-v9.5.0-windows-x64.zip"}
LINUX_ASSET = {"name": "TinyTouch-v9.5.0-linux-x64.zip"}


def release(tag="v9.5.0", assets=(WINDOWS_ASSET, LINUX_ASSET)):
    return lambda: {"tag_name": tag, "assets": list(assets)}


@pytest.fixture(autouse=True)
def no_override(monkeypatch):
    monkeypatch.delenv(update_check.TEST_VERSION_ENV, raising=False)


# --- version parsing and comparison -------------------------------------------------
@pytest.mark.parametrize("tag, expected", [
    ("v9.5.0", (9, 5, 0)),
    ("v10.0.12", (10, 0, 12)),
    ("v0.0.0", (0, 0, 0)),
])
def test_parse_version_accepts_release_tags(tag, expected):
    assert parse_version(tag) == expected


@pytest.mark.parametrize("tag", [
    "9.5.0", "v9.5", "v9.5.0-rc1", "v9.5.0.1", "V9.5.0", " v9.5.0", "v9.5.0\n",
    "vx.y.z", "", None, 950, "legacy-v9.5.0",
])
def test_parse_version_rejects_malformed_tags(tag):
    assert parse_version(tag) is None


def test_parse_plain_version():
    assert parse_plain_version("9.4.0") == (9, 4, 0)
    assert parse_plain_version("v9.4.0") is None
    assert parse_plain_version("9.4") is None
    assert parse_plain_version(None) is None


def test_comparison_is_numeric_not_textual():
    assert find_update("9.9.0", fetch=release("v9.10.0"), platform="win32") == "9.10.0"
    assert find_update("9.10.0", fetch=release("v9.9.0"), platform="win32") is None


def test_same_or_older_release_is_no_update():
    assert find_update("9.5.0", fetch=release("v9.5.0"), platform="win32") is None
    assert find_update("9.6.0", fetch=release("v9.5.0"), platform="win32") is None


def test_malformed_tag_is_no_update():
    assert find_update("9.4.0", fetch=release("v9.5.0-beta"), platform="win32") is None
    assert find_update("9.4.0", fetch=lambda: {"assets": [WINDOWS_ASSET]}, platform="win32") is None


def test_invalid_current_version_is_no_update():
    assert find_update("dev", fetch=release(), platform="win32") is None


# --- platform files -----------------------------------------------------------------
def test_platform_asset_matching():
    assets = [WINDOWS_ASSET]
    assert platform_asset_available(assets, "win32")
    assert not platform_asset_available(assets, "linux")
    assert platform_asset_available([LINUX_ASSET], "linux")
    assert not platform_asset_available([WINDOWS_ASSET, LINUX_ASSET], "darwin")
    assert not platform_asset_available([], "win32")
    assert not platform_asset_available(None, "win32")
    assert not platform_asset_available(["-windows-", {"name": 5}, {}], "win32")


def test_release_without_a_file_for_this_platform_is_no_update():
    only_windows = release(assets=[WINDOWS_ASSET])
    assert find_update("9.4.0", fetch=only_windows, platform="linux") is None
    assert find_update("9.4.0", fetch=only_windows, platform="win32") == "9.5.0"


# --- skipped version ----------------------------------------------------------------
def test_skipped_version_is_not_offered():
    assert find_update("9.4.0", skipped="9.5.0", fetch=release(), platform="win32") is None


def test_newer_than_skipped_is_offered():
    assert find_update("9.4.0", skipped="9.5.0", fetch=release("v9.6.0"), platform="win32") == "9.6.0"


def test_garbage_skipped_value_is_ignored():
    assert find_update("9.4.0", skipped=["9.5.0"], fetch=release(), platform="win32") == "9.5.0"


# --- test override ------------------------------------------------------------------
def test_env_override_replaces_the_current_version(monkeypatch):
    monkeypatch.setenv(update_check.TEST_VERSION_ENV, "9.3.0")
    assert update_check.effective_current_version("9.4.0") == "9.3.0"


@pytest.mark.parametrize("value", ["9.3", "v9.3.0", "latest", "9.3.0-dev"])
def test_invalid_env_override_is_ignored_with_a_log_line(monkeypatch, caplog, value):
    monkeypatch.setenv(update_check.TEST_VERSION_ENV, value)
    with caplog.at_level("WARNING", logger=update_check.__name__):
        assert update_check.effective_current_version("9.4.0") == "9.4.0"
    assert update_check.TEST_VERSION_ENV in caplog.text


def test_empty_env_override_is_ignored(monkeypatch):
    monkeypatch.setenv(update_check.TEST_VERSION_ENV, "")
    assert update_check.effective_current_version("9.4.0") == "9.4.0"


def test_env_override_does_not_change_program_version(monkeypatch):
    import app_info

    before = app_info.PROGRAM_VERSION
    monkeypatch.setenv(update_check.TEST_VERSION_ENV, "1.0.0")
    update_check.effective_current_version(before)
    assert app_info.PROGRAM_VERSION == before


def test_start_check_uses_the_override(monkeypatch):
    monkeypatch.setenv(update_check.TEST_VERSION_ENV, "9.3.0")
    check = update_check.start_check("9.4.0", fetch=release("v9.4.0"))
    check._done.wait(5)
    assert check.done
    assert check.current == "9.3.0"
    assert check.latest == ("9.4.0" if platform_asset_available([WINDOWS_ASSET, LINUX_ASSET]) else None)


def test_start_check_without_update():
    check = update_check.start_check("9.4.0", fetch=release("v9.4.0"))
    check._done.wait(5)
    assert check.done and check.latest is None


# --- failures -----------------------------------------------------------------------
class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def patch_urlopen(monkeypatch, behaviour):
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["request"], seen["timeout"] = request, timeout
        if isinstance(behaviour, BaseException):
            raise behaviour
        return FakeResponse(behaviour)

    monkeypatch.setattr(update_check.urllib.request, "urlopen", fake_urlopen)
    return seen


def test_fetch_sends_generic_headers_and_timeout(monkeypatch):
    body = json.dumps({"tag_name": "v9.5.0", "assets": [WINDOWS_ASSET]}).encode()
    seen = patch_urlopen(monkeypatch, body)
    assert update_check.fetch_latest_release()["tag_name"] == "v9.5.0"
    request = seen["request"]
    assert request.full_url == update_check.RELEASES_LATEST_API_URL
    assert request.get_header("Accept") == "application/vnd.github+json"
    assert request.get_header("User-agent") == "TinyTouch-update-check"
    assert seen["timeout"] == update_check.REQUEST_TIMEOUT_S


@pytest.mark.parametrize("body", [b"not json", b"[1, 2]", b"\xff\xfe", b""])
def test_malformed_answer_returns_none(monkeypatch, body):
    patch_urlopen(monkeypatch, body)
    assert find_update("9.4.0", platform="win32") is None


@pytest.mark.parametrize("error", [
    socket.timeout("timed out"),
    TimeoutError("timed out"),
    urllib.error.URLError("no network"),
    urllib.error.HTTPError(update_check.RELEASES_LATEST_API_URL, 403, "rate limited", {}, None),
    ConnectionResetError("reset"),
])
def test_network_failures_return_none_with_one_log_line(monkeypatch, caplog, error):
    patch_urlopen(monkeypatch, error)
    with caplog.at_level("INFO", logger=update_check.__name__):
        assert find_update("9.4.0", platform="win32") is None
    assert [r.getMessage() for r in caplog.records if "update check" in r.getMessage()] != []
    assert len(caplog.records) == 1
    assert caplog.records[0].getMessage().startswith("update check failed")


def test_unexpected_error_never_raises():
    def boom():
        raise RuntimeError("bug")

    assert find_update("9.4.0", fetch=boom, platform="win32") is None


def test_success_logs_one_line(caplog):
    with caplog.at_level("INFO", logger=update_check.__name__):
        find_update("9.4.0", fetch=release(), platform="win32")
    assert [r.getMessage() for r in caplog.records] == [
        "update check: latest 9.5.0, current 9.4.0, update available"]


# --- release page -------------------------------------------------------------------
def test_release_page_url_is_built_from_the_version():
    assert update_check.release_page_url("9.5.0") == (
        "https://github.com/Humanoids-CTU/tiny-touch/releases/tag/v9.5.0")
    with pytest.raises(ValueError):
        update_check.release_page_url("9.5.0/../../evil")
