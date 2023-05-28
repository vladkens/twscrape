import pytest

from twscrape.accounts_pool import AccountsPool
from twscrape.queue_client import QueueClient


@pytest.fixture
def poolm(tmp_path) -> AccountsPool:  # type: ignore
    db_path = tmp_path / "test.db"
    yield AccountsPool(db_path)


@pytest.fixture
async def client_fixture(poolm: AccountsPool):
    await poolm.add_account("user1", "pass1", "email1", "email_pass1")
    await poolm.add_account("user2", "pass2", "email2", "email_pass2")
    await poolm.set_active("user1", True)
    await poolm.set_active("user2", True)

    client = QueueClient(poolm, "search")
    yield poolm, client
