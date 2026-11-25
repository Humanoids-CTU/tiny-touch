"""
adapters/update_check.py
One look at GitHub per start for a newer TinyTouch release.

No GUI imports and standard library only. The request runs on a daemon thread
(`start_check`); the GUI polls the returned `UpdateCheck` from Tk's thread, so
the worker never touches Tk. Every failure is silent for the user and leaves one
log line; startup never waits for the network.

Only the validated version number leaves this module. The release-page URL is
built here from that number; no URL or text from the GitHub answer is opened or
displayed.
"""

import json
import logging
import os
import re
import sys
import threading
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

RELEASES_LATEST_API_URL = "https://api.github.com/repos/Humanoids-CTU/tiny-touch/releases/latest"
RELEASE_PAGE_BASE_URL = "https://github.com/Humanoids-CTU/tiny-touch/releases/tag/v"
REQUEST_TIMEOUT_S = 3.0
REQUEST_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "TinyTouch-update-check",   # generic: no user or machine data
}
MAX_RESPONSE_BYTES = 1_000_000   # the answer is a few kB; never read an unbounded body
# Development/test override: compare against this version instead of
# PROGRAM_VERSION (update check only, never exports or project data).
TEST_VERSION_ENV = "TINYTOUCH_UPDATE_TEST_VERSION"
# File-name marker of the release zip for each platform (sys.platform prefix).
PLATFORM_ASSET_MARKERS = {"win32": "-windows-", "linux": "-linux-"}

_TAG_PATTERN = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
_VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def parse_version(tag):
    """`"v9.5.0"` -> `(9, 5, 0)`; anything not exactly `vMAJOR.MINOR.PATCH` -> None."""
    if not isinstance(tag, str):
        return None
    match = _TAG_PATTERN.fullmatch(tag)
    return tuple(int(part) for part in match.groups()) if match else None


def parse_plain_version(value):
    """`"9.5.0"` -> `(9, 5, 0)`, or None (the form of PROGRAM_VERSION and the config)."""
    if not isinstance(value, str):
        return None
    match = _VERSION_PATTERN.fullmatch(value.strip())
    return tuple(int(part) for part in match.groups()) if match else None


def format_version(version) -> str:
    return ".".join(str(part) for part in version)


def release_page_url(version: str) -> str:
    """Release page for a validated `MAJOR.MINOR.PATCH` version string."""
    if parse_plain_version(version) is None:
        raise ValueError(f"not a release version: {version!r}")
    return RELEASE_PAGE_BASE_URL + version


def platform_asset_available(assets, platform=None) -> bool:
    """True when the release lists a file for `platform` (default: this one)."""
    platform = sys.platform if platform is None else platform
    marker = next((m for prefix, m in PLATFORM_ASSET_MARKERS.items()
                   if platform.startswith(prefix)), None)
    if marker is None or not isinstance(assets, list):
        return False
    return any(isinstance(asset, dict) and isinstance(asset.get("name"), str)
               and marker in asset["name"] for asset in assets)


def effective_current_version(program_version: str) -> str:
    """PROGRAM_VERSION, or the valid TINYTOUCH_UPDATE_TEST_VERSION override."""
    override = os.environ.get(TEST_VERSION_ENV)
    if override is None or override.strip() == "":
        return program_version
    if parse_plain_version(override) is None:
        logger.warning("update check: ignoring invalid %s=%r", TEST_VERSION_ENV, override)
        return program_version
    override = override.strip()
    logger.info("update check: %s=%s replaces %s for the check",
                TEST_VERSION_ENV, override, program_version)
    return override


def fetch_latest_release(timeout=REQUEST_TIMEOUT_S):
    """The parsed `releases/latest` answer (a dict). Raises on any failure."""
    request = urllib.request.Request(RELEASES_LATEST_API_URL, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("answer too large")
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("answer is not a JSON object")
    return data


def find_update(current: str, skipped=None, fetch=fetch_latest_release, platform=None):
    """The newer release version as `"MAJOR.MINOR.PATCH"`, or None.

    `current` is the version in use (see `effective_current_version`),
    `skipped` the version stored by "Skip this version". Never raises: every
    failure is logged in one line and returns None.
    """
    try:
        current_version = parse_plain_version(current)
        if current_version is None:
            logger.warning("update check skipped: current version %r is not MAJOR.MINOR.PATCH", current)
            return None
        release = fetch()
        if not isinstance(release, dict):
            raise ValueError("answer is not a JSON object")
        tag = release.get("tag_name")
        latest = parse_version(tag)
        if latest is None:
            logger.info("update check: ignoring release tag %r", tag)
            return None
        latest_text = format_version(latest)
        summary = f"latest {latest_text}, current {format_version(current_version)}"
        if latest <= current_version:
            logger.info("update check: %s, up to date", summary)
            return None
        if not platform_asset_available(release.get("assets"), platform):
            logger.info("update check: %s, no file for this platform", summary)
            return None
        if parse_plain_version(skipped) == latest:
            logger.info("update check: %s, skipped by the user", summary)
            return None
        logger.info("update check: %s, update available", summary)
        return latest_text
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # URLError/HTTPError, timeout, proxy and connection errors, bad JSON.
        logger.info("update check failed: %s", _describe(exc))
    except Exception as exc:   # never into startup
        logger.warning("update check failed unexpectedly: %r", exc)
    return None


def _describe(exc) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return str(exc.reason)
    return str(exc) or type(exc).__name__


class UpdateCheck:
    """Result holder shared between the worker thread and Tk's thread."""

    def __init__(self, current: str):
        self.current = current          # the version the check compared against
        self._done = threading.Event()
        self._latest = None

    def _finish(self, latest):
        self._latest = latest
        self._done.set()

    @property
    def done(self) -> bool:
        return self._done.is_set()

    @property
    def latest(self):
        """The newer version once `done`, otherwise None."""
        return self._latest if self._done.is_set() else None


def start_check(program_version: str, skipped=None, fetch=fetch_latest_release) -> UpdateCheck:
    """Start the background check; returns at once with an `UpdateCheck` to poll."""
    check = UpdateCheck(effective_current_version(program_version))

    def run():
        check._finish(find_update(check.current, skipped, fetch=fetch))

    threading.Thread(target=run, name="update-check", daemon=True).start()
    return check
