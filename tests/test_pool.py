from twscrape.accounts_pool import AccountsPool
from twscrape.utils import utc_ts


async def test_add_accounts(poolm: AccountsPool):
    # should add account
    await poolm.add_account("user1", "pass1", "email1", "email_pass1")
    acc = await poolm.get("user1")
    assert acc.username == "user1"
    assert acc.password == "pass1"
    assert acc.email == "email1"
    assert acc.email_password == "email_pass1"

    # should not add account with same username
    await poolm.add_account("user1", "pass2", "email2", "email_pass2")
    acc = await poolm.get("user1")
    assert acc.username == "user1"
    assert acc.password == "pass1"
    assert acc.email == "email1"
    assert acc.email_password == "email_pass1"

    # should not add account with different username case
    await poolm.add_account("USER1", "pass2", "email2", "email_pass2")
    acc = await poolm.get("user1")
    assert acc.username == "user1"
    assert acc.password == "pass1"
    assert acc.email == "email1"
    assert acc.email_password == "email_pass1"

    # should add account with different username
    await poolm.add_account("user2", "pass2", "email2", "email_pass2")
    acc = await poolm.get("user2")
    assert acc.username == "user2"
    assert acc.password == "pass2"
    assert acc.email == "email2"
    assert acc.email_password == "email_pass2"


async def test_get_all(poolm: AccountsPool):
    # should return empty list
    accs = await poolm.get_all()
    assert len(accs) == 0

    # should return all accounts
    await poolm.add_account("user1", "pass1", "email1", "email_pass1")
    await poolm.add_account("user2", "pass2", "email2", "email_pass2")
    accs = await poolm.get_all()
    assert len(accs) == 2
    assert accs[0].username == "user1"
    assert accs[1].username == "user2"


async def test_save(poolm: AccountsPool):
    # should save account
    await poolm.add_account("user1", "pass1", "email1", "email_pass1")
    acc = await poolm.get("user1")
    acc.password = "pass2"
    await poolm.save(acc)
    acc = await poolm.get("user1")
    assert acc.password == "pass2"

    # should not save account
    acc = await poolm.get("user1")
    acc.username = "user2"
    await poolm.save(acc)
    acc = await poolm.get("user1")
    assert acc.username == "user1"


async def test_get_for_queue(poolm: AccountsPool):
    Q = "test_queue"

    # should return account
    await poolm.add_account("user1", "pass1", "email1", "email_pass1")
    await poolm.set_active("user1", True)
    acc = await poolm.get_for_queue(Q)
    assert acc is not None
    assert acc.username == "user1"
    assert acc.active is True
    assert acc.locks is not None
    assert Q in acc.locks
    assert acc.locks[Q] is not None

    # should return None
    acc = await poolm.get_for_queue(Q)
    assert acc is None


async def test_account_unlock(poolm: AccountsPool):
    Q = "test_queue"

    await poolm.add_account("user1", "pass1", "email1", "email_pass1")
    await poolm.set_active("user1", True)
    acc = await poolm.get_for_queue(Q)
    assert acc is not None
    assert acc.locks[Q] is not None

    # should unlock account and make available for queue
    await poolm.unlock(acc.username, Q)
    acc = await poolm.get_for_queue(Q)
    assert acc is not None
    assert acc.locks[Q] is not None

    # should update lock time
    end_time = utc_ts() + 60  # + 1 minute
    await poolm.lock_until(acc.username, Q, end_time)

    acc = await poolm.get(acc.username)
    assert int(acc.locks[Q].timestamp()) == end_time


async def test_get_stats(poolm: AccountsPool):
    Q = "search"

    # should return empty stats
    stats = await poolm.stats()
    for k, v in stats.items():
        assert v == 0, f"{k} should be 0"

    # should increate total
    await poolm.add_account("user1", "pass1", "email1", "email_pass1")
    stats = await poolm.stats()
    assert stats["total"] == 1
    assert stats["active"] == 0

    # should increate active
    await poolm.set_active("user1", True)
    stats = await poolm.stats()
    assert stats["total"] == 1
    assert stats["active"] == 1

    # should update queue stats
    await poolm.get_for_queue(Q)
    stats = await poolm.stats()
    assert stats["total"] == 1
    assert stats["active"] == 1
    assert stats["locked_search"] == 1
