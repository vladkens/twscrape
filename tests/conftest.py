import pytest

from twscrape.accounts_pool import AccountsPool
from twscrape.api import API
from twscrape.queue_client import QueueClient


@pytest.fixture
def pool_mock(tmp_path) -> AccountsPool:  # type: ignore
    db_path = tmp_path / "test.db"
    yield AccountsPool(db_path)


@pytest.fixture
async def client_fixture(pool_mock: AccountsPool):
    await pool_mock.add_account("user1", "pass1", "email1", "email_pass1")
    await pool_mock.add_account("user2", "pass2", "email2", "email_pass2")
    await pool_mock.set_active("user1", True)
    await pool_mock.set_active("user2", True)

    client = QueueClient(pool_mock, "search")
    yield pool_mock, client


@pytest.fixture
async def api_mock(pool_mock: AccountsPool):
    await pool_mock.add_account("user1", "pass1", "email1", "email_pass1")
    await pool_mock.set_active("user1", True)

    api = API(pool_mock)
    yield api
