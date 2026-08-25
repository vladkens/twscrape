from unittest.mock import MagicMock, call

import pytest

import twscrape.xclid as xclid
from twscrape.http import HttpxClient, NetworkError

from .mock_http import MockClient


class FakeClient:
    def __init__(self):
        self.closed = False
        self.cookies = MagicMock()

    async def aclose(self):
        self.closed = True


async def test_xclid_create_passes_proxy_and_cookies_to_client(monkeypatch):
    seen = {}
    fake_client = FakeClient()

    def fake_make_client(*, headers=None, proxy=None, cookies=None):
        seen["headers"] = headers
        seen["proxy"] = proxy
        seen["cookies"] = cookies
        return fake_client

    async def fake_get_tw_page_text(url, clt):
        seen["url"] = url
        seen["client"] = clt
        return "<html></html>"

    async def fake_load_keys(soup, clt):
        seen["load_client"] = clt
        return [1, 2, 3], "anim-key"

    monkeypatch.setattr(xclid, "_make_http_client", fake_make_client)
    monkeypatch.setattr(xclid, "get_tw_page_text", fake_get_tw_page_text)
    monkeypatch.setattr(xclid, "load_keys", fake_load_keys)

    proxy = "http://127.0.0.1:7897"
    cookies = {"auth_token": "abc", "ct0": "def"}
    gen = await xclid.XClIdGen.create(proxy=proxy, cookies=cookies)

    assert gen.vk_bytes == [1, 2, 3]
    assert gen.anim_key == "anim-key"
    assert seen["headers"] == {"user-agent": "@chrome"}
    assert seen["proxy"] == proxy
    assert seen["cookies"] is None
    assert fake_client.cookies.set.call_args_list == [
        call("auth_token", "abc", domain=".x.com"),
        call("ct0", "def", domain=".x.com"),
    ]
    assert seen["url"] == "https://x.com/tesla"
    assert seen["client"] is fake_client
    assert seen["load_client"] is fake_client
    assert fake_client.closed is True


async def test_xclid_create_without_proxy_or_cookies(monkeypatch):
    seen = {}
    fake_client = FakeClient()

    def fake_make_client(*, headers=None, proxy=None, cookies=None):
        seen["proxy"] = proxy
        seen["cookies"] = cookies
        return fake_client

    async def fake_get_tw_page_text(url, clt):
        return "<html></html>"

    async def fake_load_keys(soup, clt):
        return [1, 2, 3], "anim-key"

    monkeypatch.setattr(xclid, "_make_http_client", fake_make_client)
    monkeypatch.setattr(xclid, "get_tw_page_text", fake_get_tw_page_text)
    monkeypatch.setattr(xclid, "load_keys", fake_load_keys)

    await xclid.XClIdGen.create()
    assert seen == {"proxy": None, "cookies": None}


async def test_xclid_client_does_not_send_cookies_to_asset_hosts(monkeypatch):
    monkeypatch.setenv("TWS_HTTP_BACKEND", "httpx")
    client = xclid._make_client(cookies={"auth_token": "abc", "ct0": "def"})
    assert isinstance(client, HttpxClient)
    try:
        x_request = client._client.build_request("GET", "https://x.com/tesla")
        asset_request = client._client.build_request(
            "GET", "https://abs.twimg.com/x-web/client-web/main.js"
        )
        assert x_request.headers["cookie"] == "auth_token=abc; ct0=def"
        assert "cookie" not in asset_request.headers
    finally:
        await client.aclose()


async def test_xclid_curl_client_scopes_cookies_to_x(monkeypatch):
    monkeypatch.setenv("TWS_HTTP_BACKEND", "curl")
    client = xclid._make_client(cookies={"auth_token": "abc"})
    try:
        cookies = list(client.cookies.jar)
        assert [(x.name, x.domain) for x in cookies] == [("auth_token", ".x.com")]
    finally:
        await client.aclose()


async def test_logged_out_entry_is_account_error():
    html = (
        '<script src="https://abs.twimg.com/x-web/client-web/'
        'entry-client-logged-out-a1b2c3.js"></script>'
    )

    with pytest.raises(xclid.XClIdAccountError, match="Logged-out X web app"):
        await xclid.parse_anim_idx(html, MockClient())


def test_script_list_combines_direct_and_reconstructed_urls():
    html = (
        '<script src="https://abs.twimg.com/x-web/x-web/app-a1b2c3.js"></script>'
        '<script src="https://abs.twimg.com/responsive-web/client-web/vendor.1234567a.js"></script>'
        '<script src="/responsive-web/client-web/main.15e48250ae23af9ea.js"></script>'
        '{100:"shared~feature"}+{100:"00c0ffee00c0ffee"}'
    )

    urls = xclid.get_scripts_list(html)

    assert urls == [
        "https://abs.twimg.com/x-web/x-web/app-a1b2c3.js",
        "https://abs.twimg.com/responsive-web/client-web/vendor.1234567a.js",
        "https://abs.twimg.com/responsive-web/client-web/main.15e48250ae23af9ea.js",
        "https://abs.twimg.com/responsive-web/client-web/shared~feature.00c0ffee00c0ffeea.js",
    ]


# In the legacy webpack fixtures the name map comes BEFORE the hash map: hash values
# must be excluded from the name map by format alone, or they overwrite the names.
def test_legacy_webpack_build_with_7_hex_hashes():
    html = '{100:"main",200:"shared~feature"}+{100:"a1b2c3d",200:"0badca4"}'

    urls = xclid.get_scripts_list(html)

    assert urls == [
        "https://abs.twimg.com/responsive-web/client-web/main.a1b2c3da.js",
        "https://abs.twimg.com/responsive-web/client-web/shared~feature.0badca4a.js",
    ]


def test_legacy_webpack_build_with_16_hex_hashes():
    # Hash format served since 2026-08-24, e.g. main.15e48250ae23af9ea.js
    # https://github.com/vladkens/twscrape/issues/327
    html = '{100:"main",200:"shared~feature"}+{100:"15e48250ae23af9e",200:"00c0ffee00c0ffee"}'

    urls = xclid.get_scripts_list(html)

    assert urls == [
        "https://abs.twimg.com/responsive-web/client-web/main.15e48250ae23af9ea.js",
        "https://abs.twimg.com/responsive-web/client-web/shared~feature.00c0ffee00c0ffeea.js",
    ]


async def test_find_indices_url_complete_scan_is_parse_error():
    client = MockClient()
    client.add_response(text="no reference")
    client.add_response(text="still no reference")

    with pytest.raises(
        xclid.XClIdParseError,
        match=r"Signing script not found \(assets: 2 loaded, 0 failed\)",
    ):
        await xclid._find_indices_url(["https://x.test/a.js", "https://x.test/b.js"], client)


async def test_find_indices_url_summarizes_transport_error(monkeypatch):
    client = MockClient()
    error = NetworkError("asset timeout")
    client.add_exception(error)
    client.add_response(text="no reference")
    messages = []
    monkeypatch.setattr(xclid.logger, "trace", messages.append)

    with pytest.raises(
        xclid.XClIdParseError,
        match=r"Signing script not found \(assets: 1 loaded, 1 failed\)",
    ):
        await xclid._find_indices_url(["https://x.test/a.js", "https://x.test/b.js"], client)

    assert messages == ["XClId asset failed: NetworkError - https://x.test/a.js"]


async def test_find_indices_url_summarizes_http_error(monkeypatch):
    client = MockClient()
    client.add_response(status_code=503)
    client.add_response(text="no reference")
    messages = []
    monkeypatch.setattr(xclid.logger, "trace", messages.append)

    with pytest.raises(
        xclid.XClIdParseError,
        match=r"Signing script not found \(assets: 1 loaded, 1 failed\)",
    ):
        await xclid._find_indices_url(["https://x.test/a.js", "https://x.test/b.js"], client)

    assert messages == ["XClId asset failed: HttpStatusError 503 - https://x.test/a.js"]


async def test_find_indices_url_returns_reference_despite_unrelated_failure():
    client = MockClient()
    client.add_exception(NetworkError("asset timeout"))
    client.add_response(text='import("./sign.o-abc123.js")')

    url = await xclid._find_indices_url(
        ["https://x.test/assets/a.js", "https://x.test/assets/b.js"], client
    )

    assert url == "https://x.test/assets/sign.o-abc123.js"
