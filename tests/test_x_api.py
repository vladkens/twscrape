import json
from pathlib import Path
from typing import Any, cast

import pytest

from twscrape.models import Tweet, parse_tweets, parse_user
from twscrape.x_api import (
    XApiNotFoundError,
    XApiService,
    parse_bool,
    parse_limit,
    tweet_to_dict,
    user_to_dict,
)


class MockResponse:
    def __init__(self, filename: str):
        self.filename = filename

    def json(self):
        path = Path(__file__).parent / "mocked-data" / self.filename
        return json.loads(path.read_text())


def sample_user():
    user = parse_user(cast(Any, MockResponse("raw_user_by_login.json")))
    assert user is not None
    return user


def sample_tweet() -> Tweet:
    return next(parse_tweets(cast(Any, MockResponse("raw_search.json"))))


@pytest.mark.parametrize(
    ("value", "expected"), [(None, 20), ("1", 1), ("200", 200), ("true", None)]
)
def test_parse_limit(value: str | None, expected: int | None):
    if expected is None:
        with pytest.raises(ValueError):
            parse_limit(value)
    else:
        assert parse_limit(value) == expected


@pytest.mark.parametrize("value", ["0", "201", "-1"])
def test_parse_limit_range(value: str):
    with pytest.raises(ValueError):
        parse_limit(value)


@pytest.mark.parametrize(
    ("value", "expected"), [(None, False), ("true", True), ("1", True), ("false", False)]
)
def test_parse_bool(value: str | None, expected: bool):
    assert parse_bool(value) is expected


def test_serializers_return_json_safe_public_shapes():
    user = user_to_dict(sample_user())
    tweet = tweet_to_dict(sample_tweet())

    assert user["username"] == "XDevelopers"
    assert isinstance(user["id"], str)
    assert tweet["id"]
    assert tweet["user"]["username"]
    assert "cookies" not in json.dumps({"user": user, "tweet": tweet})
    json.dumps({"user": user, "tweet": tweet})


class FakeAPI:
    def __init__(self, tweets: list[Tweet], user=None):
        self.tweets = tweets
        self.user = user
        self.closed = False
        self.graph_method = None

    async def user_by_login(self, username: str):
        return self.user

    async def search(self, query: str, limit: int):
        try:
            for tweet in self.tweets:
                yield tweet
        finally:
            self.closed = True

    async def followers(self, user_id: int, limit: int):
        self.graph_method = "followers"
        try:
            for _ in range(2):
                yield self.user
        finally:
            self.closed = True

    async def following(self, user_id: int, limit: int):
        self.graph_method = "following"
        try:
            for _ in range(2):
                yield self.user
        finally:
            self.closed = True


async def test_search_enforces_exact_limit_and_closes_generator(pool_mock):
    fake_api = FakeAPI([sample_tweet(), sample_tweet()])
    service = XApiService(pool_mock)
    service.api = cast(Any, fake_api)

    result = await service.search("python", limit=1)

    assert result["query"] == "python"
    assert result["count"] == 1
    assert len(result["tweets"]) == 1
    assert fake_api.closed is True


async def test_user_not_found(pool_mock):
    service = XApiService(pool_mock)
    service.api = cast(Any, FakeAPI([]))

    with pytest.raises(XApiNotFoundError):
        await service.user("missing")


@pytest.mark.parametrize("kind", ["followers", "following"])
async def test_social_graph_enforces_limit_and_closes_generator(pool_mock, kind: str):
    fake_api = FakeAPI([], user=sample_user())
    service = XApiService(pool_mock)
    service.api = cast(Any, fake_api)

    result = await getattr(service, kind)("xdevelopers", limit=1)

    assert result["kind"] == kind
    assert result["count"] == 1
    assert len(result["users"]) == 1
    assert result["users"][0]["username"] == "XDevelopers"
    assert fake_api.graph_method == kind
    assert fake_api.closed is True
