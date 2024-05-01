from typing import List, AsyncContextManager
from unittest.mock import AsyncMock
from twscrape.accounts_pool import AccountsPool
from twscrape.utils import utc


async def test_add_accounts(pool_mock: AccountsPool):
    """
    Test adding accounts to the pool.
    """
    # should add account
    account = Account(
        username="user1",
        password="pass1",
        email="email1",
        email_password="email_pass1",
    )
    await pool_mock.add_account(**account.to_dict())
    acc = await pool_mock.get(account.username)
    assert acc == account

    # should not add account with same username
    account.password = "pass2"
    with pytest.raises(ValueError):
        await pool_mock.add_account(**account.to_dict())

    # should not add account with different username case
    account.username = "USER1"
    with pytest.raises(ValueError):
        await pool_mock.add_account(**account.to_dict())

    # should add account with different username
    account.username = "user2"
    await pool_mock.add_account(**account.to_dict())
    acc = await pool_mock.get(account.username)
    assert acc == account


async def test_get_all(pool_mock: AccountsPool):
    """
    Test getting all accounts from the pool.
    """
    # should return empty list
    accounts = await pool_mock.get_all()
    assert len(accounts) == 0

    # should return all accounts
    accounts = [
        Account(
            username="user1",
            password="pass1",
            email="email1",
            email_password="email_pass1",
        ),
        Account(
            username="user2",
            password="pass2",
            email="email2",
            email_password="email_pass2",
        ),
    ]
    for account in accounts:
        await pool_mock.add_account(**account.to_dict())
    accounts = await pool_mock.get_all()
    assert len(accounts) == 2
    for account, db_account in zip(accounts, accounts):
        assert account == db_account


async def test_save(pool_mock: AccountsPool):
    """
    Test saving changes to an account.
    """
    # should save account
    account = Account(
        username="user1",
        password="pass1",
        email="email1",
        email_password="email_pass1",
    )
    await pool_mock.add_account(**account.to_dict())
    db_account = await pool_mock.get(account.username)
    db_account.password = "pass2"
    await pool_mock.save(db_account)
    db_account = await pool_mock.get(account.username)
    assert db_account.password == "pass2"

    # should not save account
    db_account.username = "user2"
    with pytest.raises(ValueError):
        await pool_mock.save(db_account)


async def test_get_for_queue(pool_mock: AccountsPool):
    """
    Test getting an account for a queue.
    """
    Q = "test_queue"

    # should return account
    account = Account(
        username="user1",
        password="pass1",
        email="email1",
        email_password="email_pass1",
    )
    await pool_mock.add_account(**account.to_dict())
    await pool_mock.set_active(account.username, True)
    db_account = await pool_mock.get_for_queue(Q)
    assert db_account == account
    assert db_account.active is True
    assert db_account.locks is not None
    assert Q in db_account.locks
    assert db_account.locks[Q] is not None

    # should return None
    db_account = await pool_mock.get_for_queue(Q)
    assert db_account is None


async def test_account_unlock(pool_mock: AccountsPool):
    """
    Test unlocking an account.
    """
    Q = "test_queue"

    account = Account(
        username="user1",
        password="pass1",
        email="email1",
        email_password="email_pass1",
    )
    await pool_mock.add_account(**account.to_dict())
    await pool_mock.set_active(account.username, True)
    db_account = await pool_mock.get_for_queue(Q)
    assert db_account is not None
    assert db_account.locks[Q] is not None

    # should unlock account and make available for queue
    await pool_mock.unlock(db_account.username, Q)
    db_account = await pool_mock.get_for_queue(Q)
    assert db_account is not None
    assert db_account.locks[Q] is not None

    # should update lock time
    end_time = utc.ts() + 60  # + 1 minute
    await pool_mock.lock_until(db_account.username, Q, end_time)

    db_account = await pool_mock.get(db_account.username)
    assert int(db_account.locks[Q].timestamp()) == end_time


async def test_get_stats(pool_mock: AccountsPool):
    """
    Test getting stats from the pool.
    """
    Q = "SearchTimeline"

    # should return empty stats
    stats = await pool_mock.stats()
    for k, v in stats.items():
        assert v == 0, f"{k} should be 0"

    # should increate total
    account = Account(
        username="user1",
        password="pass1",
        email="email1",
        email_password="email_pass1",
    )
    await pool_mock.add_account(**account.to_dict())
    stats = await pool_mock.stats()
    assert stats["total"] == 1
    assert stats["active"] == 0

    # should increate active
    await pool_mock.set_active(account.username, True)
    stats = await pool_mock.stats()
    assert stats["total"] == 1
    assert stats["active"] == 1

    # should update queue stats
    db_account = await pool_mock.get_for_queue(Q)
    assert db_account is not None
    stats = await pool_mock.stats()
    assert stats["total"] == 1
    assert stats["active"] == 1
    assert stats[f"locked_{Q}"] == 1
