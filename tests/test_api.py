import json
import os

import pytest

from twscrape.account import Account
from twscrape.accounts_pool import NoAccountError
from twscrape.api import API
from twscrape.queue_client import AbortReqError, ApiError
from twscrape.utils import gather, get_env_bool

from .mock_http import MockClient

DATA_DIR = os.path.join(os.path.dirname(__file__), "mocked-data")

CLOUDFLARE_BLOCK = {
    "status_code": 403,
    "text": "<html>blocked</html>",
    "headers": {"content-type": "text/html", "cf-ray": "abc123"},
}
# Seen in production: "API unknown error: 200 - ... - (-1) DeadlineExceeded: Unspecified"
DEADLINE_EXCEEDED = {"json": {"errors": [{"code": -1, "message": "DeadlineExceeded: Unspecified"}]}}


class MockedError(Exception):
    pass


def load(name: str) -> dict:
    with open(os.path.join(DATA_DIR, f"{name}.json")) as f:
        return json.load(f)


@pytest.fixture
def api_http(api_mock: API, monkeypatch):
    mock = MockClient()
    monkeypatch.setattr(Account, "make_client", lambda self, proxy=None: mock)
    return api_mock, mock


GQL_GEN = [
    "search",
    "tweet_replies",
    "tweet_thread",
    "retweeters",
    "followers",
    "following",
    "user_tweets",
    "user_tweets_and_replies",
    "list_timeline",
    "trends",
    "list_members",
    "community_members",
    "community_moderators",
    "community_tweets",
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
        # Parsed generators count unique items, so raw pagination runs until
        # enough distinct results have passed the parser.
        assert args[0][1]["limit"] == -1, f"raw limit not disabled in {func}"
        assert args[0][0][1]["count"] == 100, f"count not changed in {func}"


async def test_tweet_details_article_toggles(api_mock: API, monkeypatch):
    args = []

    async def mock_gql_item(*a, **kw):
        args.append((a, kw))

    monkeypatch.setattr(api_mock, "_gql_item", mock_gql_item)
    await api_mock.tweet_details_raw(2075503860689281453)

    assert len(args) == 1
    assert args[0][1]["field_toggles"] == {
        "withArticleRichContentState": True,
        "withArticlePlainText": False,
        "withArticleSummaryText": True,
        "withArticleVoiceOver": True,
        "withGrokAnalyze": False,
        "withDisallowedReplyControls": False,
    }


async def test_raise_when_no_account(api_mock: API):
    await api_mock.pool.delete_accounts(["user1"])
    assert len(await api_mock.pool.get_all()) == 0

    assert get_env_bool("TWS_RAISE_WHEN_NO_ACCOUNT") is False
    os.environ["TWS_RAISE_WHEN_NO_ACCOUNT"] = "1"
    assert get_env_bool("TWS_RAISE_WHEN_NO_ACCOUNT") is True

    with pytest.raises(NoAccountError):
        await gather(api_mock.search("foo", limit=10))

    with pytest.raises(NoAccountError):
        await api_mock.user_by_id(123)

    del os.environ["TWS_RAISE_WHEN_NO_ACCOUNT"]
    assert get_env_bool("TWS_RAISE_WHEN_NO_ACCOUNT") is False


# https://github.com/vladkens/twscrape/issues/346
# A failed request must raise; None (or an empty generator) is kept for X's own
# "no data" answers, recorded from X in the _issue_346_*.json files.


@pytest.mark.parametrize(
    "method,arg,data",
    [
        ("user_by_id", 1, "_issue_346_user_by_id_not_found"),
        ("user_by_login", "coalition_peaks", "_issue_346_user_by_login_not_found"),
        ("user_by_id", 17161988, "_issue_346_user_suspended"),
    ],
)
async def test_user_lookup_returns_none_when_x_has_no_user(api_http, method, arg, data):
    api, mock = api_http
    mock.add_response(json=load(data))

    assert await getattr(api, method)(arg) is None


@pytest.mark.parametrize(
    "response,error",
    [(CLOUDFLARE_BLOCK, AbortReqError), (DEADLINE_EXCEEDED, ApiError)],
)
@pytest.mark.parametrize("method,arg", [("user_by_id", 123), ("user_by_login", "someone")])
async def test_user_lookup_raises_when_request_fails(api_http, method, arg, response, error):
    api, mock = api_http
    mock.add_response(**response)

    with pytest.raises(error):
        await getattr(api, method)(arg)


async def test_user_tweets_of_unavailable_user_ends_without_error(api_http):
    # Protected or suspended account: X answers with UserUnavailable and no timeline
    api, mock = api_http
    mock.add_response(json=load("_issue_346_user_tweets_unavailable"))

    assert await gather(api.user_tweets(123)) == []


@pytest.mark.parametrize(
    "response,error",
    [(CLOUDFLARE_BLOCK, AbortReqError), (DEADLINE_EXCEEDED, ApiError)],
)
async def test_user_tweets_raises_when_page_fails_mid_pagination(api_http, response, error):
    api, mock = api_http
    mock.add_response(json=load("raw_user_tweets"))  # has a Bottom cursor
    mock.add_response(**response)

    tweets = []
    with pytest.raises(error):
        async for tweet in api.user_tweets(123):
            tweets.append(tweet)

    # the caller keeps what was yielded before the failure
    assert len(tweets) == 21
    assert mock._queue == []
