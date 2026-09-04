from datetime import timedelta

import pytest

from twscrape.accounts_pool import AccountsPool
from twscrape.dashboard import DashboardAuth, DashboardService, resolve_dashboard_credentials
from twscrape.utils import utc


async def test_dashboard_snapshot_exposes_only_safe_fields(pool_mock: AccountsPool):
    await pool_mock.add_account_cookies("ready-user", "auth_token=secret; ct0=csrf-secret")
    account = await pool_mock.get("ready-user")
    account.email = "private@example.com"
    account.proxy = "http://private-proxy"
    account.stats = {"SearchTimeline": 7}
    await pool_mock.save(account)

    snapshot = await DashboardService(pool_mock).snapshot()
    assert snapshot["summary"] == {
        "total": 1,
        "running": 1,
        "ready": 1,
        "cooling": 0,
        "attention": 0,
        "disabled": 0,
        "pool_healthy": True,
        "headline": "账号池正常 · 1/1 个账号可参与轮换",
    }
    item = snapshot["accounts"][0]
    assert item["username"] == "ready-user"
    assert item["status"] == "ready"
    assert item["status_label"] == "可用"
    assert item["has_proxy"] is True
    assert item["total_requests"] == 7
    assert item["requests_by_queue"] == [{"queue": "SearchTimeline", "count": 7}]
    assert "cookies" not in item
    assert "password" not in item
    assert "email" not in item
    assert "proxy" not in item
    assert "secret" not in str(snapshot)


async def test_dashboard_account_actions_are_scoped(pool_mock: AccountsPool):
    await pool_mock.add_account_cookies("first", "auth_token=a; ct0=b")
    await pool_mock.add_account_cookies("second", "auth_token=c; ct0=d")
    first = await pool_mock.get("first")
    second = await pool_mock.get("second")
    first.locks = {"SearchTimeline": utc.now() + timedelta(minutes=10)}
    second.locks = {"SearchTimeline": utc.now() + timedelta(minutes=10)}
    await pool_mock.save(first)
    await pool_mock.save(second)

    service = DashboardService(pool_mock)
    await service.reset_locks("first")
    await service.set_active("first", False)

    assert (await pool_mock.get("first")).locks == {}
    assert (await pool_mock.get("first")).active is False
    assert "SearchTimeline" in (await pool_mock.get("second")).locks
    assert (await pool_mock.get("second")).active is True


async def test_dashboard_updates_cookie_active_and_write_only_proxy(pool_mock: AccountsPool):
    await pool_mock.add_account_cookies("editable", "auth_token=old; ct0=old-csrf")
    service = DashboardService(pool_mock)

    await service.update_account(
        "editable",
        active=False,
        cookies="auth_token=new; ct0=new-csrf",
        proxy_mode="set",
        proxy="127.0.0.1:8080",
    )

    account = await pool_mock.get("editable")
    assert account.cookies == {"auth_token": "new", "ct0": "new-csrf"}
    assert account.active is False
    assert account.proxy == "http://127.0.0.1:8080"
    snapshot = await service.snapshot()
    assert snapshot["accounts"][0]["has_proxy"] is True
    assert "127.0.0.1" not in str(snapshot)

    await service.update_account(
        "editable", active=None, cookies=None, proxy_mode="clear", proxy=None
    )
    assert (await pool_mock.get("editable")).proxy is None


async def test_dashboard_deletes_only_target_account(pool_mock: AccountsPool):
    await pool_mock.add_account_cookies("first", "auth_token=a; ct0=b")
    await pool_mock.add_account_cookies("second", "auth_token=c; ct0=d")

    await DashboardService(pool_mock).delete_account("first")

    assert await pool_mock.get_account("first") is None
    assert await pool_mock.get_account("second") is not None


async def test_dashboard_rejects_invalid_edit_before_writing_cookie(pool_mock: AccountsPool):
    await pool_mock.add_account_cookies("editable", "auth_token=old; ct0=old-csrf")

    with pytest.raises(ValueError, match="代理地址不能超过"):
        await DashboardService(pool_mock).update_account(
            "editable",
            active=False,
            cookies="auth_token=new; ct0=new-csrf",
            proxy_mode="set",
            proxy="x" * 1001,
        )

    account = await pool_mock.get("editable")
    assert account.cookies == {"auth_token": "old", "ct0": "old-csrf"}
    assert account.active is True


async def test_dashboard_snapshot_prioritizes_attention_and_exposes_cooling_details(
    pool_mock: AccountsPool,
):
    await pool_mock.add_account_cookies("cooling", "auth_token=a; ct0=b")
    await pool_mock.add_account_cookies("attention", "auth_token=c; ct0=d")
    cooling = await pool_mock.get("cooling")
    cooling.locks = {"SearchTimeline": utc.now() + timedelta(minutes=10)}
    await pool_mock.save(cooling)
    attention = await pool_mock.get("attention")
    attention.error_msg = "session expired"
    attention.active = False
    await pool_mock.save(attention)

    snapshot = await DashboardService(pool_mock).snapshot()

    assert snapshot["summary"]["attention"] == 1
    assert snapshot["summary"]["cooling"] == 1
    assert snapshot["summary"]["pool_healthy"] is False
    assert snapshot["accounts"][0]["username"] == "attention"
    assert snapshot["accounts"][0]["next_action"] == "add_cookie"
    assert snapshot["accounts"][1]["status"] == "cooling"
    assert snapshot["accounts"][1]["next_unlock_in_seconds"] > 0
    assert snapshot["accounts"][1]["active_locks"][0]["queue"] == "SearchTimeline"


@pytest.mark.parametrize("cookies", ["", "auth_token=only", "ct0=only"])
async def test_dashboard_rejects_incomplete_cookie_sessions(pool_mock: AccountsPool, cookies: str):
    with pytest.raises(ValueError):
        await DashboardService(pool_mock).add_cookie_account("new-user", cookies)


def test_dashboard_auth_session_lifecycle():
    auth = DashboardAuth("admin", "strong-password")

    assert auth.authenticate("127.0.0.1", "admin", "wrong", now=1) is False
    assert auth.authenticate("127.0.0.1", "admin", "strong-password", now=2) is True
    token = auth.create_session(now=2)
    assert auth.validate_session(token, now=3) is True
    auth.revoke_session(token)
    assert auth.validate_session(token, now=4) is False


def test_dashboard_auth_rate_limits_failures():
    auth = DashboardAuth("admin", "strong-password")
    for attempt in range(5):
        assert auth.authenticate("127.0.0.1", "admin", "wrong", now=attempt) is False

    assert auth.is_locked("127.0.0.1", now=5) is True
    assert auth.authenticate("127.0.0.1", "admin", "strong-password", now=5) is False
    assert auth.authenticate("127.0.0.1", "admin", "strong-password", now=306) is True


def test_dashboard_credentials_from_environment(monkeypatch):
    monkeypatch.setenv("TWS_DASHBOARD_USERNAME", "operator")
    monkeypatch.setenv("TWS_DASHBOARD_PASSWORD", "strong-password")

    assert resolve_dashboard_credentials() == ("operator", "strong-password")


def test_dashboard_credentials_reject_short_password(monkeypatch):
    monkeypatch.setenv("TWS_DASHBOARD_PASSWORD", "short")

    with pytest.raises(ValueError, match="至少需要 8"):
        resolve_dashboard_credentials()
