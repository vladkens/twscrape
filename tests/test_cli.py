import argparse
import json

from tests.test_parser import fake_rep
from twscrape import cli


async def test_add_cookie_uses_arg_cookies(tmp_path, monkeypatch):
    called = {}

    async def mock_add_account_cookies(self, username, cookies):
        called["username"] = username
        called["cookies"] = cookies

    monkeypatch.setattr(cli.AccountsPool, "add_account_cookies", mock_add_account_cookies)

    args = argparse.Namespace(
        command="add_cookie",
        debug=False,
        db=str(tmp_path / "test.db"),
        email_first=False,
        manual=False,
        username="user1",
        cookies="auth_token=token; ct0=csrf",
    )

    await cli.main(args)

    assert called == {"username": "user1", "cookies": "auth_token=token; ct0=csrf"}


async def test_add_cookie_prompts_securely_when_missing(tmp_path, monkeypatch):
    called = {}

    async def mock_add_account_cookies(self, username, cookies):
        called["username"] = username
        called["cookies"] = cookies

    def mock_getpass(prompt):
        called["prompt"] = prompt
        return "auth_token=prompted; ct0=csrf"

    monkeypatch.setattr(cli.AccountsPool, "add_account_cookies", mock_add_account_cookies)
    monkeypatch.setattr(cli.getpass, "getpass", mock_getpass)

    args = argparse.Namespace(
        command="add_cookie",
        debug=False,
        db=str(tmp_path / "test.db"),
        email_first=False,
        manual=False,
        username="user1",
        cookies=None,
    )

    await cli.main(args)

    assert called == {
        "prompt": "cookies (e.g. auth_token=xxx; ct0=yyy): ",
        "username": "user1",
        "cookies": "auth_token=prompted; ct0=csrf",
    }


async def test_add_accounts_prints_next_step(tmp_path, monkeypatch, capsys):
    called = {}

    async def mock_load_from_file(self, file_path, line_format):
        called["file_path"] = file_path
        called["line_format"] = line_format

    monkeypatch.setattr(cli.AccountsPool, "load_from_file", mock_load_from_file)

    args = argparse.Namespace(
        command="add_accounts",
        debug=False,
        db=str(tmp_path / "test.db"),
        email_first=False,
        manual=False,
        file_path="accounts.txt",
        line_format="username:password:email:email_password",
    )

    await cli.main(args)

    out = capsys.readouterr().out
    assert called == {
        "file_path": "accounts.txt",
        "line_format": "username:password:email:email_password",
    }
    assert "twscrape login_accounts" in out


async def test_search_prints_parsed_tweets(tmp_path, monkeypatch, capsys):
    async def mock_search_raw(self, q, limit=-1, kv=None):
        yield fake_rep("raw_search")

    monkeypatch.setattr(cli.API, "search_raw", mock_search_raw)

    args = argparse.Namespace(
        command="search",
        debug=False,
        db=str(tmp_path / "test.db"),
        email_first=False,
        manual=False,
        raw=False,
        arg_name="query",
        query="elon musk lang:en",
        limit=1,
    )

    await cli.main(args)

    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) > 0
    doc = json.loads(out[0])
    assert isinstance(doc["id"], int)
    assert doc["user"]["username"] is not None


async def test_user_by_login_prints_parsed_user(tmp_path, monkeypatch, capsys):
    async def mock_user_by_login_raw(self, login, kv=None):
        return fake_rep("raw_user_by_login")

    monkeypatch.setattr(cli.API, "user_by_login_raw", mock_user_by_login_raw)

    args = argparse.Namespace(
        command="user_by_login",
        debug=False,
        db=str(tmp_path / "test.db"),
        email_first=False,
        manual=False,
        raw=False,
        arg_name="username",
        username="xdevelopers",
    )

    await cli.main(args)

    doc = json.loads(capsys.readouterr().out.strip())
    assert doc["id"] == 2244994945
    assert doc["username"] == "XDevelopers"


async def test_tweet_details_raw_prints_raw_json(tmp_path, monkeypatch, capsys):
    async def mock_tweet_details_raw(self, twid, kv=None):
        return fake_rep("raw_tweet_details")

    monkeypatch.setattr(cli.API, "tweet_details_raw", mock_tweet_details_raw)

    args = argparse.Namespace(
        command="tweet_details",
        debug=False,
        db=str(tmp_path / "test.db"),
        email_first=False,
        manual=False,
        raw=True,
        arg_name="tweet_id",
        tweet_id=1649191520250245121,
    )

    await cli.main(args)

    doc = json.loads(capsys.readouterr().out.strip())
    assert "data" in doc
    assert "threaded_conversation_with_injections_v2" in json.dumps(doc)
