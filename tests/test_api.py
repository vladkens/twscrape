import os
from typing import Any
from typing import AsyncContextManager
from typing import Callable
from typing import Collection
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Type
from typing import Union

import pytest
from pytest_mock import MockerFixture
from _pytest.monkeypatch import MonkeyPatch
from twscrape.accounts_pool import NoAccountError
from twscrape.api import API
from twscrape.logger import set_log_level
from twscrape.utils import gather

set_log_level("DEBUG")


class MockedError(Exception):
    pass


GQL_GEN: List[str] = [
    "search",
    "tweet_replies",
    "retweeters",
    "favoriters",
    "followers",
    "following",
    "user_tweets",
    "user_tweets_and_replies",
    "list_timeline",
    "liked_tweets",
]


async def test_gql_params(api_mock: API, monkeypatch: MonkeyPatch) -> None:
    calls: List[Tuple[Tuple[Any, Dict[str, Any]], Dict[str, Any]]] = []

    async def mock_gql_items(*args: Tuple[Any, Dict[str, Any]], **kwargs: Any) -> None:
        nonlocal calls
        calls.append((args, kwargs))
        raise MockedError()

    for func in GQL_GEN:
        monkeypatch.setattr(api_mock, "_gql_items", mock_gql_items)
        try:
            await gather(getattr(api_mock, func)("user1", limit=100, kv={"count": 100}))
        except MockedError:
            pass

    monkeypatch.undo()

    assert len(calls) == 1, f"{func} not called once"
    assert calls[0][1]["limit"] == 100, f"limit not changed in {func}"
    assert calls[0][0][1]["count"] == 100, f"count not changed in {func}"


@pytest.fixture
async def api_mock() -> Type[API]:
    class MockAPI(API):
        async def _gql_items(self, *args: Tuple[Any, Dict[str, Any]], **kwargs: Any) -> None:
            pass

    return MockAPI()


@pytest.fixture
async def api_session() -> AsyncContextManager[API]:
    api = API()
    yield api
    await api.close()


async def test_raise_when_no_account(
    api_session: API, monkeypatch: MockerFixture
) -> None:
    monkeypatch.setattr(api_session, "pool", MockPool())
    monkeypatch.setattr(api_session.pool, "get_all", lambda: [])

    env_var_name = "TWS_RAISE_WHEN_NO_ACCOUNT"
    assert get_env_bool(env_var_name) is False

    monkeypatch.setenv(env_var_name, "1")
    assert get_env_bool(env_var_name) is True

    with pytest.raises(NoAccountError):
        await gather(api_session.search("foo", limit=10))

    with pytest.raises(NoAccountError):
        await api_session.user_by_id(123)

    monkeypatch.delenv(env_var_name)
    assert get_env_bool(env_var_name) is False


class MockPool:
    async def delete_accounts(self, accounts: Collection[str]) -> None:
        pass

    async def get_all(self) -> List[str]:
        pass


def get_env_bool(name: str) -> bool:
    return os.environ.get(name, "0") == "1"
