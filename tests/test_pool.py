import pytest

from twscrape.accounts_pool import AccountsPool, NoAccountError
from twscrape.utils import utc


async def test_add_accounts(pool_mock: AccountsPool):
    # should add account
    await pool_mock.add_account("user1", "pass1", "email1", "email_pass1")
    acc = await pool_mock.get("user1")
    assert acc.username == "user1"
    assert acc.password == "pass1"
    assert acc.email == "email1"
    assert acc.email_password == "email_pass1"

    # should not add account with same username
    await pool_mock.add_account("user1", "pass2", "email2", "email_pass2")
    acc = await pool_mock.get("user1")
    assert acc.username == "user1"
    assert acc.password == "pass1"
    assert acc.email == "email1"
    assert acc.email_password == "email_pass1"

    # should not add account with different username case
    await pool_mock.add_account("USER1", "pass2", "email2", "email_pass2")
    acc = await pool_mock.get("user1")
    assert acc.username == "user1"
    assert acc.password == "pass1"
    assert acc.email == "email1"
    assert acc.email_password == "email_pass1"

    # should add account with different username
    await pool_mock.add_account("user2", "pass2", "email2", "email_pass2")
    acc = await pool_mock.get("user2")
    assert acc.username == "user2"
    assert acc.password == "pass2"
    assert acc.email == "email2"
    assert acc.email_password == "email_pass2"


async def test_add_account_cookies(pool_mock: AccountsPool):
    await pool_mock.add_account_cookies("user1", "auth_token=token; ct0=csrf")
    acc = await pool_mock.get("user1")

    assert acc.active is True


async def test_add_account_cookies_without_ct0(pool_mock: AccountsPool):
    await pool_mock.add_account_cookies("user1", "auth_token=token")
    acc = await pool_mock.get("user1")

    assert acc.active is False


async def test_add_account_cookies_existing(pool_mock: AccountsPool):
    await pool_mock.add_account_cookies("user1", "auth_token=token; ct0=csrf")
    acc = await pool_mock.get("user1")

    await pool_mock.add_account_cookies("user1", "auth_token=other")
    same = await pool_mock.get("user1")

    assert same.cookies == acc.cookies
    assert same.active is True


async def test_get_all(pool_mock: AccountsPool):
    # should return empty list
    accs = await pool_mock.get_all()
    assert len(accs) == 0

    # should return all accounts
    await pool_mock.add_account("user1", "pass1", "email1", "email_pass1")
    await pool_mock.add_account("user2", "pass2", "email2", "email_pass2")
    accs = await pool_mock.get_all()
    assert len(accs) == 2
    assert accs[0].username == "user1"
    assert accs[1].username == "user2"


async def test_save(pool_mock: AccountsPool):
    # should save account
    await pool_mock.add_account("user1", "pass1", "email1", "email_pass1")
    acc = await pool_mock.get("user1")
    acc.password = "pass2"
    await pool_mock.save(acc)
    acc = await pool_mock.get("user1")
    assert acc.password == "pass2"

    # should not save account
    acc = await pool_mock.get("user1")
    acc.username = "user2"
    await pool_mock.save(acc)
    acc = await pool_mock.get("user1")
    assert acc.username == "user1"


async def test_get_for_queue(pool_mock: AccountsPool):
    Q = "test_queue"

    # should return account
    await pool_mock.add_account("user1", "pass1", "email1", "email_pass1")
    await pool_mock.set_active("user1", True)
    acc = await pool_mock.get_for_queue(Q)
    assert acc is not None
    assert acc.username == "user1"
    assert acc.active is True
    assert acc.locks is not None
    assert Q in acc.locks
    assert acc.locks[Q] is not None

    # should return None
    acc = await pool_mock.get_for_queue(Q)
    assert acc is None


async def test_account_unlock(pool_mock: AccountsPool):
    Q = "test_queue"

    await pool_mock.add_account("user1", "pass1", "email1", "email_pass1")
    await pool_mock.set_active("user1", True)
    acc = await pool_mock.get_for_queue(Q)
    assert acc is not None
    assert acc.locks[Q] is not None

    # should unlock account and make available for queue
    await pool_mock.unlock(acc.username, Q)
    acc = await pool_mock.get_for_queue(Q)
    assert acc is not None
    assert acc.locks[Q] is not None

    # should update lock time
    end_time = utc.ts() + 60  # + 1 minute
    await pool_mock.lock_until(acc.username, Q, end_time)

    acc = await pool_mock.get(acc.username)
    assert int(acc.locks[Q].timestamp()) == end_time


async def test_get_stats(pool_mock: AccountsPool):
    Q = "SearchTimeline"

    # should return empty stats
    stats = await pool_mock.stats()
    for k, v in stats.items():
        assert v == 0, f"{k} should be 0"

    # should increate total
    await pool_mock.add_account("user1", "pass1", "email1", "email_pass1")
    stats = await pool_mock.stats()
    assert stats["total"] == 1
    assert stats["active"] == 0

    # should increate active
    await pool_mock.set_active("user1", True)
    stats = await pool_mock.stats()
    assert stats["total"] == 1
    assert stats["active"] == 1

    # should update queue stats
    acc = await pool_mock.get_for_queue(Q)
    assert acc is not None
    stats = await pool_mock.stats()
    assert stats["total"] == 1
    assert stats["active"] == 1
    assert stats[f"locked_{Q}"] == 1


async def test_delete_accounts(pool_mock: AccountsPool):
    await pool_mock.add_account("user1", "pass1", "email1", "ep1")
    await pool_mock.add_account("user2", "pass2", "email2", "ep2")

    await pool_mock.delete_accounts("user1")
    usernames = {x.username for x in await pool_mock.get_all()}
    assert "user1" not in usernames
    assert "user2" in usernames

    await pool_mock.delete_accounts(["user2"])
    assert len(await pool_mock.get_all()) == 0


async def test_delete_inactive(pool_mock: AccountsPool):
    await pool_mock.add_account("user1", "pass1", "email1", "ep1")
    await pool_mock.add_account("user2", "pass2", "email2", "ep2")
    await pool_mock.set_active("user2", True)

    await pool_mock.delete_inactive()
    accs = await pool_mock.get_all()
    assert len(accs) == 1
    assert accs[0].username == "user2"


async def test_reset_locks(pool_mock: AccountsPool):
    Q = "TestQueue"
    await pool_mock.add_account("user1", "pass1", "email1", "ep1")
    await pool_mock.set_active("user1", True)

    await pool_mock.get_for_queue(Q)
    user = await pool_mock.get("user1")
    assert Q in user.locks

    await pool_mock.reset_locks()
    user = await pool_mock.get("user1")
    assert Q not in user.locks


async def test_mark_inactive(pool_mock: AccountsPool):
    await pool_mock.add_account("user1", "pass1", "email1", "ep1")
    await pool_mock.set_active("user1", True)

    await pool_mock.mark_inactive("user1", "banned by system")
    acc = await pool_mock.get("user1")
    assert acc.active is False
    assert acc.error_msg == "banned by system"


async def test_next_available_at_none_when_empty(pool_mock: AccountsPool):
    assert await pool_mock.next_available_at("TestQueue") is None


async def test_next_available_at_returns_future_time(pool_mock: AccountsPool):
    Q = "TestQueue"
    await pool_mock.add_account("user1", "pass1", "email1", "ep1")
    await pool_mock.set_active("user1", True)
    await pool_mock.lock_until("user1", Q, utc.ts() + 3600)

    result = await pool_mock.next_available_at(Q)
    assert result is not None
    assert result != "now"


async def test_get_for_queue_or_wait_raises_when_flag_set(pool_mock: AccountsPool):
    pool = AccountsPool(pool_mock._db_file, raise_when_no_account=True)
    with pytest.raises(NoAccountError):
        await pool.get_for_queue_or_wait("TestQueue")


async def test_get_for_queue_or_wait_raises_via_env(pool_mock: AccountsPool, monkeypatch):
    monkeypatch.setenv("TWS_RAISE_WHEN_NO_ACCOUNT", "1")
    with pytest.raises(NoAccountError):
        await pool_mock.get_for_queue_or_wait("TestQueue")


async def test_accounts_info_active_first(pool_mock: AccountsPool):
    await pool_mock.add_account("user_b", "pass", "email", "ep")
    await pool_mock.add_account("user_a", "pass", "email", "ep")
    await pool_mock.set_active("user_a", True)

    items = await pool_mock.accounts_info()
    assert items[0]["username"] == "user_a"
    assert items[0]["active"] is True
    assert items[1]["username"] == "user_b"
    assert items[1]["active"] is False


async def test_load_from_file(pool_mock: AccountsPool, tmp_path):
    filepath = tmp_path / "accounts.txt"
    filepath.write_text("user1:pass1:email1:ep1\nuser2:pass2:email2:ep2\n")

    await pool_mock.load_from_file(str(filepath), "username:password:email:email_password")
    usernames = {x.username for x in await pool_mock.get_all()}
    assert "user1" in usernames
    assert "user2" in usernames
