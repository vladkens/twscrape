from contextlib import aclosing

import httpx
from pytest_httpx import HTTPXMock

from twscrape.accounts_pool import AccountsPool
from twscrape.logger import set_log_level
from twscrape.queue_client import QueueClient

set_log_level("ERROR")

DB_FILE = "/tmp/twscrape_test_queue_client.db"
URL = "https://example.com/api"
CF = tuple[AccountsPool, QueueClient]


async def get_locked_accounts(pool: AccountsPool) -> set[str]:
    return {x.username for x in await pool.get_all() if x.locks.get("SearchTimeline", None) is not None}


async def test_lock_account_when_used(httpx_mock: HTTPXMock, client_fixture):
    pool, client = client_fixture

    locked_before = await get_locked_accounts(pool)
    assert not locked_before

    # should lock account on getting it
    async with client:
        locked_after = await get_locked_accounts(pool)
        assert len(locked_after) == 1
        assert "user1" in locked_after

    # keep locked on request
    httpx_mock.add_response(url=URL, json={"foo": "bar"}, status_code=200)
    response = await client.get(URL)
    assert response.json() == {"foo": "bar"}

    locked_after = await get_locked_accounts(pool)
    assert len(locked_after) == 1
    assert "user1" in locked_after

    # unlock on exit

async def test_do_not_switch_account_on_200(httpx_mock: HTTPXMock, client_fixture: CF):
    pool, client = client_fixture

    # get account and lock it
    async with client:
        locked_accounts_before = await get_locked_accounts(pool)
        assert len(locked_accounts_before) == 1

        # make several requests with status=200
        for x in range(1):
            httpx_mock.add_response(url=URL, json={"foo": x}, status_code=200)
            response = await client.get(URL)
            assert response is not None
            assert response.json() == {"foo": x}

        # account should not be switched
        locked_accounts_after = await get_locked_accounts(pool)
        assert locked_accounts_before == locked_accounts_after


async def test_switch_acc_on_http_error(httpx_mock: HTTPXMock, client_fixture: CF):
    pool, client = client_fixture

    # locked account on enter
    async with client:
        locked_accounts_before = await get_locked_accounts(pool)
        assert len(locked_accounts_before) == 1

        # fail one request, account should be switched
        httpx_mock.add_response(url=URL, json={"foo": "1"}, status_code=403)
        httpx_mock.add_response(url=URL, json={"foo": "2"}, status_code=200)

        response = await client.get(URL)
        assert response is not None
        assert response.json() == {"foo": "2"}

        locked_accounts_after = await get_locked_accounts(pool)
        assert len(locked_accounts_after) == 2

    # unlock on exit (failed account still should locked)
    locked_accounts_after_exit = await get_locked_accounts(pool)
    assert len(locked_accounts_after_exit) == 1
    assert locked_accounts_before == locked_accounts_after_exit  # failed account locked


async def test_retry_with_same_acc_on_network_error(httpx_mock: HTTPXMock, client_fixture: CF):
    pool, client = client_fixture

    # locked account on enter
    async with client:
        locked_accounts_before = await get_locked_accounts(pool)
        assert len(locked_accounts_before) == 1

        # timeout on first request, account should not be switched
        httpx_mock.add_exception(httpx.ReadTimeout("Unable to read within timeout"))
        httpx_mock.add_response(url=URL, json={"foo": "2"}, status_code=200)

        response = await client.get(URL)
        assert response is not None
        assert response.json() == {"foo": "2"}

        locked_accounts_after = await get_locked_accounts(pool)
        assert locked_accounts_after == locked_accounts_before

        # check username added to request obj (for logging)
        username = getattr(response, "__username", None)
        assert username is not None


async def test_ctx_closed_on_break(httpx_mock: HTTPXMock, client_fixture: CF):
    pool, client = client_fixture

    async def get_data_stream():
        async with client as c:
            counter = 0
            while True:
                counter += 1
                check_retry = counter == 2
                before_ctx = c.ctx

                if check_retry:
                    httpx_mock.add_response(url=URL, json={"counter": counter}, status_code=403)
                    httpx_mock.add_response(url=URL, json={"counter": counter}, status_code=200)
                else:
                    httpx_mock.add_response(url=URL, json={"counter": counter}, status_code=200)

                response = await c.get(URL)

                if check_retry:
                    assert before_ctx != c.ctx
                elif before_ctx is not None:
                    assert before_ctx == c.ctx

                assert response is not None
                assert response.json() == {"counter": counter}
                yield response.json()["counter"]

                if counter == 9:
                    return

    # need to use async with to break to work
    async with aclosing(get_data_stream()) as gen:
        async for x in gen:
            if x == 3:
                break

    # ctx should be None after break
    assert client.ctx is None
