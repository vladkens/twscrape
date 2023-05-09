import os

from twscrape.accounts_pool import AccountsPool
from twscrape.db import DB
from twscrape.utils import utc_ts

DB_FILE = "/tmp/twscrape_test.db"


def remove_db():
    DB._init_once[DB_FILE] = False
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)


async def test_add_accounts():
    remove_db()
    pool = AccountsPool(DB_FILE)

    # should add account
    await pool.add_account("user1", "pass1", "email1", "email_pass1")
    acc = await pool.get("user1")
    assert acc.username == "user1"
    assert acc.password == "pass1"
    assert acc.email == "email1"
    assert acc.email_password == "email_pass1"

    # should not add account with same username
    await pool.add_account("user1", "pass2", "email2", "email_pass2")
    acc = await pool.get("user1")
    assert acc.username == "user1"
    assert acc.password == "pass1"
    assert acc.email == "email1"
    assert acc.email_password == "email_pass1"

    # should not add account with different username case
    await pool.add_account("USER1", "pass2", "email2", "email_pass2")
    acc = await pool.get("user1")
    assert acc.username == "user1"
    assert acc.password == "pass1"
    assert acc.email == "email1"
    assert acc.email_password == "email_pass1"

    # should add account with different username
    await pool.add_account("user2", "pass2", "email2", "email_pass2")
    acc = await pool.get("user2")
    assert acc.username == "user2"
    assert acc.password == "pass2"
    assert acc.email == "email2"
    assert acc.email_password == "email_pass2"


async def test_get_all():
    remove_db()
    pool = AccountsPool(DB_FILE)

    # should return empty list
    accs = await pool.get_all()
    assert len(accs) == 0

    # should return all accounts
    await pool.add_account("user1", "pass1", "email1", "email_pass1")
    await pool.add_account("user2", "pass2", "email2", "email_pass2")
    accs = await pool.get_all()
    assert len(accs) == 2
    assert accs[0].username == "user1"
    assert accs[1].username == "user2"


async def test_save():
    remove_db()
    pool = AccountsPool(DB_FILE)

    # should save account
    await pool.add_account("user1", "pass1", "email1", "email_pass1")
    acc = await pool.get("user1")
    acc.password = "pass2"
    await pool.save(acc)
    acc = await pool.get("user1")
    assert acc.password == "pass2"

    # should not save account
    acc = await pool.get("user1")
    acc.username = "user2"
    await pool.save(acc)
    acc = await pool.get("user1")
    assert acc.username == "user1"


async def test_get_for_queue():
    remove_db()
    pool = AccountsPool(DB_FILE)
    Q = "test_queue"

    # should return account
    await pool.add_account("user1", "pass1", "email1", "email_pass1")
    await pool.set_active("user1", True)
    acc = await pool.get_for_queue(Q)
    assert acc is not None
    assert acc.username == "user1"
    assert acc.active is True
    assert acc.locks is not None
    assert Q in acc.locks
    assert acc.locks[Q] is not None

    # should return None
    acc = await pool.get_for_queue(Q)
    assert acc is None


async def test_account_unlock():
    remove_db()
    pool = AccountsPool(DB_FILE)
    Q = "test_queue"

    await pool.add_account("user1", "pass1", "email1", "email_pass1")
    await pool.set_active("user1", True)
    acc = await pool.get_for_queue(Q)
    assert acc is not None
    assert acc.locks[Q] is not None

    # should unlock account and make available for queue
    await pool.unlock(acc.username, Q)
    acc = await pool.get_for_queue(Q)
    assert acc is not None
    assert acc.locks[Q] is not None

    # should update lock time
    end_time = utc_ts() + 60  # + 1 minute
    await pool.lock_until(acc.username, Q, end_time)

    acc = await pool.get(acc.username)
    assert int(acc.locks[Q].timestamp()) == end_time


async def test_get_stats():
    remove_db()
    pool = AccountsPool(DB_FILE)
    Q = "search"

    # should return empty stats
    stats = await pool.stats()
    for k, v in stats.items():
        assert v == 0, f"{k} should be 0"

    # should increate total
    await pool.add_account("user1", "pass1", "email1", "email_pass1")
    stats = await pool.stats()
    assert stats["total"] == 1
    assert stats["active"] == 0

    # should increate active
    await pool.set_active("user1", True)
    stats = await pool.stats()
    assert stats["total"] == 1
    assert stats["active"] == 1

    # should update queue stats
    await pool.get_for_queue(Q)
    stats = await pool.stats()
    assert stats["total"] == 1
    assert stats["active"] == 1
    assert stats["locked_search"] == 1
