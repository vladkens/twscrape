import asyncio
import os
import random
from abc import ABC, abstractmethod
from typing import Any, Literal, Protocol, cast

from curl_cffi.const import CurlECode
from curl_cffi.requests import AsyncSession, BrowserTypeLiteral
from curl_cffi.requests.errors import RequestsError
from fake_useragent import UserAgent

from .logger import logger

HttpMethod = Literal["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "TRACE", "PATCH"]

_UNSET = object()
_CURL_MAX_RETRIES = 3
_CURL_RETRY_DELAY = 0.5  # seconds, grows with each attempt
_LOGGED_BACKENDS: set[str] = set()
_CURL_CONNECT_CODES = {
    CurlECode.COULDNT_RESOLVE_PROXY,
    CurlECode.COULDNT_RESOLVE_HOST,
    CurlECode.COULDNT_CONNECT,
    CurlECode.SSL_CONNECT_ERROR,
    CurlECode.PEER_FAILED_VERIFICATION,
}
_BROWSER_PROFILE_HEADERS = {"user-agent", "accept", "accept-encoding", "connection"}

# https://curl-impersonate.readthedocs.io/en/latest/fingerprints.html
_BROWSER_FAMILIES = {"chrome", "safari", "firefox", "edge"}

_ua = UserAgent()


def _resolve_browser(hint: str | None, seed: int | None = None) -> tuple[str, str]:
    """Return (ua_string, family) for a @hint or a real UA string."""
    if hint and not hint.startswith("@"):
        return hint, "chrome"
    family = hint[1:].lower() if hint else "chrome"
    if family not in _BROWSER_FAMILIES:
        family = "chrome"
    if seed is not None:
        uas = [x["useragent"] for x in _ua.data_browsers if family in (x["browser"] or "").lower()]
        if uas:
            return random.Random(seed).choice(uas), family
    return cast(str, getattr(_ua, family, _ua.chrome)), family


class _RawResponse(Protocol):
    status_code: int
    text: str
    content: bytes
    headers: Any
    url: Any
    request: Any

    def json(self) -> Any: ...


class Response:
    """Thin wrapper around httpx.Response or curl_cffi.Response."""

    def __init__(self, rep: _RawResponse):
        self._rep = rep
        self._json: Any = _UNSET

    @property
    def status_code(self) -> int:
        return self._rep.status_code

    @property
    def text(self) -> str:
        return self._rep.text

    @property
    def content(self) -> bytes:
        return self._rep.content

    @property
    def headers(self) -> Any:
        return self._rep.headers

    @property
    def url(self) -> Any:
        return self._rep.url

    @property
    def request(self) -> Any:
        return self._rep.request

    def json(self) -> Any:
        if self._json is _UNSET:
            self._json = self._rep.json()
        return self._json

    def raise_for_status(self) -> None:
        if self._rep.status_code >= 400:
            raise HttpStatusError(f"HTTP {self._rep.status_code}", response=self)


class HttpError(Exception): ...


class NetworkError(HttpError): ...


class ConnectError(HttpError): ...


class HttpStatusError(HttpError):
    def __init__(self, message: str, *, response: Response):
        super().__init__(message)
        self.response = response


def format_error(error: Exception) -> str:
    name = type(error).__name__
    if isinstance(error, HttpStatusError):
        return f"{name} {error.response.status_code}"
    if isinstance(error, HttpError):
        return name
    return f"{name}: {error}"


class HttpClient(ABC):
    backend: str

    @abstractmethod
    async def request(self, method: HttpMethod, url: str, **kwargs) -> Response: ...

    async def get(self, url: str, **kwargs) -> Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> Response:
        return await self.request("POST", url, **kwargs)

    @abstractmethod
    async def aclose(self) -> None: ...

    async def __aenter__(self) -> "HttpClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    @property
    @abstractmethod
    def cookies(self) -> Any: ...

    @property
    @abstractmethod
    def headers(self) -> Any: ...


class HttpxClient(HttpClient):
    backend = "httpx"

    def __init__(
        self,
        *,
        proxy: str | None = None,
        headers: dict | None = None,
        seed: int | None = None,
    ):
        import httpx
        from httpx import AsyncHTTPTransport

        self._httpx = httpx
        transport = AsyncHTTPTransport(retries=3)
        resolved_headers = dict(headers or {})
        ua_string, _ = _resolve_browser(resolved_headers.get("user-agent"), seed=seed)
        resolved_headers["user-agent"] = ua_string
        self._client = httpx.AsyncClient(
            proxy=proxy,
            follow_redirects=True,
            transport=transport,
            headers=resolved_headers,
        )

    @property
    def cookies(self) -> Any:
        return self._client.cookies

    @property
    def headers(self) -> Any:
        return self._client.headers

    async def request(self, method: HttpMethod, url: str, **kwargs) -> Response:
        return await self._wrap(self._client.request(method, url, **kwargs))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _wrap(self, coro: Any) -> Response:
        hx = self._httpx
        try:
            return Response(await coro)
        except (hx.ConnectError, hx.ConnectTimeout) as e:
            raise ConnectError(str(e)) from e
        except (hx.ReadTimeout, hx.WriteTimeout, hx.PoolTimeout, hx.ProxyError) as e:
            raise NetworkError(str(e)) from e


def _resolve_dns_on_proxy(proxy: str | None) -> str | None:
    if proxy and proxy.startswith("socks5://"):
        return proxy.replace("socks5://", "socks5h://", 1)

    return proxy


class CurlClient(HttpClient):
    backend = "curl"

    def __init__(self, *, proxy: str | None = None, headers: dict | None = None):
        _, family = _resolve_browser((headers or {}).get("user-agent"))
        safe_headers = {
            k: v for k, v in (headers or {}).items() if k.lower() not in _BROWSER_PROFILE_HEADERS
        }
        self._session = AsyncSession(
            impersonate=cast(BrowserTypeLiteral, family),
            proxy=_resolve_dns_on_proxy(proxy),
            allow_redirects=True,
            headers=safe_headers,
        )

    @property
    def cookies(self) -> Any:
        return self._session.cookies

    @property
    def headers(self) -> Any:
        return self._session.headers

    async def request(self, method: HttpMethod, url: str, **kwargs) -> Response:
        for attempt in range(_CURL_MAX_RETRIES):
            try:
                return await self._wrap(self._session.request(method, url, **kwargs))
            except ConnectError:
                await asyncio.sleep(_CURL_RETRY_DELAY * attempt)

        return await self._wrap(self._session.request(method, url, **kwargs))

    async def aclose(self) -> None:
        await self._session.close()

    async def _wrap(self, coro: Any) -> Response:
        try:
            return Response(await coro)
        except RequestsError as e:
            if e.code in _CURL_CONNECT_CODES:
                raise ConnectError(str(e)) from e

            if e.code:
                raise NetworkError(str(e)) from e

            raise


def _detect_backend() -> str:
    forced = os.getenv("TWS_HTTP_BACKEND", "").lower().strip()

    if forced in ("", "curl"):
        return "curl"

    if forced == "httpx":
        return "httpx"

    raise ValueError(f"Invalid TWS_HTTP_BACKEND={forced!r}. Expected 'curl' or 'httpx'.")


def make_client(
    backend: str | None = None,
    *,
    proxy: str | None = None,
    headers: dict | None = None,
    cookies: dict | None = None,
    seed: int | None = None,
) -> HttpClient:
    if backend is None:
        backend = _detect_backend()

    if backend not in _LOGGED_BACKENDS:
        name = "curl-cffi" if backend == "curl" else backend
        logger.debug(f"Using {name} HTTP client")
        _LOGGED_BACKENDS.add(backend)

    client: HttpClient
    if backend == "curl":
        client = CurlClient(proxy=proxy, headers=headers)
    elif backend == "httpx":
        client = HttpxClient(proxy=proxy, headers=headers, seed=seed)
    else:
        raise ValueError(f"Unknown backend: {backend!r}. Expected 'curl' or 'httpx'.")

    for name, value in (cookies or {}).items():
        client.cookies.set(name, value, domain=".x.com")

    return client
