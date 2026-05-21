import pytest

from twscrape.utils import parse_cookies, parse_proxy


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
