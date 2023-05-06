import os

from twscrape.accounts_pool import AccountsPool
from twscrape.db import DB

DB_FILE = "/tmp/twapi_test.db"


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
