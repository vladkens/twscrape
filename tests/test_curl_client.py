"""CurlClient against real curl_cffi objects: what MockClient can't catch."""

import asyncio

import pytest
from curl_cffi.requests.errors import RequestsError

from twscrape.http import ConnectError, CurlClient, NetworkError, make_client

from .local_server import Reply, Seen, local_server


def rotate_ct0(req: Seen) -> Reply:
    if req.target.endswith("/rotate"):
        return Reply(headers=["Set-Cookie: ct0=new; Domain=.x.com; Path=/"])
    if req.target.endswith("/expire"):
        return Reply(headers=["Set-Cookie: ct0=; Domain=.x.com; Path=/; Max-Age=0"])
    return Reply()


async def test_account_cookies_follow_x_rotation():
    async with local_server(rotate_ct0) as srv:
        client = make_client(proxy=srv.url, cookies={"ct0": "old", "auth_token": "a"})
        await client.get("http://x.com/rotate")
        await client.get("http://api.x.com/next")
        await client.aclose()

    assert sorted(srv.seen[-1].headers["cookie"].split("; ")) == ["auth_token=a", "ct0=new"]
    assert client.cookies.get("ct0") == "new"
    assert "ct0" in client.cookies
    assert client.cookies["ct0"] == "new"
    assert dict(client.cookies.items()) == {"auth_token": "a", "ct0": "new"}


async def test_account_cookies_are_dropped_when_x_expires_them():
    async with local_server(rotate_ct0) as srv:
        client = make_client(proxy=srv.url, cookies={"ct0": "old", "auth_token": "a"})
        await client.get("http://api.x.com/expire")
        await client.get("http://api.x.com/next")
        await client.aclose()

    assert srv.seen[-1].headers["cookie"] == "auth_token=a"
    assert "ct0" not in client.cookies
    assert dict(client.cookies.items()) == {"auth_token": "a"}


async def test_account_cookies_stay_off_other_hosts():
    async with local_server() as srv:
        client = CurlClient(proxy=srv.url, cookies={"auth_token": "a"})
        await client.get("http://x.com/")
        await client.get("http://abs.twimg.com/main.js")
        await client.aclose()

    assert srv.seen[0].headers["cookie"] == "auth_token=a"
    assert "cookie" not in srv.seen[1].headers


async def test_refused_connection_is_connect_error():
    async with local_server() as srv:
        pass  # the port is free again

    client = CurlClient()
    with pytest.raises(ConnectError):
        await client.get(srv.url)
    await client.aclose()


async def test_request_that_went_out_is_not_sent_twice():
    async with local_server(lambda _: None) as srv:
        client = CurlClient(proxy=srv.url)
        with pytest.raises(NetworkError):
            await client.post("http://api.x.com/1.1/onboarding/task.json", json={"a": 1})
        await client.aclose()

    assert len(srv.seen) == 1


async def test_timeout_is_network_error():
    async def hang(*_):
        await asyncio.sleep(5)

    srv = await asyncio.start_server(hang, "127.0.0.1", 0)
    client = CurlClient()
    with pytest.raises(NetworkError):
        await client.get(f"http://127.0.0.1:{srv.sockets[0].getsockname()[1]}/", timeout=0.1)
    await client.aclose()
    srv.close()


async def test_closed_session_is_not_a_network_error():
    client = CurlClient()
    await client.aclose()
    with pytest.raises(RequestsError):
        await client.get("http://x.com/")
