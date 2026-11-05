from abc import ABC, abstractmethod
from typing import Any, Literal, Protocol, cast

from curl_cffi.requests import AsyncSession, BrowserTypeLiteral
from curl_cffi.requests.errors import RequestsError
from fake_useragent import UserAgent

HttpMethod = Literal["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "TRACE", "PATCH"]

_UNSET = object()
_CURL_MAX_RETRIES = 3
_COOKIE_DOMAIN = ".x.com"

# https://curl-impersonate.readthedocs.io/en/latest/fingerprints.html
_BROWSER_FAMILIES = {"chrome", "safari", "firefox", "edge"}

_ua = UserAgent()


def _resolve_browser(hint: str | None) -> tuple[str, str]:
    """Return (ua_string, family) for a @hint or a real UA string."""
    if hint and not hint.startswith("@"):
        return hint, "chrome"
    family = hint[1:].lower() if hint else "chrome"
    if family not in _BROWSER_FAMILIES:
        family = "chrome"
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
    """Thin wrapper around curl_cffi.Response."""

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


class CurlClient(HttpClient):
    backend = "curl"

    def __init__(
        self, *, proxy: str | None = None, headers: dict | None = None, cookies: dict | None = None
    ):
        _, family = _resolve_browser((headers or {}).get("user-agent"))
        # strip user-agent — curl_cffi sets its own UA for the impersonated profile
        safe_headers = {k: v for k, v in (headers or {}).items() if k.lower() != "user-agent"}
        self._session = AsyncSession(
            impersonate=cast(BrowserTypeLiteral, family),
            proxy=proxy,
            allow_redirects=True,
            headers=safe_headers,
        )

        # Without a domain curl_cffi sends a cookie to any host, and one set by X later doesn't
        # replace it: both are sent. Asset hosts like abs.twimg.com must not get auth cookies.
        for name, value in (cookies or {}).items():
            self._session.cookies.set(name, value, domain=_COOKIE_DOMAIN)

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
        except RequestsError as e:
            # libcurl error codes: 5=COULDNT_RESOLVE_PROXY, 6=COULDNT_RESOLVE_HOST, 7=COULDNT_CONNECT
            if e.code in {5, 6, 7}:
                raise ConnectError(str(e)) from e
            raise NetworkError(str(e)) from e


def make_client(
    *, proxy: str | None = None, headers: dict | None = None, cookies: dict | None = None
) -> HttpClient:
    return CurlClient(proxy=proxy, headers=headers, cookies=cookies)
