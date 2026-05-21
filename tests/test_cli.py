import argparse

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
