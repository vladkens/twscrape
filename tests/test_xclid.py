import twscrape.xclid as xclid


class FakeClient:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


async def test_xclid_create_passes_cookies_to_client(monkeypatch):
    seen = {}
    fake_client = FakeClient()

    def fake_make_client(*, headers=None, cookies=None):
        seen["headers"] = headers
        seen["cookies"] = cookies
        return fake_client

    async def fake_get_tw_page_text(url, clt):
        seen["url"] = url
        seen["client"] = clt
        return "<html></html>"

    async def fake_load_keys(soup, clt):
        seen["load_client"] = clt
        return [1, 2, 3], "anim-key"

    monkeypatch.setattr(xclid, "_make_http_client", fake_make_client)
    monkeypatch.setattr(xclid, "get_tw_page_text", fake_get_tw_page_text)
    monkeypatch.setattr(xclid, "load_keys", fake_load_keys)

    cookies = {"auth_token": "abc", "ct0": "def"}
    gen = await xclid.XClIdGen.create(cookies=cookies)

    assert gen.vk_bytes == [1, 2, 3]
    assert gen.anim_key == "anim-key"
    assert seen["headers"] == {"user-agent": "@chrome"}
    assert seen["cookies"] == cookies
    assert seen["url"] == "https://x.com/tesla"
    assert seen["client"] is fake_client
    assert seen["load_client"] is fake_client
    assert fake_client.closed is True


async def test_xclid_create_without_cookies(monkeypatch):
    seen = {}
    fake_client = FakeClient()

    def fake_make_client(*, headers=None, cookies=None):
        seen["cookies"] = cookies
        return fake_client

    async def fake_get_tw_page_text(url, clt):
        return "<html></html>"

    async def fake_load_keys(soup, clt):
        return [1, 2, 3], "anim-key"

    monkeypatch.setattr(xclid, "_make_http_client", fake_make_client)
    monkeypatch.setattr(xclid, "get_tw_page_text", fake_get_tw_page_text)
    monkeypatch.setattr(xclid, "load_keys", fake_load_keys)

    await xclid.XClIdGen.create()
    assert seen["cookies"] is None
