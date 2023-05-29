import httpx
from pytest_httpx import HTTPXMock

from twscrape.logger import set_log_level

DB_FILE = "/tmp/twscrape_test_queue_client.db"
URL = "https://example.com/api"

set_log_level("ERROR")


async def test_lock_account_when_used(httpx_mock: HTTPXMock, client_fixture):
    pool, client = client_fixture
    assert (await pool.stats())["locked_search"] == 0

    await client.__aenter__()
    assert (await pool.stats())["locked_search"] == 1

    httpx_mock.add_response(url=URL, json={"foo": "bar"}, status_code=200)
    assert (await client.get(URL)).json() == {"foo": "bar"}

    await client.__aexit__(None, None, None)
    assert (await pool.stats())["locked_search"] == 0


async def test_do_not_switch_account_on_200(httpx_mock: HTTPXMock, client_fixture):
    pool, client = client_fixture
    assert (await pool.stats())["locked_search"] == 0
    await client.__aenter__()

    httpx_mock.add_response(url=URL, json={"foo": "1"}, status_code=200)
    httpx_mock.add_response(url=URL, json={"foo": "2"}, status_code=200)

    rep = await client.get(URL)
    assert rep.json() == {"foo": "1"}

    rep = await client.get(URL)
    assert rep.json() == {"foo": "2"}

    assert (await pool.stats())["locked_search"] == 1
    await client.__aexit__(None, None, None)


async def test_switch_acc_on_http_error(httpx_mock: HTTPXMock, client_fixture):
    pool, client = client_fixture

    assert (await pool.stats())["locked_search"] == 0
    await client.__aenter__()

    httpx_mock.add_response(url=URL, json={"foo": "1"}, status_code=403)
    httpx_mock.add_response(url=URL, json={"foo": "2"}, status_code=200)

    rep = await client.get(URL)
    assert rep.json() == {"foo": "2"}

    assert (await pool.stats())["locked_search"] == 1  # user1 unlocked, user2 locked
    await client.__aexit__(None, None, None)


async def test_retry_with_same_acc_on_network_error(httpx_mock: HTTPXMock, client_fixture):
    pool, client = client_fixture
    await client.__aenter__()

    httpx_mock.add_exception(httpx.ReadTimeout("Unable to read within timeout"))
    httpx_mock.add_response(url=URL, json={"foo": "2"}, status_code=200)

    rep = await client.get(URL)
    assert rep.json() == {"foo": "2"}

    assert (await pool.stats())["locked_search"] == 1

    username = getattr(rep, "__username", None)
    assert username is not None

    acc1 = await pool.get(username)
    assert len(acc1.locks) > 0

    acc2 = await pool.get("user2" if username == "user1" else "user1")
    assert len(acc2.locks) == 0
