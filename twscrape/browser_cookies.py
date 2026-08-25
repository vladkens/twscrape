"""Read X session cookies straight from a local browser's cookie store.

No CDP, no automated login, no new browser instance — X fingerprints
navigator.webdriver and blocks Playwright/CDP-driven login flows, so this
avoids that fight entirely by reading the cookies of a session the user
already authenticated by hand, the same way tools like yt-dlp's
--cookies-from-browser do.
"""

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

    return getattr(browser_cookie3, name)


def get_x_cookies(browser: str = "chrome") -> dict[str, str]:
    """Extract auth_token + ct0 for x.com from the given local browser.

    Raises BrowserCookiesError if the browser/profile can't be read (locked
    keychain, browser not installed, no active x.com session) or the
    required cookies aren't present (user isn't logged in).
    """
    loader = _get_loader(browser)

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
