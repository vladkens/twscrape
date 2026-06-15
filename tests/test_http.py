from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from curl_cffi.const import CurlECode
from curl_cffi.requests.errors import RequestsError

from twscrape.http import (
    _CURL_MAX_RETRIES,
    ConnectError,
    CurlClient,
    HttpClient,
    HttpError,
    HttpStatusError,
    HttpxClient,
    NetworkError,
    Response,
    _detect_backend,
    _resolve_browser,
    make_client,
)

from .mock_http import _raw

# --- Response wrapper ---


def test_response_delegates_attributes():
    raw = _raw(status_code=200, text="hello", json_data={"key": "val"})
    rep = Response(raw)
    assert rep.status_code == 200
    assert rep.text == "hello"
    assert rep.json() == {"key": "val"}
    assert rep.request.method == "GET"


def test_response_raise_for_status_ok():
    rep = Response(_raw(status_code=200))
    rep.raise_for_status()  # should not raise


def test_response_raise_for_status_error():
    rep = Response(_raw(status_code=403, text="ok"))
    with pytest.raises(HttpStatusError) as exc_info:
        rep.raise_for_status()
    err = exc_info.value
    assert err.response is rep
    assert err.response.status_code == 403
    assert err.response.text == "ok"


def test_response_allows_setattr():
    rep = Response(_raw(status_code=200))
    setattr(rep, "__username", "alice")
    assert getattr(rep, "__username") == "alice"


# --- Exception hierarchy ---


def test_exception_hierarchy():
    assert issubclass(HttpStatusError, HttpError)
    assert issubclass(NetworkError, HttpError)
    assert issubclass(ConnectError, HttpError)


def test_http_status_error_carries_response():
    raw = _raw(status_code=500, text="server error")
    resp = Response(raw)
    err = HttpStatusError("fail", response=resp)
    assert err.response is resp
    assert err.response.status_code == 500
    assert err.response.text == "server error"


# --- _detect_backend ---


def test_detect_backend_env_curl_not_installed(monkeypatch):
    monkeypatch.setenv("TWS_HTTP_BACKEND", "curl")
    with (
        patch.dict("sys.modules", {"curl_cffi": None}),
        pytest.raises(ImportError, match="curl-cffi is not installed"),
    ):
        _detect_backend()


def test_detect_backend_env_httpx(monkeypatch):
    monkeypatch.setenv("TWS_HTTP_BACKEND", "httpx")
    result = _detect_backend()
    assert result == "httpx"


def test_detect_backend_env_missing_backend(monkeypatch):
    monkeypatch.setenv("TWS_HTTP_BACKEND", "httpx")
    with (
        patch.dict("sys.modules", {"httpx": None}),
        pytest.raises(ImportError, match="not installed"),
    ):
        _detect_backend()


def test_detect_backend_invalid_value(monkeypatch):
    monkeypatch.setenv("TWS_HTTP_BACKEND", "requests")
    with pytest.raises(ValueError, match="Invalid"):
        _detect_backend()


def test_detect_backend_default_httpx(monkeypatch):
    monkeypatch.delenv("TWS_HTTP_BACKEND", raising=False)
    result = _detect_backend()
    assert result == "httpx"


def test_detect_backend_default_httpx_missing(monkeypatch):
    monkeypatch.delenv("TWS_HTTP_BACKEND", raising=False)
    with (
        patch.dict("sys.modules", {"httpx": None}),
        pytest.raises(ImportError, match="httpx is not installed"),
    ):
        _detect_backend()


# --- HttpClient base ---


async def test_http_client_is_async_context_manager():
    class MinimalClient(HttpClient):
        closed = False

        async def request(self, method, url, **kwargs):
            return Response(_raw())

        async def aclose(self):
            self.closed = True

        @property
        def cookies(self):
            return {}

        @property
        def headers(self):
            return {}

    client = MinimalClient()
    async with client as c:
        assert c is client
    assert client.closed


# --- HttpxClient ---


def test_make_client_httpx_returns_httpx_client(monkeypatch):
    monkeypatch.delenv("TWS_HTTP_BACKEND", raising=False)
    client = make_client("httpx")
    assert isinstance(client, HttpxClient)


async def test_httpx_client_cookies_and_headers_are_mutable():
    client = HttpxClient(headers={"x-foo": "bar"}, cookies={"ct0": "token"})
    # headers support __setitem__
    client.headers["x-new"] = "value"
    # cookies support __contains__
    assert "ct0" in client.cookies
    await client.aclose()


async def test_httpx_client_maps_network_errors():
    client = HttpxClient()
    with (
        patch.object(
            client._client, "request", AsyncMock(side_effect=httpx.ReadTimeout("timeout"))
        ),
        pytest.raises(NetworkError),
    ):
        await client.get("https://example.com")
    await client.aclose()


async def test_httpx_client_maps_connect_errors():
    client = HttpxClient()
    with (
        patch.object(
            client._client, "request", AsyncMock(side_effect=httpx.ConnectError("refused"))
        ),
        pytest.raises(ConnectError),
    ):
        await client.get("https://example.com")
    await client.aclose()


async def test_httpx_client_returns_response_wrapper():

    raw = httpx.Response(
        200, json={"ok": True}, request=httpx.Request("GET", "https://example.com")
    )
    client = HttpxClient()
    with patch.object(client._client, "request", AsyncMock(return_value=raw)):
        rep = await client.get("https://example.com")
    assert isinstance(rep, Response)
    assert rep.status_code == 200
    assert rep.json() == {"ok": True}
    await client.aclose()


async def test_httpx_client_maps_connect_timeout():

    client = HttpxClient()
    with (
        patch.object(
            client._client, "request", AsyncMock(side_effect=httpx.ConnectTimeout("timeout"))
        ),
        pytest.raises(ConnectError),
    ):
        await client.get("https://example.com")
    await client.aclose()


async def test_httpx_client_maps_write_and_pool_timeout():

    for exc_cls in (httpx.WriteTimeout, httpx.PoolTimeout, httpx.ProxyError):
        client = HttpxClient()
        with (
            patch.object(client._client, "request", AsyncMock(side_effect=exc_cls("err"))),
            pytest.raises(NetworkError),
        ):
            await client.get("https://example.com")
        await client.aclose()


# --- _detect_backend: missing paths ---


def test_detect_backend_ignores_installed_curl_by_default(monkeypatch):
    monkeypatch.delenv("TWS_HTTP_BACKEND", raising=False)
    result = _detect_backend()
    assert result == "httpx"


def test_detect_backend_env_curl_installed(monkeypatch):
    monkeypatch.setenv("TWS_HTTP_BACKEND", "curl")
    result = _detect_backend()
    assert result == "curl"


# --- make_client: missing paths ---


def test_make_client_curl_returns_curl_client():

    client = make_client("curl")
    assert isinstance(client, CurlClient)


def test_make_client_unknown_backend_raises():
    with pytest.raises(ValueError, match="Unknown backend"):
        make_client("unknown_backend")


def test_make_client_none_uses_default_httpx(monkeypatch):
    monkeypatch.delenv("TWS_HTTP_BACKEND", raising=False)

    client = make_client(None)
    assert isinstance(client, HttpxClient)


# --- CurlClient ---


async def test_curl_client_returns_response_wrapper():

    raw = MagicMock()
    raw.status_code = 200
    raw.text = "hello"
    raw.content = b"hello"
    raw.headers = {}
    raw.url = "https://example.com"
    raw.request = MagicMock()
    raw.json.return_value = {"ok": True}
    raw.raise_for_status.return_value = None

    client = CurlClient()
    with patch.object(client._session, "request", AsyncMock(return_value=raw)):
        rep = await client.get("https://example.com")

    assert isinstance(rep, Response)
    assert rep.status_code == 200
    assert rep.json() == {"ok": True}
    await client.aclose()


async def test_curl_client_connect_error_codes():

    for code in (CurlECode(5), CurlECode(6), CurlECode(7)):
        client = CurlClient()
        err = RequestsError("connect failed", code=code)
        with (
            patch.object(client._session, "request", AsyncMock(side_effect=err)),
            pytest.raises(ConnectError),
        ):
            await client.get("https://example.com")
        await client.aclose()


async def test_curl_client_network_error():
    client = CurlClient()
    err = RequestsError("operation timed out", code=CurlECode(28))

    with (
        patch.object(client._session, "request", AsyncMock(side_effect=err)),
        pytest.raises(NetworkError),
    ):
        await client.get("https://example.com")
    await client.aclose()


async def test_curl_client_cookies_and_headers():

    client = CurlClient(headers={"x-foo": "bar"}, cookies={"ct0": "token"})
    assert "ct0" in client.cookies
    assert client.headers is not None
    await client.aclose()


async def test_curl_client_retries_network_error():
    client = CurlClient()
    err = RequestsError("timeout", code=CurlECode(28))
    mock_req = AsyncMock(side_effect=err)
    with (
        patch.object(client._session, "request", mock_req),
        pytest.raises(NetworkError),
    ):
        await client.get("https://example.com")
    assert mock_req.call_count == _CURL_MAX_RETRIES + 1
    await client.aclose()


async def test_curl_client_non_curl_error_propagates():
    client = CurlClient()
    with (
        patch.object(client._session, "request", AsyncMock(side_effect=ValueError("unexpected"))),
        pytest.raises(ValueError),
    ):
        await client.get("https://example.com")
    await client.aclose()


# --- HttpClient.post ---


async def test_http_client_post_delegates_to_request():
    rep_mock = Response(_raw(status_code=201))

    class PostableClient(HttpClient):
        async def request(self, method, url, **kwargs):
            assert method == "POST"
            return rep_mock

        async def aclose(self):
            pass

        @property
        def cookies(self):
            return {}

        @property
        def headers(self):
            return {}

    client = PostableClient()
    result = await client.post("https://example.com", json={"x": 1})
    assert result is rep_mock


# --- Response: remaining properties ---


def test_response_content_and_headers():
    raw = _raw(status_code=200, text="body", headers={"x-custom": "val"})
    rep = Response(raw)
    assert rep.content == b"body"
    assert rep.headers == {"x-custom": "val"}
    assert rep.url == "https://mock.local"


def test_response_json_is_cached():
    raw = _raw(status_code=200, json_data={"x": 1})
    rep = Response(raw)
    _ = rep.json()
    _ = rep.json()
    assert raw.json.call_count == 1


# --- Browser resolution helpers ---


def test_resolve_browser_none_returns_chrome():
    ua, family = _resolve_browser(None)
    assert family == "chrome"
    assert len(ua) > 10


def test_resolve_browser_at_safari():
    ua, family = _resolve_browser("@safari")
    assert family == "safari"
    assert len(ua) > 10


def test_resolve_browser_at_firefox():
    ua, family = _resolve_browser("@firefox")
    assert family == "firefox"


def test_resolve_browser_at_edge():
    _, family = _resolve_browser("@edge")
    assert family == "edge"


def test_resolve_browser_unknown_at_hint_falls_back_to_chrome():
    _, family = _resolve_browser("@netscape")
    assert family == "chrome"


def test_resolve_browser_real_ua_passes_through():
    old_ua = "Mozilla/5.0 (Macintosh) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15"
    ua, family = _resolve_browser(old_ua)
    assert ua == old_ua
    assert family == "chrome"


# --- CurlClient: impersonate param and header safety ---


def test_curl_client_resolves_impersonate_from_ua_hint():
    client = CurlClient(headers={"user-agent": "@safari"})
    assert client._session.impersonate == "safari"


def test_curl_client_resolves_impersonate_from_real_ua():
    chrome_ua = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/136.0.0.0 Safari/537.36"
    client = CurlClient(headers={"user-agent": chrome_ua})
    assert client._session.impersonate == "chrome"


def test_curl_client_does_not_mutate_caller_headers():

    original = {"user-agent": "@chrome", "x-foo": "bar"}
    headers_copy = dict(original)
    CurlClient(headers=headers_copy)
    assert headers_copy == original  # caller's dict unchanged


def test_curl_client_strips_user_agent_from_session():

    client = CurlClient(headers={"user-agent": "@chrome", "x-foo": "bar"})
    session_headers = dict(client._session.headers)
    assert "user-agent" not in {k.lower() for k in session_headers}


def test_httpx_client_resolves_ua_hint_to_real_string():
    from twscrape.http import HttpxClient

    client = HttpxClient(headers={"user-agent": "@firefox"})
    ua = dict(client._client.headers).get("user-agent", "")
    assert "Firefox/" in ua
    assert "@" not in ua
