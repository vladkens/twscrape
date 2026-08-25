"""Covers the real bug found by testing against an actual multi-profile
Chrome install: browser_cookie3's chrome()/edge()/brave()/chromium() only
ever resolve the "Default" profile's Cookies file (first glob match wins).
A user whose X session lives in "Profile 2" would silently get missing or
wrong cookies with no indication why. These tests simulate that exact
layout without touching a real browser profile."""

import sys

import pytest

from twscrape.browser_cookies import BrowserCookiesError, get_x_cookies


class FakeCookie:
    def __init__(self, name, value):
        self.name = name
        self.value = value


class FakeChromeInstance:
    """Stands in for browser_cookie3.Chrome: cookie_file gets swapped and
    .load() re-read, matching how the real class behaves."""

    def __init__(self, jars_by_path, default_path, domain_name=None):
        self._jars_by_path = jars_by_path
        self.cookie_file = default_path
        self.domain_name = domain_name

    def load(self):
        jar = self._jars_by_path.get(self.cookie_file)
        if jar is None:
            raise FileNotFoundError(self.cookie_file)
        return jar


def install_fake_chrome_class(monkeypatch, profile_paths, jars_by_profile, default_index=0):
    """profile_paths: list of Path objects under one User Data dir, in the
    order Default should be checked first, then Profile 1, Profile 2, ...
    jars_by_profile: dict[Path, list[FakeCookie]] — only profiles with a
    findable session need an entry."""
    jars_by_path = {str(p): jar for p, jar in jars_by_profile.items()}
    default_path = str(profile_paths[default_index])

    def make_instance(domain_name=None):
        return FakeChromeInstance(jars_by_path, default_path, domain_name)

    fake_mod = type(sys)("browser_cookie3")
    fake_mod.chrome = lambda domain_name=None: make_instance(domain_name).load()
    fake_mod.Chrome = make_instance
    monkeypatch.setitem(sys.modules, "browser_cookie3", fake_mod)


def test_session_in_non_default_profile_is_found(tmp_path, monkeypatch):
    # Layout: Default has no x.com session at all, Profile 2 has the real one.
    user_data = tmp_path / "User Data"
    default_cookies = user_data / "Default" / "Cookies"
    profile1_cookies = user_data / "Profile 1" / "Cookies"
    profile2_cookies = user_data / "Profile 2" / "Cookies"
    for p in (default_cookies, profile1_cookies, profile2_cookies):
        p.parent.mkdir(parents=True)
        p.touch()

    jars = {
        default_cookies: [],  # no x.com cookies here
        profile1_cookies: [FakeCookie("ct0", "csrf-only")],  # partial, missing auth_token
        profile2_cookies: [FakeCookie("auth_token", "real-token"), FakeCookie("ct0", "real-csrf")],
    }
    install_fake_chrome_class(
        monkeypatch, [default_cookies, profile1_cookies, profile2_cookies], jars
    )

    result = get_x_cookies("chrome")
    assert result == {"auth_token": "real-token", "ct0": "real-csrf"}


def test_no_profile_has_full_session_reports_count(tmp_path, monkeypatch):
    user_data = tmp_path / "User Data"
    default_cookies = user_data / "Default" / "Cookies"
    profile1_cookies = user_data / "Profile 1" / "Cookies"
    for p in (default_cookies, profile1_cookies):
        p.parent.mkdir(parents=True)
        p.touch()

    jars = {
        default_cookies: [],
        profile1_cookies: [FakeCookie("ct0", "csrf-only")],  # partial only, never completes
    }
    install_fake_chrome_class(monkeypatch, [default_cookies, profile1_cookies], jars)

    with pytest.raises(BrowserCookiesError, match=r"2 chrome profile\(s\) checked"):
        get_x_cookies("chrome")


def test_default_profile_wins_when_it_has_the_session(tmp_path, monkeypatch):
    user_data = tmp_path / "User Data"
    default_cookies = user_data / "Default" / "Cookies"
    profile1_cookies = user_data / "Profile 1" / "Cookies"
    for p in (default_cookies, profile1_cookies):
        p.parent.mkdir(parents=True)
        p.touch()

    jars = {
        default_cookies: [FakeCookie("auth_token", "default-token"), FakeCookie("ct0", "default-csrf")],
        profile1_cookies: [FakeCookie("auth_token", "other-token"), FakeCookie("ct0", "other-csrf")],
    }
    install_fake_chrome_class(monkeypatch, [default_cookies, profile1_cookies], jars)

    result = get_x_cookies("chrome")
    # Default checked first — should win even though Profile 1 also has a full session.
    assert result == {"auth_token": "default-token", "ct0": "default-csrf"}
