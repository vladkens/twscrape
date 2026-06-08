import pytest

from twscrape.utils import get_env_bool, parse_cookies, parse_proxy, to_old_obj


def test_cookies_parse():
    val = "abc=123; def=456; ghi=789"
    assert parse_cookies(val) == {"abc": "123", "def": "456", "ghi": "789"}

    val = '{"abc": "123", "def": "456", "ghi": "789"}'
    assert parse_cookies(val) == {"abc": "123", "def": "456", "ghi": "789"}

    val = '[{"name": "abc", "value": "123"}, {"name": "def", "value": "456"}, {"name": "ghi", "value": "789"}]'
    assert parse_cookies(val) == {"abc": "123", "def": "456", "ghi": "789"}

    val = "eyJhYmMiOiAiMTIzIiwgImRlZiI6ICI0NTYiLCAiZ2hpIjogIjc4OSJ9"
    assert parse_cookies(val) == {"abc": "123", "def": "456", "ghi": "789"}

    val = "W3sibmFtZSI6ICJhYmMiLCAidmFsdWUiOiAiMTIzIn0sIHsibmFtZSI6ICJkZWYiLCAidmFsdWUiOiAiNDU2In0sIHsibmFtZSI6ICJnaGkiLCAidmFsdWUiOiAiNzg5In1d"
    assert parse_cookies(val) == {"abc": "123", "def": "456", "ghi": "789"}

    val = '{"cookies": {"abc": "123", "def": "456", "ghi": "789"}}'
    assert parse_cookies(val) == {"abc": "123", "def": "456", "ghi": "789"}

    with pytest.raises(ValueError, match=r"Invalid cookie value: .+"):
        val = "{invalid}"
        assert parse_cookies(val) == {}


def test_proxy_parse():
    assert parse_proxy(None) is None
    assert parse_proxy("") is None

    # already has scheme
    assert parse_proxy("http://1.2.3.4:8080") == "http://1.2.3.4:8080"
    assert parse_proxy("http://user:pass@1.2.3.4:8080") == "http://user:pass@1.2.3.4:8080"
    assert parse_proxy("socks5://1.2.3.4:1080") == "socks5://1.2.3.4:1080"
    assert parse_proxy("socks5://user:pass@1.2.3.4:1080") == "socks5://user:pass@1.2.3.4:1080"

    # host:port
    assert parse_proxy("1.2.3.4:8080") == "http://1.2.3.4:8080"

    # host:port:user:pass
    assert parse_proxy("1.2.3.4:8080:user:pass") == "http://user:pass@1.2.3.4:8080"

    # user:pass@host:port (no scheme)
    assert parse_proxy("user:pass@1.2.3.4:8080") == "http://user:pass@1.2.3.4:8080"


def test_get_env_bool(monkeypatch):
    monkeypatch.delenv("TEST_BOOL_FLAG", raising=False)
    assert get_env_bool("TEST_BOOL_FLAG") is False
    assert get_env_bool("TEST_BOOL_FLAG", default_val=True) is True

    for truthy in ("1", "true", "yes", "True", "YES"):
        monkeypatch.setenv("TEST_BOOL_FLAG", truthy)
        assert get_env_bool("TEST_BOOL_FLAG") is True

    for falsy in ("0", "false", "no", ""):
        monkeypatch.setenv("TEST_BOOL_FLAG", falsy)
        assert get_env_bool("TEST_BOOL_FLAG") is False


def test_to_old_obj_user_new_schema():
    obj = {
        "__typename": "User",
        "rest_id": "12345",
        "core": {
            "screen_name": "testuser",
            "name": "Test User",
            "created_at": "Mon Jan 01 00:00:00 +0000 2020",
        },
        "avatar": {"image_url": "https://example.com/avatar.jpg"},
        "location": {"location": "Earth"},
        "privacy": {"protected": False},
        "verification": {"verified": True},
        "profile_bio": {"description": "A test bio"},
        "is_blue_verified": True,
    }

    flat = to_old_obj(obj)
    assert flat["screen_name"] == "testuser"
    assert flat["profile_image_url_https"] == "https://example.com/avatar.jpg"
    assert flat["location"] == "Earth"
    assert flat["protected"] is False
    assert flat["verified"] is True
    assert flat["description"] == "A test bio"
    assert flat["is_blue_verified"] is True
    assert flat["id"] == 12345


def test_to_old_obj_tweet_new_schema():
    obj = {
        "__typename": "Tweet",
        "rest_id": "9876",
        "source": "<a>Twitter Web App</a>",
    }

    flat = to_old_obj(obj)
    assert flat["source"] == "<a>Twitter Web App</a>"
    assert flat["id"] == 9876
