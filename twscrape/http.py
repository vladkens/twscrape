import importlib.util
import os
from typing import Any, Literal

HttpMethod = Literal["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "TRACE", "PATCH", "QUERY"]


class Response:
    """Thin wrapper around httpx.Response or curl_cffi.Response."""

    def __init__(self, rep: Any):
        self._rep = rep

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
        return self._rep.json()

    def raise_for_status(self) -> None:
        try:
            self._rep.raise_for_status()
        except Exception as e:
            raise HttpStatusError(str(e), response=self) from e


class HttpError(Exception): ...


class NetworkError(HttpError): ...


class ConnectError(HttpError): ...


class HttpStatusError(HttpError):
    def __init__(self, message: str, *, response: Response):
        super().__init__(message)
        self.response = response


class HttpClient:
    async def request(self, method: HttpMethod, url: str, **kwargs) -> Response: ...

    async def get(self, url: str, **kwargs) -> Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> Response:
        return await self.request("POST", url, **kwargs)

    async def aclose(self) -> None: ...

    async def __aenter__(self) -> "HttpClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    @property
    def cookies(self) -> Any: ...

    @property
    def headers(self) -> Any: ...


class HttpxClient(HttpClient):
    def __init__(
        self, *, proxy: str | None = None, headers: dict | None = None, cookies: dict | None = None
    ):
        import httpx
        from httpx import AsyncHTTPTransport

        self._httpx = httpx
        transport = AsyncHTTPTransport(retries=3)
        self._client = httpx.AsyncClient(
            proxy=proxy,
            follow_redirects=True,
            transport=transport,
            headers=headers or {},
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
        from curl_cffi.requests import AsyncSession

        self._session = AsyncSession(
            impersonate="chrome", proxy=proxy, allow_redirects=True, headers=headers or {}
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
        return await self._wrap(self._session.request(method, url, **kwargs))

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

    if forced == "httpx":
        if importlib.util.find_spec("httpx") is None:
            raise ImportError(
                "TWS_HTTP_BACKEND=httpx but httpx is not installed. "
                "Run: pip install twscrape[httpx]"
            )
        return "httpx"

    if forced:
        raise ValueError(f"Invalid TWS_HTTP_BACKEND={forced!r}. Expected 'curl' or 'httpx'.")

    if importlib.util.find_spec("curl_cffi") is not None:
        return "curl"
    if importlib.util.find_spec("httpx") is not None:
        return "httpx"

    raise ImportError(
        "No HTTP backend installed. Run: pip install twscrape[httpx] or pip install twscrape[curl]"
    )


def make_client(
    backend: str | None = None,
    *,
    proxy: str | None = None,
    headers: dict | None = None,
    cookies: dict | None = None,
) -> HttpClient:
    if backend is None:
        backend = _detect_backend()

    if backend == "curl":
        return CurlClient(proxy=proxy, headers=headers, cookies=cookies)
    if backend == "httpx":
        return HttpxClient(proxy=proxy, headers=headers, cookies=cookies)

    raise ValueError(f"Unknown backend: {backend!r}. Expected 'curl' or 'httpx'.")
