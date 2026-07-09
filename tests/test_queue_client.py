from contextlib import aclosing

import pytest

from twscrape.account import Account
from twscrape.accounts_pool import AccountsPool
from twscrape.http import ConnectError, NetworkError
from twscrape.queue_client import QueueClient, XClIdGenStore
from twscrape.utils import utc

from .mock_http import MockClient

URL = "https://example.com/api"
CF = tuple[AccountsPool, QueueClient, MockClient]


async def get_locked(pool: AccountsPool) -> set[str]:
    rep = await pool.get_all()
    return {x.username for x in rep if x.locks.get("SearchTimeline", None) is not None}


async def get_inactive(pool: AccountsPool) -> set[str]:
    rep = await pool.get_all()
    return {x.username for x in rep if not x.active}


async def test_lock_account_when_used(client_fixture: CF):
    pool, client, mock = client_fixture

    locked = await get_locked(pool)
    assert len(locked) == 0

    await client.__aenter__()
    locked = await get_locked(pool)
    assert len(locked) == 1
    assert "user1" in locked

    mock.add_response(json={"foo": "bar"})
    rep = await client.get(URL)
    assert rep is not None
    assert rep.json() == {"foo": "bar"}

    locked = await get_locked(pool)
    assert len(locked) == 1
    assert "user1" in locked

    await client.__aexit__(None, None, None)
    locked = await get_locked(pool)
    assert len(locked) == 0


async def test_do_not_switch_account_on_200(client_fixture: CF):
    pool, client, mock = client_fixture

    await client.__aenter__()
    locked1 = await get_locked(pool)
    assert len(locked1) == 1

    for x in range(3):
        mock.add_response(json={"foo": x})
        rep = await client.get(URL)
        assert rep is not None
        assert rep.json() == {"foo": x}

    locked2 = await get_locked(pool)
    assert locked1 == locked2

    await client.__aexit__(None, None, None)
    assert len(await get_locked(pool)) == 0


async def test_switch_acc_on_http_error(client_fixture: CF):
    pool, client, mock = client_fixture

    await client.__aenter__()
    locked1 = await get_locked(pool)
    assert len(locked1) == 1

    mock.add_response(status_code=403, json={})
    mock.add_response(json={"foo": "2"})

    rep = await client.get(URL)
    assert rep is not None
    assert rep.json() == {"foo": "2"}

    locked2 = await get_locked(pool)
    assert len(locked2) == 2

    await client.__aexit__(None, None, None)
    locked3 = await get_locked(pool)
    assert len(locked3) == 1
    assert locked1 == locked3


async def test_retry_with_same_acc_on_network_error(client_fixture: CF):
    pool, client, mock = client_fixture

    await client.__aenter__()
    locked1 = await get_locked(pool)
    assert len(locked1) == 1

    mock.add_exception(NetworkError("timeout"))
    mock.add_response(json={"foo": "2"})

    rep = await client.get(URL)
    assert rep is not None
    assert rep.json() == {"foo": "2"}

    assert await get_locked(pool) == locked1

    username = getattr(rep, "__username", None)
    assert username is not None


async def test_ctx_closed_on_break(client_fixture: CF):
    pool, client, mock = client_fixture

    async def get_data_stream():
        async with client as c:
            counter = 0
            while True:
                counter += 1
                check_retry = counter == 2
                before_ctx = c.ctx

                if check_retry:
                    mock.add_response(status_code=403, json={"counter": counter})
                    mock.add_response(json={"counter": counter})
                else:
                    mock.add_response(json={"counter": counter})

                rep = await c.get(URL)

                if check_retry:
                    assert before_ctx != c.ctx
                elif before_ctx is not None:
                    assert before_ctx == c.ctx

                assert rep is not None
                assert rep.json() == {"counter": counter}
                yield rep.json()["counter"]

                if counter == 9:
                    return

    async with aclosing(get_data_stream()) as gen:
        async for x in gen:
            if x == 3:
                break

    assert client.ctx is None


async def test_queue_client_passes_effective_proxy_to_xclid(pool_mock: AccountsPool, monkeypatch):
    mock = MockClient()
    seen = {}

    class FakeXClIdGen:
        def calc(self, *args, **kwargs):
            return "mocked-clid"

    async def fake_get(cls, username, proxy=None, fresh=False):
        seen["username"] = username
        seen["proxy"] = proxy
        seen["fresh"] = fresh
        return FakeXClIdGen()

    monkeypatch.setattr(Account, "make_client", lambda self, proxy=None: mock)
    monkeypatch.setattr(XClIdGenStore, "get", classmethod(fake_get))

    await pool_mock.add_account(
        "user1",
        "pass1",
        "email1",
        "email_pass1",
        proxy="127.0.0.1:7897",
    )
    await pool_mock.set_active("user1", True)

    client = QueueClient(pool_mock, "SearchTimeline")
    await client.__aenter__()

    mock.add_response(json={"ok": True})
    rep = await client.get(URL)

    assert rep is not None
    assert seen == {
        "username": "user1",
        "proxy": "http://127.0.0.1:7897",
        "fresh": False,
    }

    await client.__aexit__(None, None, None)


# --- ConnectError ---


async def test_connect_error_raises_after_3_retries(client_fixture: CF):
    pool, client, mock = client_fixture
    await client.__aenter__()

    mock.add_exception(ConnectError("refused"))
    mock.add_exception(ConnectError("refused"))
    mock.add_exception(ConnectError("refused"))

    with pytest.raises(ConnectError):
        await client.get(URL)

    await client.__aexit__(None, None, None)


async def test_connect_error_recovers_before_3_retries(client_fixture: CF):
    pool, client, mock = client_fixture
    await client.__aenter__()

    mock.add_exception(ConnectError("refused"))
    mock.add_exception(ConnectError("refused"))
    mock.add_response(json={"ok": True})

    rep = await client.get(URL)
    assert rep is not None
    assert rep.json() == {"ok": True}

    await client.__aexit__(None, None, None)


# --- Rate limit ---


async def test_rate_limit_locks_account_and_switches(client_fixture: CF):
    pool, client, mock = client_fixture
    await client.__aenter__()
    assert "user1" in await get_locked(pool)

    future_ts = 9999999999
    mock.add_response(
        headers={"x-rate-limit-remaining": "0", "x-rate-limit-reset": str(future_ts)},
    )
    mock.add_response(json={"ok": True})

    rep = await client.get(URL)
    assert rep is not None
    assert rep.json() == {"ok": True}

    user1 = next(x for x in await pool.get_all() if x.username == "user1")
    assert user1.locks.get("SearchTimeline") is not None

    await client.__aexit__(None, None, None)


# --- Ban / inactive ---


async def test_ban_88_marks_account_inactive(client_fixture: CF):
    pool, client, mock = client_fixture
    await client.__aenter__()

    mock.add_response(
        json={"errors": [{"code": 88, "message": "Rate limit exceeded"}]},
        headers={"x-rate-limit-remaining": "1"},
    )
    mock.add_response(json={"ok": True})

    rep = await client.get(URL)
    assert rep is not None
    assert "user1" in await get_inactive(pool)

    await client.__aexit__(None, None, None)


async def test_ban_326_marks_account_inactive(client_fixture: CF):
    pool, client, mock = client_fixture
    await client.__aenter__()

    mock.add_response(
        json={"errors": [{"code": 326, "message": "Authorization: Denied by access control"}]},
    )
    mock.add_response(json={"ok": True})

    rep = await client.get(URL)
    assert rep is not None
    assert "user1" in await get_inactive(pool)

    await client.__aexit__(None, None, None)


async def test_ban_32_marks_account_inactive(client_fixture: CF):
    pool, client, mock = client_fixture
    await client.__aenter__()

    mock.add_response(
        json={"errors": [{"code": 32, "message": "Could not authenticate you"}]},
    )
    mock.add_response(json={"ok": True})

    rep = await client.get(URL)
    assert rep is not None
    assert "user1" in await get_inactive(pool)

    await client.__aexit__(None, None, None)


async def test_403_no_errors_marks_account_inactive(client_fixture: CF):
    pool, client, mock = client_fixture
    await client.__aenter__()

    mock.add_response(status_code=403, json={})
    mock.add_response(json={"ok": True})

    rep = await client.get(URL)
    assert rep is not None
    assert "user1" in await get_inactive(pool)

    await client.__aexit__(None, None, None)


# --- Cloudflare / HTML block ---


async def test_cloudflare_block_returns_none(client_fixture: CF):
    pool, client, mock = client_fixture
    await client.__aenter__()

    mock.add_response(
        status_code=403,
        text="<html>blocked</html>",
        headers={"content-type": "text/html", "cf-ray": "abc123"},
    )

    rep = await client.get(URL)
    assert rep is None

    await client.__aexit__(None, None, None)


async def test_html_block_without_cf_returns_none(client_fixture: CF):
    pool, client, mock = client_fixture
    await client.__aenter__()

    mock.add_response(
        status_code=503,
        text="<html>error</html>",
        headers={"content-type": "text/html"},
    )

    rep = await client.get(URL)
    assert rep is None

    await client.__aexit__(None, None, None)


# --- _check_rep branches ---


async def test_131_with_user_data_continues(client_fixture: CF):
    pool, client, mock = client_fixture
    await client.__aenter__()

    mock.add_response(
        json={
            "errors": [{"code": 131, "message": "Dependency: Internal error"}],
            "data": {"user": {"id": "123"}},
        }
    )

    rep = await client.get(URL)
    assert rep is not None

    await client.__aexit__(None, None, None)


async def test_131_without_user_data_aborts(client_fixture: CF):
    pool, client, mock = client_fixture
    await client.__aenter__()

    mock.add_response(json={"errors": [{"code": 131, "message": "Dependency: Internal error"}]})

    rep = await client.get(URL)
    assert rep is None

    await client.__aexit__(None, None, None)


async def test_missing_status_error_ignored(client_fixture: CF):
    pool, client, mock = client_fixture
    await client.__aenter__()

    mock.add_response(
        json={"errors": [{"code": -1, "message": "_Missing: No status found with that ID"}]}
    )

    rep = await client.get(URL)
    assert rep is not None

    await client.__aexit__(None, None, None)


async def test_authorization_error_200_ignored(client_fixture: CF):
    pool, client, mock = client_fixture
    await client.__aenter__()

    mock.add_response(
        json={"errors": [{"code": -1, "message": "Authorization: Denied by unknown rule"}]}
    )

    rep = await client.get(URL)
    assert rep is not None

    await client.__aexit__(None, None, None)


async def test_unknown_error_msg_ignored(client_fixture: CF):
    pool, client, mock = client_fixture
    await client.__aenter__()

    mock.add_response(json={"errors": [{"code": 999, "message": "Some unfamiliar error"}]})

    rep = await client.get(URL)
    assert rep is not None

    await client.__aexit__(None, None, None)


async def test_unhandled_status_code_locks_and_retries(client_fixture: CF):
    pool, client, mock = client_fixture
    await client.__aenter__()

    mock.add_response(status_code=500, json={})
    mock.add_response(json={"ok": True})

    rep = await client.get(URL)
    assert rep is not None
    assert rep.json() == {"ok": True}

    user1 = next(x for x in await pool.get_all() if x.username == "user1")
    assert "SearchTimeline" in user1.locks
    assert int(user1.locks["SearchTimeline"].timestamp()) > utc.ts() + 60 * 10

    await client.__aexit__(None, None, None)


async def test_no_active_accounts_returns_none(pool_mock: AccountsPool):
    client = QueueClient(pool_mock, "SearchTimeline")
    rep = await client.get(URL)
    assert rep is None


async def test_unknown_exception_retries_then_locks_account(client_fixture: CF):
    pool, client, mock = client_fixture
    await client.__aenter__()

    mock.add_exception(RuntimeError("boom"))
    mock.add_exception(RuntimeError("boom"))
    mock.add_exception(RuntimeError("boom"))
    mock.add_response(json={"ok": True})

    rep = await client.get(URL)
    assert rep is not None
    assert rep.json() == {"ok": True}

    user1 = next(x for x in await pool.get_all() if x.username == "user1")
    assert "SearchTimeline" in user1.locks

    await client.__aexit__(None, None, None)


async def test_invalid_json_body_falls_back_to_raw_text(client_fixture: CF):
    pool, client, mock = client_fixture
    await client.__aenter__()

    mock.add_invalid_json_response(text="not-json")
    rep = await client.get(URL)
    assert rep is not None

    await client.__aexit__(None, None, None)


async def test_close_ctx_noop_when_ctx_is_none(pool_mock: AccountsPool):
    client = QueueClient(pool_mock, "SearchTimeline")
    # ctx is None — _close_ctx must be a no-op
    await client._close_ctx()


async def test_404_retries_exhaust_and_abort(client_fixture: CF):
    from unittest.mock import patch

    pool, client, mock = client_fixture
    await client.__aenter__()

    mock.add_response(status_code=404, json={})
    mock.add_response(status_code=404, json={})
    mock.add_response(status_code=404, json={})

    with patch("twscrape.queue_client.asyncio.sleep"):
        rep = await client.get(URL)
    assert rep is None

    await client.__aexit__(None, None, None)
