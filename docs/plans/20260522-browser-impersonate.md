# Browser Impersonate & UA Resolution

## Overview

Replace `fake_useragent` dependency and hardcoded `impersonate="chrome"` (not a valid
`BrowserType` value) with a `_resolve_browser(hint)` function that maps meta-strings
(`"@chrome"`, `"@safari"`, `"@firefox"`, `"@edge"`) or real UA strings to a
`(ua_string, impersonate_profile)` pair.

**Problem it solves:**
- `fake_useragent` is deprecated and will be removed
- `impersonate="chrome"` is not a valid `BrowserType` value — could silently break
- Safari UA (from `fake_useragent`) + Chrome TLS fingerprint = bot-detection red flag
- No way to control the browser profile without patching source

**Key benefits:**
- `_latest_profile(family)` queries `BrowserType` at runtime → new curl_cffi versions auto-picked
- Both backends use consistent browser identity
- `fake_useragent` removed from all source files and `pyproject.toml`
- Accounts get a stable `"@chrome"` / `"@safari"` etc. stored in DB at creation time

## Context (from discovery)

- **Files involved:** `twscrape/http.py`, `twscrape/account.py`, `twscrape/accounts_pool.py`,
  `twscrape/xclid.py`, `pyproject.toml`, `tests/test_http.py`
- **`fake_useragent` used in:**
  - `accounts_pool.py:7` — import; `line 96` — `UserAgent().safari` in `add_account` default;
    `line 213` — `UserAgent().safari` inlined in raw SQL inside `relogin`
  - `xclid.py:10` — import; `line 17` — `UserAgent().chrome` in `_make_client`
- **curl_cffi 0.11.4 `BrowserType` desktop profiles:** `chrome99`…`chrome136` (note `chrome133a`
  variant), `firefox133`, `firefox135`, `safari15_3`, `safari15_5`, `safari17_0`, `safari18_0`,
  `edge99`, `edge101`; excluded: `*_android`, `*_ios`, `tor145`

## Development Approach

- **Testing approach:** Regular (code → tests)
- Complete each task fully before moving to the next; all tests must pass

## Solution Overview

**Single resolution point:** `Account.make_client()` and `xclid._make_client()` call
`_resolve_browser(hint)` and pass already-resolved values to `make_client()`.
`CurlClient` and `HttpxClient` receive final values; no resolution inside constructors.

```
hint: "@chrome" | "@safari" | "@firefox" | "@edge" | real-UA-string
  └→ family: "chrome" | "safari" | "firefox" | "edge"
       ├─ _latest_profile(family)  → impersonate_profile  (e.g. "chrome136")
       └─ _ua_for_profile(profile) → ua_string
```

`_pick_browser_hint()` (used by `add_account` default): random family by weight
`[chrome 60%, safari 20%, firefox 15%, edge 5%]`, returns `"@chrome"` etc. — called once at
account creation so each account has a **stable** browser identity in the DB.

**HttpxClient:** receives `headers` with resolved `ua_string`; `impersonate` dropped in
`make_client()` — not passed to `HttpxClient` at all.

**CurlClient:** receives `impersonate` profile directly; `user-agent` key stripped from headers
copy (not mutating caller dict) so curl_cffi sets its own matching UA automatically.

## Technical Details

```python
_BROWSER_FAMILIES = {"chrome", "safari", "firefox", "edge"}

_BROWSER_WEIGHTS = [("chrome", 60), ("safari", 20), ("firefox", 15), ("edge", 5)]

def _pick_browser_hint() -> str:
    """Return a random "@<family>" hint using browser market-share weights."""
    import random
    families, weights = zip(*_BROWSER_WEIGHTS)
    return "@" + random.choices(families, weights=weights)[0]

def _latest_profile(family: str) -> str:
    """Find the highest-versioned desktop BrowserType entry for family.
    
    Uses strict allow-list regex ^<family>\\d+(_\\d+)?$ to reject:
    - chrome133a (alpha/beta suffix)
    - chrome131_android, safari17_2_ios (mobile)
    - tor145 (different family)
    """
    import re
    from curl_cffi.requests import BrowserType
    pattern = re.compile(rf"^{family}\d+(_\d+)?$")
    candidates = [name for name in dir(BrowserType) if pattern.match(name)]
    if not candidates:
        raise ValueError(f"No BrowserType entry found for family {family!r}")
    # sort by numeric components: safari18_0 > safari17_0 > safari15_5
    candidates.sort(key=lambda s: [int(x) for x in re.findall(r"\d+", s)])
    return candidates[-1]

# UA templates — version number extracted from profile name and injected.
# Platform: Windows for Chrome/Firefox/Edge, macOS for Safari.
def _ua_for_profile(profile: str) -> str:
    """Return a matching User-Agent string for the given impersonate profile.
    
    profile examples: "chrome136", "safari18_0", "firefox135", "edge101"
    """
    import re
    nums = re.findall(r"\d+", profile)
    major = nums[0]  # e.g. "136" from "chrome136", "18" from "safari18_0"
    if profile.startswith("chrome"):
        return (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                f"AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{major}.0.0.0 Safari/537.36")
    if profile.startswith("edge"):
        return (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                f"AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{major}.0.0.0 Safari/537.36 Edg/{major}.0.0.0")
    if profile.startswith("firefox"):
        return (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{major}.0) "
                f"Gecko/20100101 Firefox/{major}.0")
    if profile.startswith("safari"):
        minor = nums[1] if len(nums) > 1 else "0"
        wk = "605.1.15"
        return (f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                f"AppleWebKit/{wk} (KHTML, like Gecko) "
                f"Version/{major}.{minor} Safari/{wk}")
    raise ValueError(f"Unknown profile {profile!r}")

# Family detection from a real UA string (for existing DB rows with fake_useragent UA).
# Order matters: check Edge before Chrome (Edge UA contains "Chrome/").
_UA_FAMILY_RULES = [
    ("Edg/",     "edge"),
    ("Firefox/", "firefox"),
    ("Chrome/",  "chrome"),
    ("Safari/",  "safari"),   # Safari UA does NOT contain "Chrome/"
]

def _detect_family(ua: str) -> str:
    for marker, family in _UA_FAMILY_RULES:
        if marker in ua:
            return family
    return "chrome"  # fallback

def _resolve_browser(hint: str | None) -> tuple[str, str]:
    """Return (ua_string, impersonate_profile) for the given hint.
    
    hint=None or "@chrome"/"@safari"/"@firefox"/"@edge" → use that family.
    hint=real UA string → detect family, use latest profile for it.
    Unknown "@xxx" hint → fallback to "@chrome".
    """
    if hint is None:
        hint = "@chrome"
    if hint.startswith("@"):
        family = hint[1:].lower()
        if family not in _BROWSER_FAMILIES:
            family = "chrome"
    else:
        family = _detect_family(hint)
    profile = _latest_profile(family)
    ua = _ua_for_profile(profile)
    return ua, profile
```

`make_client()` updated signature:
```python
def make_client(backend=None, *, proxy=None, headers=None, cookies=None,
                impersonate: str | None = None) -> HttpClient:
    ...
    if backend == "curl":
        return CurlClient(proxy=proxy, headers=headers, cookies=cookies,
                          impersonate=impersonate)
    if backend == "httpx":
        # impersonate silently dropped; httpx has no TLS fingerprinting
        return HttpxClient(proxy=proxy, headers=headers, cookies=cookies)
```

`CurlClient.__init__` strips `user-agent` from a **copy** of headers:
```python
safe_headers = {k: v for k, v in (headers or {}).items()
                if k.lower() != "user-agent"}
self._session = AsyncSession(
    impersonate=impersonate, proxy=proxy, allow_redirects=True,
    headers=safe_headers,
)
```

## What Goes Where

**Implementation Steps** — all code changes and their tests.

**Post-Completion** — real login flow verification with accounts carrying old
`fake_useragent`-generated UA strings already in the DB.

## Implementation Steps

### Task 1: Core helpers in `http.py`

**Files:**
- Modify: `twscrape/http.py`
- Modify: `tests/test_http.py`

- [ ] add `_BROWSER_FAMILIES`, `_BROWSER_WEIGHTS`, `_UA_FAMILY_RULES` constants
- [ ] implement `_pick_browser_hint()` using `random.choices`
- [ ] implement `_latest_profile(family)` with strict allow-list regex (see Technical Details)
- [ ] implement `_ua_for_profile(profile)` with template per family (see Technical Details)
- [ ] implement `_detect_family(ua)` using `_UA_FAMILY_RULES` ordered detection
- [ ] implement `_resolve_browser(hint)` composing the above
- [ ] add `impersonate: str | None = None` to `make_client()` signature; pass to `CurlClient`;
  silently drop for `HttpxClient`
- [ ] tests: `_latest_profile("chrome")` returns a `chrome*` member of `BrowserType`
- [ ] tests: `_latest_profile("safari")` returns `safari18_0` (current latest desktop)
- [ ] tests: `_latest_profile` excludes `chrome133a`, `chrome131_android`, `safari17_2_ios`
- [ ] tests: `_ua_for_profile` produces correct UA for chrome, safari, firefox, edge profiles
- [ ] tests: `_detect_family` correctly identifies Edge/Firefox/Chrome/Safari + fallback
- [ ] tests: `_resolve_browser` for all hint variants (None, @chrome, @safari, real UA, unknown @hint)
- [ ] tests: `_pick_browser_hint` with monkeypatched `random.choices` returns `"@<family>"` form
- [ ] run tests — must pass before task 2

### Task 2: Update `CurlClient` to use `impersonate` param

**Files:**
- Modify: `twscrape/http.py`
- Modify: `tests/test_http.py`

- [ ] add `impersonate: str | None = None` to `CurlClient.__init__`
- [ ] strip `user-agent` from a copy of `headers` (do not mutate caller's dict)
- [ ] pass `impersonate` to `AsyncSession(impersonate=impersonate, ...)`
- [ ] remove `_CURL_IMPERSONATE` constant usage (already replaced in Task 1)
- [ ] update existing `test_curl_client_*` tests to pass an explicit `impersonate` or verify
  the existing auto-resolution path no longer lives in `CurlClient`
- [ ] test: `CurlClient(impersonate="chrome136")` passes `"chrome136"` to `AsyncSession`
- [ ] test: headers dict passed to `CurlClient` with `user-agent` key is not mutated by caller
- [ ] run tests — must pass before task 3

### Task 3: Update `Account.make_client()` — resolution entry point

**Files:**
- Modify: `twscrape/account.py`
- Modify: `tests/test_http.py` or `tests/test_queue_client.py`

- [ ] import `_resolve_browser` from `.http`
- [ ] call `ua_string, impersonate = _resolve_browser(self.user_agent)` at top of `make_client`
- [ ] set `headers["user-agent"] = ua_string` (for httpx backend to use)
- [ ] pass `impersonate=impersonate` to `_make_http_client(...)`
- [ ] test: account with `user_agent="@safari"` → `make_client` creates a `CurlClient` with
  `impersonate` matching `safari*`
- [ ] test: account with `user_agent="@chrome"` → `HttpxClient` headers contain a Chrome UA string
- [ ] test: account with old `fake_useragent`-style Safari UA string → resolves to `safari*` profile
- [ ] run tests — must pass before task 4

### Task 4: Update `AccountsPool` — remove `fake_useragent`

**Files:**
- Modify: `twscrape/accounts_pool.py`

- [ ] import `_pick_browser_hint` from `.http`
- [ ] in `add_account`: replace `user_agent or UserAgent().safari` with
  `user_agent or _pick_browser_hint()`
- [ ] in `relogin` SQL (line 213): replace `"{UserAgent().safari}"` with `"@chrome"`
  (reset accounts to explicit Chrome; no runtime call inside SQL string)
- [ ] remove `from fake_useragent import UserAgent` from `accounts_pool.py`
- [ ] test: `add_account(user_agent=None)` stores a `"@<family>"` meta-string (not a real UA)
- [ ] test: `add_account(user_agent="@safari")` stores `"@safari"` verbatim
- [ ] run tests — must pass before task 5

### Task 5: Update `xclid.py` and remove `fake_useragent` dependency

**Files:**
- Modify: `twscrape/xclid.py`
- Modify: `pyproject.toml`

- [ ] replace `headers={"user-agent": UserAgent().chrome}` in `xclid._make_client()` with
  `headers={"user-agent": "@chrome"}` — preserves explicit Chrome intent
- [ ] remove `from fake_useragent import UserAgent` from `xclid.py`
- [ ] remove `fake-useragent>=1.4.0` from `dependencies` in `pyproject.toml`
- [ ] run `uv sync` to verify dependency graph is clean
- [ ] verify: `grep -r fake_useragent .` (excluding `.venv`) returns no matches
- [ ] run full test suite — must pass

### Task 6: Verify acceptance criteria

- [ ] `_latest_profile("chrome")` returns the highest-versioned `chrome\d+` entry in current curl_cffi
- [ ] `"@safari"` → `CurlClient` impersonates a `safari*` profile; `HttpxClient` headers contain Safari UA
- [ ] real Chrome UA → both clients resolve to `chrome*` profile / Chrome UA
- [ ] `add_account(user_agent=None)` stores `"@<family>"`, not a real UA string
- [ ] no `fake_useragent` import anywhere in `twscrape/`
- [ ] run `uv run pytest` — all tests pass

### Task 7: [Final] Tidy up

- [ ] document `@<family>` meta-string convention in `CLAUDE.md`
- [ ] move this plan to `docs/plans/completed/`

## Post-Completion

**Manual verification:**
- Run a real login/request flow with an account that has an old `fake_useragent`-generated UA
  string in the DB (e.g. `"Mozilla/5.0 ... Safari/605.1.15 ..."`); confirm `_resolve_browser`
  falls back correctly and the request succeeds
- Confirm with debug logging that `CurlClient` sends the correct UA for its impersonated profile
  (not any `@chrome` literal or old Safari string)
