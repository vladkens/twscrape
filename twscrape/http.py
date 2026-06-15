import importlib.util
import os
import random
from abc import ABC, abstractmethod
from typing import Any, Literal, cast

from fake_useragent import UserAgent

from .logger import logger

HttpMethod = Literal["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "TRACE", "PATCH"]

_UNSET = object()
_CURL_MAX_RETRIES = 3
_LOGGED_BACKENDS: set[str] = set()

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
    return getattr(_ua, family, _ua.chrome), family


class Response:
    """Thin wrapper around httpx.Response or curl_cffi.Response."""

    def __init__(self, rep: Any):
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


class HttpClient(ABC):
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
    def __init__(
        self,
        *,
        proxy: str | None = None,
        headers: dict | None = None,
        cookies: dict | None = None,
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
            cookies=cookies or {},
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


class CurlClient(HttpClient):
    def __init__(
        self, *, proxy: str | None = None, headers: dict | None = None, cookies: dict | None = None
    ):
        from curl_cffi.requests import AsyncSession, BrowserTypeLiteral

        _, family = _resolve_browser((headers or {}).get("user-agent"))
        # strip user-agent — curl_cffi sets its own UA for the impersonated profile
        safe_headers = {k: v for k, v in (headers or {}).items() if k.lower() != "user-agent"}
        self._session = AsyncSession(
            impersonate=cast(BrowserTypeLiteral, family),
            proxy=proxy,
            allow_redirects=True,
            headers=safe_headers,
        )
        if cookies:
            self._session.cookies.update(cookies)

    @property
    def cookies(self) -> Any:
        return self._session.cookies

    @property
    def headers(self) -> Any:
        return self._session.headers

    async def request(self, method: HttpMethod, url: str, **kwargs) -> Response:
        last_err: Exception | None = None
        for _ in range(_CURL_MAX_RETRIES + 1):
            try:
                return await self._wrap(self._session.request(method, url, **kwargs))
            except NetworkError as e:
                last_err = e
        if last_err is not None:
            raise last_err
        raise RuntimeError("CurlClient request failed without an error")

    async def aclose(self) -> None:
        await self._session.close()

    async def _wrap(self, coro: Any) -> Response:
        try:
            return Response(await coro)
        except Exception as e:
            from curl_cffi.requests import errors as _curl_errors

            if isinstance(e, _curl_errors.RequestsError):
                # libcurl error codes: 5=COULDNT_RESOLVE_PROXY, 6=COULDNT_RESOLVE_HOST, 7=COULDNT_CONNECT
                if getattr(e, "code", -1) in {5, 6, 7}:
                    raise ConnectError(str(e)) from e
                raise NetworkError(str(e)) from e
            raise


def _detect_backend() -> str:
    forced = os.getenv("TWS_HTTP_BACKEND", "").lower().strip()

    if forced == "curl":
        if importlib.util.find_spec("curl_cffi") is None:
            raise ImportError(
                "TWS_HTTP_BACKEND=curl but curl-cffi is not installed. "
                "Run: pip install twscrape[curl]"
            )
        return "curl"

    if forced in ("", "httpx"):
        if importlib.util.find_spec("httpx") is None:
            raise ImportError(
                "TWS_HTTP_BACKEND=httpx but httpx is not installed. Run: pip install twscrape"
            )
        return "httpx"

    if forced:
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

    if backend == "curl":
        return CurlClient(proxy=proxy, headers=headers, cookies=cookies)
    if backend == "httpx":
        return HttpxClient(proxy=proxy, headers=headers, cookies=cookies, seed=seed)

    raise ValueError(f"Unknown backend: {backend!r}. Expected 'curl' or 'httpx'.")
