from contextlib import aclosing

import pytest

from twscrape.accounts_pool import AccountsPool
from twscrape.http import ConnectError, NetworkError
from twscrape.queue_client import QueueClient

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
