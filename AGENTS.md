# AGENTS.md — twscrape (intelogroup fork)

This fork adds cookie-handling fixes on top of upstream `vladkens/twscrape`.
If you're an agent wiring this into a project, read this first — it covers
the exact failure modes that cost real debugging time before these fixes
existed.

## Getting an account working, fastest path

```bash
pip install "twscrape[curl,browser]"
twscrape --db path/to/accounts.db add_cookie_local <local_username> --browser chrome
```

Requires the operator already logged into x.com in that browser. This reads
`auth_token`/`ct0` straight from the browser's local cookie store — no
scripted login, no new browser window, no bot-detection surface. Do **not**
try to automate the X login flow with Playwright/Selenium/CDP — X
fingerprints `navigator.webdriver` and blocks it; this is why
`add_cookie_local` exists instead of a headless-login flow.

Check the account actually worked before doing anything else:

```python
from twscrape import API
api = API("path/to/accounts.db")
accs = await api.pool.get_all()
for a in accs:
    assert a.active, a.error_msg  # error_msg is human-readable and specific
```

`add_cookie`/`add_cookie_local` both validate live against X on add — if
`active` is `False`, `error_msg` tells you why immediately (e.g. `"Logged-out
X web app"` means the cookies are stale/mismatched — most often caused by
copying `auth_token` and `ct0` at different moments, or from the wrong
cookie domain). Don't wait for a real scrape to discover this.

## Manual cookie format (if `add_cookie_local` isn't available)

`twscrape add_cookie <username>` prompts for a cookie string. It must be:
- **One line**, both values present
- Literal key names included: `auth_token=<value>; ct0=<value>`
- Not just the raw values — `<value1>;<value2>` alone will fail with
  `Invalid cookie value`

## CLI command names

`del_accounts`/`del_account` and `add_cookie`/`add_cookies` both work
(singular/plural aliases). If a command errors with "invalid choice", check
`twscrape --help` for the exact current command list rather than guessing.

## Rate limits (real numbers, per account, per endpoint — observed live, may drift)

| Endpoint | Limit | Window |
|---|---|---|
| `search` | ~50 requests | 15 min |
| `user_by_login` / `user_by_id` | ~150 requests | 15 min |
| `followers` / `following` | ~50 requests | 15 min |

twscrape reads these from X's own `x-rate-limit-*` response headers per
request and auto-locks an account for that specific endpoint until reset,
rotating to another active account if the pool has one — no manual backoff
needed. With a single account, budget calls under the ceiling above; X does
not publish these numbers officially and they can change.

## Don't

- Don't attempt automated/scripted login (Playwright, Selenium, raw CDP) —
  gets blocked, wastes time, `add_cookie_local` solves the same problem
  without triggering bot detection.
- Don't assume `active=True` at add time means the account is genuinely
  usable if you bypass the built-in validation (e.g. inserting rows into
  the accounts DB directly) — the validation only runs through
  `add_account_cookies()`.
- Don't hardcode the rate-limit numbers above into retry logic — read the
  live headers via twscrape's own account-lock behavior instead; the table
  is for capacity planning, not a guaranteed contract from X.
