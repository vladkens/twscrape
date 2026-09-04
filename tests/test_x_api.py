import json
from pathlib import Path
from typing import Any, cast

import pytest

from twscrape.accounts_pool import NoAccountError
from twscrape.models import Tweet, parse_tweets, parse_user
from twscrape.x_api import (
    XApiNotFoundError,
    XApiService,
    XApiUnavailableError,
    parse_bool,
    parse_by,
    parse_limit,
    parse_uid,
    tweet_to_dict,
    user_to_dict,
)


class MockResponse:
    def __init__(self, source: str | dict[str, Any]):
        self.source = source

    def json(self):
        if isinstance(self.source, dict):
            return self.source
        path = Path(__file__).parent / "mocked-data" / self.source
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
    def __init__(self, tweets: list[Tweet], user=None, unavailable: dict[str, str] | None = None):
        self.tweets = tweets
        self.user = user
        self.unavailable = unavailable
        self.closed = False
        self.graph_method = None
        self.graph_uid = None
        self.lookups: list[tuple[str, str]] = []

    async def user_by_id_raw(self, uid: int):
        self.lookups.append(("id", str(uid)))
        return await self._user_response()

    async def _user_response(self):
        if self.unavailable is not None:
            return MockResponse(
                {
                    "data": {
                        "user": {"result": {"__typename": "UserUnavailable", **self.unavailable}}
                    }
                }
            )
        if self.user is None:
            return MockResponse({"data": {"user": {"result": {}}}})
        return MockResponse("raw_user_by_login.json")

    async def user_by_login_raw(self, username: str):
        self.lookups.append(("username", username))
        return await self._user_response()

    async def search(self, query: str, limit: int):
        try:
            for tweet in self.tweets:
                yield tweet
        finally:
            self.closed = True

    async def followers(self, user_id: int, limit: int):
        self.graph_method = "followers"
        self.graph_uid = user_id
        try:
            for _ in range(2):
                yield self.user
        finally:
            self.closed = True

    async def following(self, user_id: int, limit: int):
        self.graph_method = "following"
        self.graph_uid = user_id
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


async def test_suspended_user_is_reported_as_unavailable(pool_mock):
    service = XApiService(pool_mock)
    service.api = cast(
        Any,
        FakeAPI([], unavailable={"message": "User is suspended", "reason": "Suspended"}),
    )

    with pytest.raises(XApiUnavailableError) as caught:
        await service.user("suspended-user")

    assert str(caught.value) == 'User "suspended-user" is suspended'
    assert caught.value.reason == "Suspended"


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


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "username"), ("username", "username"), ("login", "username"), ("id", "id"), ("uid", "id")],
)
def test_parse_by(value: str | None, expected: str):
    assert parse_by(value) == expected


@pytest.mark.parametrize("value", ["", "handle", "ID2"])
def test_parse_by_rejects_unknown(value: str):
    with pytest.raises(ValueError):
        parse_by(value)


@pytest.mark.parametrize("value", ["abc", "0", "-1", ""])
def test_parse_uid_rejects_invalid(value: str):
    with pytest.raises(ValueError):
        parse_uid(value)


async def test_user_lookup_by_id(pool_mock):
    fake_api = FakeAPI([], user=sample_user())
    service = XApiService(pool_mock)
    service.api = cast(Any, fake_api)

    result = await service.user("1472481088304193541", by="id")

    assert result["username"] == "XDevelopers"
    assert fake_api.lookups == [("id", "1472481088304193541")]


async def test_social_graph_by_id_skips_user_lookup(pool_mock):
    fake_api = FakeAPI([], user=sample_user())
    service = XApiService(pool_mock)
    service.api = cast(Any, fake_api)

    result = await service.following("1472481088304193541", limit=2, by="id", skip_user=True)

    assert result["user"] is None
    assert result["count"] == 2
    assert fake_api.graph_uid == 1472481088304193541
    assert fake_api.lookups == []


async def test_social_graph_by_username_still_resolves_user(pool_mock):
    fake_api = FakeAPI([], user=sample_user())
    service = XApiService(pool_mock)
    service.api = cast(Any, fake_api)

    result = await service.following("xdevelopers", limit=2, skip_user=True)

    assert result["user"] is not None
    assert fake_api.lookups == [("username", "xdevelopers")]


async def test_social_graph_by_id_rejects_non_numeric(pool_mock):
    service = XApiService(pool_mock)
    service.api = cast(Any, FakeAPI([], user=sample_user()))

    with pytest.raises(ValueError):
        await service.following("not-a-number", limit=2, by="id", skip_user=True)


async def test_following_batch_preserves_order_and_isolates_user_errors(pool_mock, monkeypatch):
    service = XApiService(pool_mock)
    seen: list[str] = []

    async def social_graph(ident, limit, kind, by, skip_user):
        seen.append(ident)
        assert (limit, kind, by, skip_user) == (50, "following", "id", True)
        if ident == "2":
            raise XApiUnavailableError('User "2" is suspended', "Suspended")
        return {"users": [{"id": ident}], "count": 1}

    monkeypatch.setattr(service, "_social_graph", social_graph)
    result = await service.following_batch([1, 2, 3], 50)

    assert seen == ["1", "2", "3"]
    assert result["results"] == [
        {"id": "1", "ok": True, "users": [{"id": "1"}], "count": 1},
        {
            "id": "2",
            "ok": False,
            "error": 'User "2" is suspended',
            "status": 403,
            "reason": "suspended",
        },
        {"id": "3", "ok": True, "users": [{"id": "3"}], "count": 1},
    ]


async def test_following_batch_stops_on_pool_exhaustion(pool_mock, monkeypatch):
    service = XApiService(pool_mock)
    seen: list[str] = []

    async def social_graph(ident, limit, kind, by, skip_user):
        seen.append(ident)
        if ident == "2":
            raise NoAccountError("pool exhausted")
        return {"users": [], "count": 0}

    monkeypatch.setattr(service, "_social_graph", social_graph)

    with pytest.raises(NoAccountError):
        await service.following_batch([1, 2, 3], 50)
    assert seen == ["1", "2"]
