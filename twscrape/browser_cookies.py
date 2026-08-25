"""Read X session cookies straight from a local browser's cookie store.

No CDP, no automated login, no new browser instance — X fingerprints
navigator.webdriver and blocks Playwright/CDP-driven login flows, so this
avoids that fight entirely by reading the cookies of a session the user
already authenticated by hand, the same way tools like yt-dlp's
--cookies-from-browser do.
"""

from pathlib import Path
from typing import Callable

REQUIRED_COOKIES = ("auth_token", "ct0")

# domain_name kwarg narrows browser_cookie3's scan to x.com cookies only,
# so it never touches unrelated site cookies in the user's browser.
_LOADERS: dict[str, str] = {
    "chrome": "chrome",
    "chromium": "chromium",
    "firefox": "firefox",
    "edge": "edge",
    "safari": "safari",
    "brave": "brave",
    "opera": "opera",
}

# browser_cookie3's convenience functions (chrome(), edge(), ...) only ever
# resolve to the FIRST matching profile path on disk — "Default" beats
# "Profile 1", "Profile 2", etc. because it's listed first internally. A
# user whose X session lives in a non-default profile (very common — work
# vs personal Chrome profiles) gets silently wrong or missing cookies with
# no error. These four share Chromium's "User Data/<Profile>/Cookies"
# layout, so for them we scan every sibling profile ourselves instead of
# trusting the single path browser_cookie3 would have picked.
_MULTI_PROFILE_CLASSES = {"chrome", "chromium", "edge", "brave"}


class BrowserCookiesError(Exception): ...


def _get_loader(browser: str) -> Callable:
    try:
        import browser_cookie3
    except ImportError as e:
        raise BrowserCookiesError(
            "browser_cookie3 not installed. Install with: pip install twscrape[browser]"
        ) from e

    name = _LOADERS.get(browser.lower())
    if name is None:
        raise BrowserCookiesError(
            f"Unsupported browser '{browser}'. Choose from: {', '.join(_LOADERS)}"
        )

    loader = getattr(browser_cookie3, name)
    cls = getattr(browser_cookie3, name.capitalize()) if name in _MULTI_PROFILE_CLASSES else None
    return loader, cls


def _profile_cookie_files(default_cookie_file: str) -> list[Path]:
    """Given the resolved 'Default' profile Cookies path, find sibling
    profile Cookies files (Profile 1, Profile 2, ... and their newer
    Network/Cookies variant) under the same User Data root."""
    default_path = Path(default_cookie_file)
    # .../User Data/Default/Cookies -> user_data_dir = .../User Data
    # .../User Data/Default/Network/Cookies -> same, one level deeper
    user_data_dir = default_path.parent.parent
    if default_path.parent.name == "Network":
        user_data_dir = user_data_dir.parent

    candidates = [default_path]
    candidates += sorted(user_data_dir.glob("Profile */Cookies"))
    candidates += sorted(user_data_dir.glob("Profile */Network/Cookies"))
    # de-dupe while preserving order (Default first)
    seen: set[Path] = set()
    ordered = []
    for c in candidates:
        if c not in seen and c.is_file():
            seen.add(c)
            ordered.append(c)
    return ordered


def _load_multi_profile(cls: type, domain_name: str) -> tuple:
    """Try every Chromium-family profile in order, return the jar from the
    first one containing both required cookies. Returns (jar, tried_count)."""
    inst = cls(domain_name=domain_name)  # resolves Default path, derives decrypt key once
    profiles = _profile_cookie_files(inst.cookie_file)

    tried = 0
    for cookie_file in profiles:
        inst.cookie_file = str(cookie_file)
        try:
            jar = inst.load()
        except Exception:
            continue
        tried += 1
        names = {c.name for c in jar}
        if all(r in names for r in REQUIRED_COOKIES):
            return jar, tried

    return None, max(tried, len(profiles))


def get_x_cookies(browser: str = "chrome") -> dict[str, str]:
    """Extract auth_token + ct0 for x.com from the given local browser.

    Raises BrowserCookiesError if the browser/profile can't be read (locked
    keychain, browser not installed, no active x.com session) or the
    required cookies aren't present (user isn't logged in — checked across
    every profile for Chromium-family browsers, since the login may not be
    in the default one).
    """
    browser_key = browser.lower()
    loader, cls = _get_loader(browser)

    if browser_key in _MULTI_PROFILE_CLASSES:
        try:
            jar, profiles_checked = _load_multi_profile(cls, "x.com")
        except Exception as e:
            raise BrowserCookiesError(f"Could not read {browser} cookies: {e}") from e

        if jar is None:
            raise BrowserCookiesError(
                f"No x.com session with both {' and '.join(REQUIRED_COOKIES)} found in "
                f"any of {profiles_checked} {browser} profile(s) checked — make sure "
                f"you're logged into x.com in one of them"
            )
        return {c.name: c.value for c in jar if c.name in REQUIRED_COOKIES}

    try:
        jar = loader(domain_name="x.com")
    except Exception as e:
        raise BrowserCookiesError(f"Could not read {browser} cookies: {e}") from e

    found = {c.name: c.value for c in jar if c.name in REQUIRED_COOKIES}
    missing = [name for name in REQUIRED_COOKIES if name not in found]
    if missing:
        raise BrowserCookiesError(
            f"Missing {', '.join(missing)} in {browser}'s x.com cookies — "
            "make sure you're logged into x.com in that browser"
        )

    return found


def get_x_cookies_string(browser: str = "chrome") -> str:
    cookies = get_x_cookies(browser)
    return "; ".join(f"{k}={v}" for k, v in cookies.items())
