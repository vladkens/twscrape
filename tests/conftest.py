import pytest

from twscrape.accounts_pool import AccountsPool
from twscrape.api import API
from twscrape.logger import set_log_level
from twscrape.queue_client import QueueClient

set_log_level("ERROR")


@pytest.fixture
def pool_mock(tmp_path):
    db_path = tmp_path / "test.db"
    yield AccountsPool(db_path)


@pytest.fixture
async def client_fixture(pool_mock: AccountsPool):
    pool_mock._order_by = "username"

    for x in range(1, 3):
        await pool_mock.add_account(f"user{x}", f"pass{x}", f"email{x}", f"email_pass{x}")
        await pool_mock.set_active(f"user{x}", True)

    client = QueueClient(pool_mock, "SearchTimeline")
    yield pool_mock, client


@pytest.fixture
async def api_mock(pool_mock: AccountsPool):
    await pool_mock.add_account("user1", "pass1", "email1", "email_pass1")
    await pool_mock.set_active("user1", True)

    api = API(pool_mock)
    yield api
