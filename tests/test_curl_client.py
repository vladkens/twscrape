"""CurlClient against real curl_cffi objects: what MockClient can't catch."""

from twscrape.http import CurlClient, make_client

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
