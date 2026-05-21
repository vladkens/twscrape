from unittest.mock import MagicMock

from twscrape.http import HttpClient, HttpMethod, Response


def _raw(*, status_code: int = 200, json_data=None, text: str = "", headers: dict | None = None):
    raw = MagicMock()
    raw.status_code = status_code
    raw.text = text
    raw.content = text.encode()
    raw.headers = headers or {}
    raw.url = "https://mock.local"
    raw.request = MagicMock()
    raw.request.method = "GET"
    raw.request.url = "https://mock.local"
    raw.json.return_value = json_data if json_data is not None else {}
    if status_code >= 400:
        raw.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        raw.raise_for_status.return_value = None
    return raw


class MockClient(HttpClient):
    def __init__(self):
        self._queue: list = []
        self._cookies: dict = {}
        self._headers: dict = {}

    def add_response(
        self,
        *,
        status_code: int = 200,
        json: dict | list | None = None,
        text: str = "",
        headers: dict | None = None,
    ) -> "MockClient":
        self._queue.append(("response", status_code, json, text, headers))
        return self

    def add_exception(self, exc: Exception) -> "MockClient":
        self._queue.append(("exc", exc))
        return self

    @property
    def cookies(self):
        return self._cookies

    @property
    def headers(self):
        return self._headers

    async def request(self, method: HttpMethod, url: str, **kwargs) -> Response:
        if not self._queue:
            raise RuntimeError("MockClient: no more queued responses")
        item = self._queue.pop(0)
        if item[0] == "exc":
            raise item[1]
        _, status_code, json_data, text, headers = item
        return Response(
            _raw(status_code=status_code, json_data=json_data, text=text, headers=headers)
        )

    async def aclose(self) -> None:
        pass
