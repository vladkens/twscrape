import sys
from types import SimpleNamespace

import pytest

from twscrape.browser_cookies import (
    BrowserCookiesError,
    get_x_cookies,
    get_x_cookies_string,
)


class FakeCookie:
    def __init__(self, name, value):
        self.name = name
        self.value = value


def install_fake_module(monkeypatch, loader):
    # firefox isn't in _MULTI_PROFILE_CLASSES, so this exercises the plain
    # single-call path — Chromium multi-profile scanning is covered
    # separately in test_browser_cookies_multiprofile.py.
    fake_mod = SimpleNamespace(firefox=loader)
    monkeypatch.setitem(sys.modules, "browser_cookie3", fake_mod)


def test_get_x_cookies_success(monkeypatch):
    def fake_firefox(domain_name=None):
        assert domain_name == "x.com"
        return [FakeCookie("auth_token", "tok"), FakeCookie("ct0", "csrf"), FakeCookie("other", "x")]

    install_fake_module(monkeypatch, fake_firefox)

    result = get_x_cookies("firefox")
    assert result == {"auth_token": "tok", "ct0": "csrf"}


def test_get_x_cookies_missing_required(monkeypatch):
    def fake_firefox(domain_name=None):
        return [FakeCookie("auth_token", "tok")]

    install_fake_module(monkeypatch, fake_firefox)

    with pytest.raises(BrowserCookiesError, match="ct0"):
        get_x_cookies("firefox")


def test_get_x_cookies_unsupported_browser(monkeypatch):
    install_fake_module(monkeypatch, lambda domain_name=None: [])

    with pytest.raises(BrowserCookiesError, match="Unsupported browser"):
        get_x_cookies("netscape-navigator")


def test_get_x_cookies_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "browser_cookie3", None)

    with pytest.raises(BrowserCookiesError, match="pip install twscrape\\[browser\\]"):
        get_x_cookies("firefox")


def test_get_x_cookies_loader_raises(monkeypatch):
    def fake_firefox(domain_name=None):
        raise RuntimeError("keychain locked")

    install_fake_module(monkeypatch, fake_firefox)

    with pytest.raises(BrowserCookiesError, match="keychain locked"):
        get_x_cookies("firefox")


def test_get_x_cookies_string_format(monkeypatch):
    def fake_firefox(domain_name=None):
        return [FakeCookie("auth_token", "tok"), FakeCookie("ct0", "csrf")]

    install_fake_module(monkeypatch, fake_firefox)

    assert get_x_cookies_string("firefox") == "auth_token=tok; ct0=csrf"
