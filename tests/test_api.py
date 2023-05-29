from twscrape.api import API
from twscrape.logger import set_log_level
from twscrape.utils import gather

set_log_level("DEBUG")


class MockedError(Exception):
    pass


GQL_GEN = [
    "followers",
    "following",
    "retweeters",
    "favoriters",
    "user_tweets",
    "user_tweets_and_replies",
]


async def test_gql_params(api_mock: API, monkeypatch):
    for func in GQL_GEN:
        args = []

        def mock_gql_items(*a, **kw):
            args.append((a, kw))
            raise MockedError()

        try:
            monkeypatch.setattr(api_mock, "_gql_items", mock_gql_items)
            await gather(getattr(api_mock, func)("user1", limit=100, kv={"count": 100}))
        except MockedError:
            pass

        assert len(args) == 1, f"{func} not called once"
        assert args[0][1]["limit"] == 100, f"limit not changed in {func}"
        assert args[0][0][1]["count"] == 100, f"count not changed in {func}"
