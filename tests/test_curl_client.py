"""CurlClient against real curl_cffi objects: what MockClient can't catch."""

import asyncio
import base64
import json
from typing import Any
from unittest.mock import mock_open, patch
from urllib.parse import parse_qs, urlparse

import pytest
from curl_cffi.requests import Response as CurlResponse
from curl_cffi.requests.errors import RequestsError

from twscrape.http import ConnectError, CurlClient, NetworkError, Response, make_client
from twscrape.queue_client import dump_rep

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
        client = make_client("curl", proxy=srv.url, cookies={"auth_token": "a"})
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


async def test_saved_httpx_headers_do_not_override_the_browser_profile():
    # accounts logged in with v0.20 and older have these in `Account.headers`
    saved = {
        "accept": "*/*",
        "accept-encoding": "gzip, deflate",
        "connection": "keep-alive",
        "user-agent": "python-httpx/0.28.1",
        "x-csrf-token": "abc",
    }

    async with local_server() as srv:
        client = CurlClient(proxy=srv.url, headers=saved)
        await client.get("http://x.com/")
        await client.aclose()

    sent = srv.seen[0].headers
    assert sent["x-csrf-token"] == "abc"
    assert sent["accept"] != "*/*"
    assert sent["accept-encoding"] != "gzip, deflate"
    assert "keep-alive" not in sent["connection"]
    assert "Chrome" in sent["user-agent"]


async def test_socks5_proxy_resolves_hosts_on_the_proxy():
    seen = {}

    async def socks(rd: asyncio.StreamReader, wr: asyncio.StreamWriter):
        methods = (await rd.readexactly(2))[1]
        await rd.readexactly(methods)
        wr.write(b"\x05\x00")

        _, _, _, seen["atyp"] = await rd.readexactly(4)
        wr.close()

    srv = await asyncio.start_server(socks, "127.0.0.1", 0)
    client = CurlClient(proxy=f"socks5://127.0.0.1:{srv.sockets[0].getsockname()[1]}")
    with pytest.raises(NetworkError):
        await client.get("http://x.com/")
    await client.aclose()
    srv.close()

    assert seen["atyp"] == 3  # domain name, 1 would be an IPv4 resolved locally


@pytest.mark.parametrize("family", ["chrome", "safari", "firefox", "edge"])
async def test_every_browser_family_can_send_a_request(family):
    async with local_server() as srv:
        client = CurlClient(proxy=srv.url, headers={"user-agent": f"@{family}"})
        rep = await client.get("http://x.com/")
        await client.aclose()

    assert rep.status_code == 200
    assert srv.seen[0].headers["user-agent"]


async def test_response_exposes_real_curl_types():
    headers = [
        "X-Rate-Limit-Remaining: 5",
        "Content-Type: application/json; charset=utf-8",
        "CF-Ray: abc",
        "X-Dup: 1",
        "X-Dup: 2",
    ]

    async with local_server(lambda _: Reply(body=b'{"ok": 1}', headers=headers)) as srv:
        client = CurlClient(proxy=srv.url)
        rep = await client.get("http://x.com/path", params={"a": "1"})
        await client.aclose()

    assert rep.url == "http://x.com/path?a=1"
    assert rep.request is not None
    assert rep.request.method == "GET"
    assert rep.request.url == rep.url
    assert rep.json() == {"ok": 1}
    assert rep.text == '{"ok": 1}'
    assert rep.content == b'{"ok": 1}'

    assert rep.headers.get("x-rate-limit-remaining", -1) == "5"
    assert rep.headers.get("X-RATE-LIMIT-REMAINING", -1) == "5"
    assert rep.headers.get("x-rate-limit-reset", -1) == -1
    assert "cf-ray" in rep.headers
    assert "text/html" not in rep.headers.get("content-type", "")
    assert rep.headers.get("x-dup") == "1, 2"
    assert ("cf-ray", "abc") in list(rep.headers.items())


async def test_status_error_keeps_the_response():
    async with local_server(lambda _: Reply(status=429, body=b"slow down")) as srv:
        client = CurlClient(proxy=srv.url)
        rep = await client.get("http://x.com/")
        await client.aclose()

    assert rep.status_code == 429
    assert rep.text == "slow down"


async def test_request_kwargs_reach_the_wire():
    variables = json.dumps({"rawQuery": "a b+c &é", "count": 20}, separators=(",", ":"))

    async with local_server() as srv:
        client = CurlClient(proxy=srv.url, headers={"content-type": "application/json"})
        await client.get("http://x.com/gql", params={"variables": variables}, headers={"x-t": "1"})
        await client.post("http://api.x.com/task", params={"flow_name": "login"}, json={"a": 1})
        await client.post("http://api.x.com/activate")
        await client.aclose()

    get, post, empty = srv.seen
    assert parse_qs(urlparse(get.target).query) == {"variables": [variables]}
    assert get.headers["x-t"] == "1"
    assert get.headers["content-type"] == "application/json"

    assert post.method == "POST"
    assert parse_qs(urlparse(post.target).query) == {"flow_name": ["login"]}
    assert json.loads(post.body) == {"a": 1}
    assert post.headers["content-type"] == "application/json"

    assert empty.method == "POST"
    assert empty.body == b""


async def test_client_headers_can_be_changed_like_login_does():
    async with local_server() as srv:
        client = CurlClient(proxy=srv.url, headers={"authorization": "Bearer t"})
        client.headers["x-guest-token"] = "1"
        client.headers["X-Guest-Token"] = "2"
        await client.get("http://x.com/")
        await client.aclose()

    assert srv.seen[0].headers["x-guest-token"] == "2"
    assert srv.seen[0].headers["authorization"] == "Bearer t"

    saved = dict(client.headers.items())
    assert saved == {"authorization": "Bearer t", "x-guest-token": "2"}
    assert json.loads(json.dumps(saved)) == saved


def redirect(req: Seen) -> Reply:
    if req.target.endswith("/same"):
        return Reply(status=302, headers=["Location: /final?a=1"])
    if req.target.endswith("/other"):
        return Reply(status=302, headers=["Location: http://abs.twimg.com/final"])
    return Reply()


async def test_redirect_is_followed_and_post_becomes_get():
    async with local_server(redirect) as srv:
        client = CurlClient(proxy=srv.url)
        rep = await client.post("http://x.com/same", json={"a": 1})
        await client.aclose()

    assert rep.status_code == 200
    assert rep.url == "http://x.com/final?a=1"
    assert [x.method for x in srv.seen] == ["POST", "GET"]
    assert srv.seen[1].body == b""


async def test_redirect_to_another_host_drops_credentials():
    async with local_server(redirect) as srv:
        client = make_client(
            "curl",
            proxy=srv.url,
            headers={"authorization": "Bearer t"},
            cookies={"auth_token": "a"},
        )
        await client.get("http://x.com/other")
        await client.aclose()

    assert "authorization" not in srv.seen[1].headers
    assert "cookie" not in srv.seen[1].headers


def dump(rep: Response):
    with patch("builtins.open", mock_open()) as fp, patch("os.makedirs"):
        dump_rep(rep)

    return "".join(x.args[0] for x in fp().write.call_args_list)


async def test_dump_rep_reads_a_real_response():
    async with local_server(lambda _: Reply(body=b'{"ok": 1}')) as srv:
        client = CurlClient(proxy=srv.url)
        rep = await client.get("http://x.com/path")
        await client.aclose()

    assert "200 GET http://x.com/path" in dump(rep)


async def test_dump_rep_survives_response_without_request():
    raw: Any = CurlResponse()
    raw.url = "http://x.com/path"
    assert raw.request is None

    assert "200 ? http://x.com/path" in dump(Response(raw))


async def test_proxy_credentials_are_url_decoded():
    async with local_server() as srv:
        client = CurlClient(proxy=f"http://user:p%40ss@127.0.0.1:{srv.port}")
        await client.get("http://x.com/")
        await client.aclose()

    auth = srv.seen[0].headers["proxy-authorization"].split()[1]
    assert base64.b64decode(auth) == b"user:p@ss"


async def test_cancelled_request_leaves_the_client_closable():
    # xclid cancels the bundle downloads it no longer needs, then closes the client
    async def hang(*_):
        await asyncio.sleep(5)

    srv = await asyncio.start_server(hang, "127.0.0.1", 0)
    client = CurlClient()
    task = asyncio.create_task(client.get(f"http://127.0.0.1:{srv.sockets[0].getsockname()[1]}/"))
    await asyncio.sleep(0.05)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await client.aclose()
    srv.close()
