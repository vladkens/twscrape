from unittest.mock import MagicMock, patch

import pytest

from twscrape.http import (
    ConnectError,
    HttpClient,
    HttpError,
    HttpStatusError,
    NetworkError,
    Response,
    _CURL_MAX_RETRIES,
    _detect_backend,
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


async def test_httpx_client_maps_network_errors():
    from unittest.mock import AsyncMock, patch

    import httpx

    from twscrape.http import HttpxClient

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
    from unittest.mock import AsyncMock, patch

    import httpx

    from twscrape.http import HttpxClient

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
    from unittest.mock import AsyncMock, patch

    import httpx

    from twscrape.http import HttpxClient

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
    from unittest.mock import AsyncMock, patch

    import httpx

    from twscrape.http import HttpxClient

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
    from unittest.mock import AsyncMock, patch

    import httpx

    from twscrape.http import HttpxClient

    for exc_cls in (httpx.WriteTimeout, httpx.PoolTimeout, httpx.ProxyError):
        client = HttpxClient()
        with (
            patch.object(client._client, "request", AsyncMock(side_effect=exc_cls("err"))),
            pytest.raises(NetworkError),
        ):
            await client.get("https://example.com")
        await client.aclose()


# --- _detect_backend: missing paths ---


def test_detect_backend_auto_curl_preferred(monkeypatch):
    monkeypatch.delenv("TWS_HTTP_BACKEND", raising=False)
    # curl_cffi is installed in the dev env, so auto-detect should pick it
    result = _detect_backend()
    assert result == "curl"


def test_detect_backend_env_curl_installed(monkeypatch):
    monkeypatch.setenv("TWS_HTTP_BACKEND", "curl")
    result = _detect_backend()
    assert result == "curl"


# --- make_client: missing paths ---


def test_make_client_curl_returns_curl_client():
    from twscrape.http import CurlClient

    client = make_client("curl")
    assert isinstance(client, CurlClient)


def test_make_client_unknown_backend_raises():
    with pytest.raises(ValueError, match="Unknown backend"):
        make_client("unknown_backend")


def test_make_client_none_uses_auto_detect(monkeypatch):
    monkeypatch.delenv("TWS_HTTP_BACKEND", raising=False)
    from twscrape.http import CurlClient

    client = make_client(None)
    assert isinstance(client, CurlClient)


# --- CurlClient ---


async def test_curl_client_returns_response_wrapper():
    from unittest.mock import AsyncMock, MagicMock, patch

    from twscrape.http import CurlClient

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
    from unittest.mock import AsyncMock, patch

    from curl_cffi.const import CurlECode
    from curl_cffi.requests.errors import RequestsError

    from twscrape.http import CurlClient

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
    from unittest.mock import AsyncMock, patch

    from curl_cffi.const import CurlECode
    from curl_cffi.requests.errors import RequestsError

    from twscrape.http import CurlClient

    client = CurlClient()
    err = RequestsError("operation timed out", code=CurlECode(28))

    with (
        patch.object(client._session, "request", AsyncMock(side_effect=err)),
        pytest.raises(NetworkError),
    ):
        await client.get("https://example.com")
    await client.aclose()


async def test_curl_client_cookies_and_headers():
    from twscrape.http import CurlClient

    client = CurlClient(headers={"x-foo": "bar"}, cookies={"ct0": "token"})
    assert "ct0" in client.cookies
    assert client.headers is not None
    await client.aclose()


async def test_curl_client_retries_network_error():
    from unittest.mock import AsyncMock, patch

    from curl_cffi.const import CurlECode
    from curl_cffi.requests.errors import RequestsError

    from twscrape.http import CurlClient

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
    from unittest.mock import AsyncMock, patch

    from twscrape.http import CurlClient

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
