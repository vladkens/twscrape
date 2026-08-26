from datetime import timedelta

import pytest

from twscrape.accounts_pool import AccountsPool
from twscrape.dashboard import DashboardService
from twscrape.utils import utc


async def test_dashboard_snapshot_exposes_only_safe_fields(pool_mock: AccountsPool):
    await pool_mock.add_account_cookies("ready-user", "auth_token=secret; ct0=csrf-secret")
    account = await pool_mock.get("ready-user")
    account.email = "private@example.com"
    account.proxy = "http://private-proxy"
    account.stats = {"SearchTimeline": 7}
    await pool_mock.save(account)

    snapshot = await DashboardService(pool_mock).snapshot()
    assert snapshot["summary"] == {"total": 1, "running": 1, "attention": 0}
    item = snapshot["accounts"][0]
    assert item["username"] == "ready-user"
    assert item["total_requests"] == 7
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


@pytest.mark.parametrize("cookies", ["", "auth_token=only", "ct0=only"])
async def test_dashboard_rejects_incomplete_cookie_sessions(pool_mock: AccountsPool, cookies: str):
    with pytest.raises(ValueError):
        await DashboardService(pool_mock).add_cookie_account("new-user", cookies)
