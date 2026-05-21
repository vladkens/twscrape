# HTTP Backend Abstraction

## Overview

Add a thin HTTP client abstraction layer (`twscrape/http.py`) so twscrape can use either
`httpx` or `curl_cffi` as the HTTP backend. `curl_cffi` enables browser-level TLS fingerprint
spoofing (JA3/SNI), which bypasses Cloudflare bot detection that httpx fails against.

Both libraries become **optional** extras. Auto-detection picks `curl_cffi` if installed,
falls back to `httpx`. User can override with `TWS_HTTP_BACKEND=curl|httpx` env var.
If env var is set but the specified backend is not installed → `ImportError` immediately.

Existing users who have `httpx` installed see zero behavior change.

**Behavior change (intentional):** `WriteTimeout` and `PoolTimeout` previously fell through
to the "unknown error / 15 min timeout" path. After this change they map to `NetworkError`
and trigger silent retry with the same account — which is the correct behavior.

Reference: [issue #269](https://github.com/vladkens/twscrape/issues/269),
example impl: `delta-farmer/lib/http.py`.

## Context

- **Language/framework**: Python 3.10+, async throughout (no sync variants)
- **Relevant files**:
  - `twscrape/http.py` — new file (core of this task)
  - `twscrape/account.py` — `make_client()` creates `httpx.AsyncClient`
  - `twscrape/accounts_pool.py` — `from httpx import HTTPStatusError`; accesses `e.response.status_code` / `e.response.text`
  - `twscrape/queue_client.py` — wraps client, catches 5 httpx-specific exceptions
  - `twscrape/login.py` — uses `AsyncClient` + `Response`; mutates `client.headers` and reads `client.cookies` after construction
  - `twscrape/xclid.py` — creates its own `httpx.AsyncClient` for public page fetching
  - `twscrape/models.py`, `twscrape/api.py`, `twscrape/cli.py` — `httpx.Response` type annotations
  - `pyproject.toml` — `httpx>=0.26.0` in required `dependencies`
- **Test mocking**: `tests/test_queue_client.py` uses `pytest-httpx`/`HTTPXMock` — still works
  since `HttpxClient` wraps `httpx.AsyncClient` internally so `pytest-httpx` intercepts there

## Development Approach

- **Testing approach**: Regular (code first, then tests alongside)
- Complete each task fully before moving to the next
- Run `uv run pytest` after each task — all tests must pass before proceeding

## Solution Overview

Single new file `twscrape/http.py` contains everything:

```
HttpError
├── HttpStatusError(response: Response)  ← raise_for_status() failures; carries .response
├── NetworkError                          ← timeout, read/write/pool/proxy (retry silently)
└── ConnectError                          ← connection failures (retry 3x then raise)

Response                    ← thin wrapper; delegates to httpx.Response or curl_cffi.Response
                              overrides raise_for_status() → HttpStatusError(response=self)
                              no __slots__ (allows arbitrary setattr for __username)

HttpClient                  ← plain base class; async context manager
├── HttpxClient             ← wraps httpx.AsyncClient; maps httpx errors → common types
└── CurlClient              ← wraps curl_cffi.AsyncSession(impersonate="chrome")

_detect_backend()           ← reads TWS_HTTP_BACKEND; strict fail if set but not installed
make_client()               ← factory; calls _detect_backend() if backend=None
```

**HttpClient full API:**
```python
async def request(method, url, *, params=None, headers=None, json=None, data=None) -> Response
async def get(url, *, params=None, headers=None) -> Response
async def post(url, *, params=None, headers=None, json=None, data=None) -> Response
async def aclose() -> None
async def __aenter__(self) -> HttpClient
async def __aexit__(self, *args) -> None     # calls aclose()
@property cookies  # mutable dict-like: __contains__, __getitem__, __setitem__, .get(), .update(), .items()
@property headers  # mutable dict-like: __setitem__, .update()
```

**Error mapping:**

| httpx | → |
|---|---|
| `ReadTimeout, WriteTimeout, PoolTimeout, ProxyError` | `NetworkError` |
| `ConnectError, ConnectTimeout` | `ConnectError` |
| `raise_for_status()` → `HTTPStatusError` | `HttpStatusError` |

| curl_cffi | → |
|---|---|
| `errors.ConnectionError, errors.ConnectTimeout` | `ConnectError` |
| `errors.RequestsError` (base; covers Timeout, ProxyError, etc.) | `NetworkError` |
| `raise_for_status()` | `HttpStatusError` |

## Implementation Steps

---

### Task 1: Create `twscrape/http.py`

**Files:**
- Create: `twscrape/http.py`
- Create: `tests/test_http.py`

- [x] define exception hierarchy:
  - `HttpError(Exception)`
  - `HttpStatusError(HttpError)` with field `response: Response` (set in `__init__`)
  - `NetworkError(HttpError)`
  - `ConnectError(HttpError)`
- [x] define `Response` wrapper class (no `__slots__`):
  - properties: `status_code`, `text`, `headers`, `content`, `url`, `request`
  - method `json() -> Any` — delegates
  - method `raise_for_status()` — catches any exception from `self._rep.raise_for_status()`, raises `HttpStatusError(response=self)`
- [x] define `HttpClient` base class:
  - `async request(method, url, *, params, headers, json, data) -> Response`
  - `async get(url, **kwargs) -> Response`
  - `async post(url, **kwargs) -> Response`
  - `async aclose() -> None`
  - `async __aenter__ / __aexit__`
  - `@property cookies` — mutable dict-like
  - `@property headers` — mutable dict-like
- [x] define `HttpxClient(HttpClient)`:
  - import aliased: `from httpx import ConnectError as _HttpxConnectError` etc. to avoid name clash with project's `ConnectError`
  - wraps `httpx.AsyncClient(proxy=..., follow_redirects=True, transport=AsyncHTTPTransport(retries=3))`
  - `_wrap(coro)`: maps `ReadTimeout, WriteTimeout, PoolTimeout, ProxyError → NetworkError`; `ConnectError, ConnectTimeout → ConnectError`
  - `request()` returns `Response(raw_rep)`
- [x] define `CurlClient(HttpClient)`:
  - wraps `curl_cffi.requests.AsyncSession(impersonate="chrome", proxy=..., allow_redirects=True)`
  - `_wrap(coro)`: maps `errors.ConnectionError, errors.ConnectTimeout → ConnectError`; `errors.RequestsError → NetworkError`
  - `request()` returns `Response(raw_rep)`
  - `aclose()` calls `await self._session.close()`
- [x] define `_detect_backend() -> str`:
  - if `TWS_HTTP_BACKEND` set: attempt to import the named backend; raise `ImportError` with install hint if missing
  - else: try `import curl_cffi` → `"curl"`; try `import httpx` → `"httpx"`; else raise `ImportError`
- [x] define `make_client(backend=None, *, proxy=None, headers=None, cookies=None) -> HttpClient`
- [x] write `tests/test_http.py`:
  - `_detect_backend()` respects `TWS_HTTP_BACKEND`
  - `TWS_HTTP_BACKEND` set but backend not installed → `ImportError`
  - `Response.raise_for_status()` raises `HttpStatusError`; `err.response.status_code` and `err.response.text` are accessible
  - `Response` delegates `.status_code`, `.json()`, `.text`, `.headers`
  - `setattr(rep, "__username", "x"); assert getattr(rep, "__username") == "x"` (no `__slots__`)
  - `HttpxClient` is an async context manager
  - `HttpxClient.cookies` and `.headers` support `__setitem__` and `__contains__`
- [x] run `uv run pytest tests/test_http.py` — must pass

---

### Task 2: Update `account.py`

**Files:**
- Modify: `twscrape/account.py`

- [x] remove `from httpx import AsyncClient, AsyncHTTPTransport`
- [x] add `from .http import HttpClient, make_client as _make_http_client`
- [x] rewrite `make_client()` return type `HttpClient`; assemble all headers upfront:
  ```python
  headers = {**self.headers}
  headers["user-agent"] = self.user_agent
  headers["content-type"] = "application/json"
  headers["authorization"] = TOKEN
  headers["x-twitter-active-user"] = "yes"
  headers["x-twitter-client-language"] = "en"
  if "ct0" in self.cookies:
      headers["x-csrf-token"] = self.cookies["ct0"]
  return _make_http_client(proxy=proxy, headers=headers, cookies=self.cookies)
  ```
- [x] run `uv run pytest` — must pass

---

### Task 3: Update `queue_client.py`

**Files:**
- Modify: `twscrape/queue_client.py`

- [x] remove `import httpx` and `from httpx import AsyncClient, Response`
- [x] add `from .http import HttpClient, NetworkError, ConnectError, HttpStatusError, Response`
- [x] `Ctx.__init__`: `clt: AsyncClient` → `clt: HttpClient`
- [x] `Ctx.req()` / `QueueClient.get()` / `QueueClient.req()` return types: `Response | None`
- [x] in `_check_rep`: `except httpx.HTTPStatusError` → `except HttpStatusError`
- [x] in `QueueClient.req()`:
  ```python
  except NetworkError: continue
  except ConnectError as e:
      connection_retry += 1
      if connection_retry >= 3: raise e
  ```
- [x] run `uv run pytest` — must pass

---

### Task 4: Update `accounts_pool.py`

**Files:**
- Modify: `twscrape/accounts_pool.py`

- [x] remove `from httpx import HTTPStatusError`
- [x] add `from .http import HttpStatusError`
- [x] `except HTTPStatusError as e:` — unchanged; `e.response.status_code` and `e.response.text` work via `HttpStatusError.response`
- [x] run `uv run pytest` — must pass

---

### Task 5: Update `login.py`

**Files:**
- Modify: `twscrape/login.py`

- [x] remove `from httpx import AsyncClient, Response`
- [x] add `from .http import HttpClient, Response`
- [x] `TaskCtx.client: AsyncClient` → `TaskCtx.client: HttpClient`
- [x] all `Response` type annotations → `Response`
- [x] verify all `client.headers["..."] = ...` and `client.cookies.get(...)` calls still work (both backends expose mutable dict-like jars)
- [x] run `uv run pytest` — must pass

---

### Task 6: Update `xclid.py`

**Files:**
- Modify: `twscrape/xclid.py`

- [x] remove `import httpx`
- [x] add `from .http import HttpClient, make_client as _make_http_client`
- [x] `_make_client() -> HttpClient`: `return _make_http_client(headers={"user-agent": UserAgent().chrome})`
- [x] update all function signatures: `clt: httpx.AsyncClient` → `clt: HttpClient`
- [x] run `uv run pytest` — must pass

---

### Task 7: Update type annotations in `models.py`, `api.py`, `cli.py`

**Files:**
- Modify: `twscrape/models.py`
- Modify: `twscrape/api.py`
- Modify: `twscrape/cli.py`

- [x] `models.py`: remove `import httpx`; add `from .http import Response`; replace all `httpx.Response` with `Response` in parse_* signatures; update comment at line 811 removing httpx mention
- [x] `api.py`: remove `from httpx import Response`; add `from .http import Response`
- [x] `cli.py`: remove `import httpx`; add `from .http import Response`; update `to_str()` signature
- [x] fix `[tool.pyright]` in `pyproject.toml`: change `include` from non-existent dirs to `["twscrape"]`
- [ ] run `uv run pyright twscrape/` — no errors
- [x] run `uv run pytest` — must pass

---

### Task 8: Update `pyproject.toml`

**Files:**
- Modify: `pyproject.toml`

- [x] remove `httpx>=0.26.0` from `dependencies`
- [x] add optional extras:
  ```toml
  [project.optional-dependencies]
  httpx = ["httpx>=0.26.0"]
  curl = ["curl-cffi>=0.7.0"]
  ```
- [x] keep `pytest-httpx` in dev dependencies (still intercepts at httpx level inside `HttpxClient`)
- [x] run `uv run pytest` — must pass (httpx still installed in dev env via pytest-httpx)

---

### Task 9: Verify acceptance criteria

- [x] `uv run pytest` — all tests pass (73/73)
- [ ] `uv run pyright twscrape/` — no errors
- [x] `grep -r "import httpx" twscrape/` — returns empty (no direct httpx usage outside http.py)
- [ ] verify `TWS_HTTP_BACKEND=httpx` override works
- [ ] verify clean import: `python -c "from twscrape.http import Response, HttpClient, NetworkError, ConnectError, HttpStatusError"`

---

### Task 10: [Final] Update documentation

- [ ] update `readme.md`: add section on optional dependencies and backend selection
- [ ] add entry to `changelog.md`: httpx is now optional; install `twscrape[httpx]` or `twscrape[curl]`; `curl_cffi` backend preferred when installed
- [ ] move this plan to `docs/plans/completed/`

## Post-Completion

**Manual verification:**
- Test login flow with a real account using `curl_cffi` backend
- Verify TLS fingerprint via `tls.browserleaks.com` — should show Chrome profile
- Test `TWS_HTTP_BACKEND=httpx` override still works after curl_cffi is installed

**Isolation test** (to verify optional-deps work end to end):
```bash
uv venv /tmp/twscrape-curl-only
/tmp/twscrape-curl-only/bin/pip install -e ".[curl]"
/tmp/twscrape-curl-only/bin/python -c "import twscrape; print('ok')"
```

**Breaking change notice** (in release notes):
- `httpx` is no longer a required dependency — users must install `twscrape[httpx]` or `twscrape[curl]`
- Existing installs unaffected: httpx was installed before, auto-detect finds it
