import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from twscrape.accounts_pool import AccountsPool
from twscrape.api import API
from twscrape.queue_client import QueueClient


@pytest.fixture
def pool_mock(tmp_path):
    """
    Creates a temporary database and returns an instance of `AccountsPool`.
    """
    db_path = tmp_path / "test.db"
    return AccountsPool(db_path)


@pytest.fixture(scope="module")
@pytest.mark.asyncio(record_messages=True)
async def client_fixture(pool_mock: AccountsPool):
    """
    Sets up the `AccountsPool` with some test data and returns an instance of `QueueClient`.
    """
    pool_mock._order_by = "username"

    for x in range(1, 3):
        await pool_mock.add_account(f"user{x}", f"pass{x}", f"email{x}", f"email_pass{x}")
        await pool_mock.set_active(f"user{x}", True)

    client = QueueClient(pool_mock, "SearchTimeline")
    await client.start()
    yield from asyncio.gather(client.run())
    await client.stop()


@pytest.fixture(scope="function")
@pytest.mark.asyncio
async def api_mock(pool_mock: AccountsPool):
    """
    Sets up the `AccountsPool` with some test data and returns an instance of `API`.
    """
    await pool_mock.add_account("user1", "pass1", "email1", "email_pass1")
    await pool_mock.set_active("user1", True)

    with patch("twscrape.api.API.request", new_callable=AsyncMock) as mock_request:
        api = API(pool_mock)
        yield api
