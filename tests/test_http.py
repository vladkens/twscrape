from unittest.mock import AsyncMock, MagicMock, patch

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
    NetworkError,
    Response,
    _resolve_browser,
    format_error,
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
    assert rep.request is not None
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


def test_format_error():
    response = Response(_raw(status_code=503))

    assert format_error(HttpStatusError("HTTP 503", response=response)) == "HttpStatusError 503"
    assert format_error(NetworkError("proxy credentials")) == "NetworkError"
    assert format_error(ValueError("invalid value")) == "ValueError: invalid value"


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


# --- make_client ---


def test_make_client_returns_curl_client():
    assert isinstance(make_client(), CurlClient)


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


@pytest.mark.parametrize("code", [5, 6, 7, 35, 60])
async def test_curl_client_connect_error_codes(code):
    client = CurlClient()
    err = RequestsError("connect failed", code=CurlECode(code))
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


async def test_curl_client_retries_connect_error():
    client = CurlClient()
    err = RequestsError("refused", code=CurlECode(7))
    mock_req = AsyncMock(side_effect=err)
    with (
        patch.object(client._session, "request", mock_req),
        pytest.raises(ConnectError),
    ):
        await client.post("https://example.com")
    assert mock_req.call_count == _CURL_MAX_RETRIES + 1
    await client.aclose()


async def test_curl_client_does_not_retry_network_error():
    client = CurlClient()
    err = RequestsError("timeout", code=CurlECode(28))
    mock_req = AsyncMock(side_effect=err)
    with (
        patch.object(client._session, "request", mock_req),
        pytest.raises(NetworkError),
    ):
        await client.get("https://example.com")
    assert mock_req.call_count == 1
    await client.aclose()


async def test_curl_client_error_without_curl_code_propagates():
    client = CurlClient()
    with (
        patch.object(client._session, "request", AsyncMock(side_effect=RequestsError("bad"))),
        pytest.raises(RequestsError),
    ):
        await client.get("https://example.com")
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
