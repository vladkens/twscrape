from unittest.mock import MagicMock, patch

import pytest

from twscrape.http import (
    ConnectError,
    HttpClient,
    HttpError,
    HttpStatusError,
    NetworkError,
    Response,
    _detect_backend,
    make_client,
)


def _mock_response(status_code=200, text="ok", json_data=None, headers=None):
    rep = MagicMock()
    rep.status_code = status_code
    rep.text = text
    rep.content = text.encode()
    rep.headers = headers or {}
    rep.url = "https://example.com"
    rep.request = MagicMock()
    rep.request.method = "GET"
    rep.request.url = "https://example.com"
    rep.json.return_value = json_data or {}

    if status_code >= 400:
        rep.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        rep.raise_for_status.return_value = None

    return rep


# --- Response wrapper ---


def test_response_delegates_attributes():
    raw = _mock_response(200, "hello", {"key": "val"})
    rep = Response(raw)
    assert rep.status_code == 200
    assert rep.text == "hello"
    assert rep.json() == {"key": "val"}
    assert rep.request.method == "GET"


def test_response_raise_for_status_ok():
    rep = Response(_mock_response(200))
    rep.raise_for_status()  # should not raise


def test_response_raise_for_status_error():
    rep = Response(_mock_response(403))
    with pytest.raises(HttpStatusError) as exc_info:
        rep.raise_for_status()
    err = exc_info.value
    assert err.response is rep
    assert err.response.status_code == 403
    assert err.response.text == "ok"


def test_response_allows_setattr():
    rep = Response(_mock_response(200))
    setattr(rep, "__username", "alice")
    assert getattr(rep, "__username") == "alice"


# --- Exception hierarchy ---


def test_exception_hierarchy():
    assert issubclass(HttpStatusError, HttpError)
    assert issubclass(NetworkError, HttpError)
    assert issubclass(ConnectError, HttpError)


def test_http_status_error_carries_response():
    raw = _mock_response(500, "server error")
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


def test_detect_backend_auto_httpx(monkeypatch):
    monkeypatch.delenv("TWS_HTTP_BACKEND", raising=False)
    with patch.dict("sys.modules", {"curl_cffi": None}):
        result = _detect_backend()
        assert result == "httpx"


def test_detect_backend_no_backends(monkeypatch):
    monkeypatch.delenv("TWS_HTTP_BACKEND", raising=False)
    with (
        patch.dict("sys.modules", {"curl_cffi": None, "httpx": None}),
        pytest.raises(ImportError, match="No HTTP backend"),
    ):
        _detect_backend()


# --- HttpClient base ---


def test_http_client_is_async_context_manager():
    class MinimalClient(HttpClient):
        closed = False

        async def request(self, method, url, **kwargs):
            return Response(_mock_response())

        async def aclose(self):
            self.closed = True

        @property
        def cookies(self):
            return {}

        @property
        def headers(self):
            return {}

    import asyncio

    async def run():
        client = MinimalClient()
        async with client as c:
            assert c is client
        assert client.closed

    asyncio.get_event_loop().run_until_complete(run())


# --- HttpxClient ---


def test_make_client_httpx_returns_httpx_client(monkeypatch):
    monkeypatch.delenv("TWS_HTTP_BACKEND", raising=False)
    from twscrape.http import HttpxClient

    client = make_client("httpx")
    assert isinstance(client, HttpxClient)


async def test_httpx_client_cookies_and_headers_are_mutable():
    from twscrape.http import HttpxClient

    client = HttpxClient(headers={"x-foo": "bar"}, cookies={"ct0": "token"})
    # headers support __setitem__
    client.headers["x-new"] = "value"
    # cookies support __contains__
    assert "ct0" in client.cookies
    await client.aclose()


async def test_httpx_client_maps_network_errors(httpx_mock):
    import httpx

    from twscrape.http import HttpxClient

    httpx_mock.add_exception(httpx.ReadTimeout("timeout"))
    client = HttpxClient()
    with pytest.raises(NetworkError):
        await client.get("https://example.com")
    await client.aclose()


async def test_httpx_client_maps_connect_errors(httpx_mock):
    import httpx

    from twscrape.http import HttpxClient

    httpx_mock.add_exception(httpx.ConnectError("refused"))
    client = HttpxClient()
    with pytest.raises(ConnectError):
        await client.get("https://example.com")
    await client.aclose()


async def test_httpx_client_returns_response_wrapper(httpx_mock):
    from twscrape.http import HttpxClient

    httpx_mock.add_response(url="https://example.com", json={"ok": True}, status_code=200)
    client = HttpxClient()
    rep = await client.get("https://example.com")
    assert isinstance(rep, Response)
    assert rep.status_code == 200
    assert rep.json() == {"ok": True}
    await client.aclose()
