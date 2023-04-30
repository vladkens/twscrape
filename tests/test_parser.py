import asyncio
import json
import os

from twapi import API, AccountsPool, gather
from twapi.logger import set_log_level

BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "mocked-data")
os.makedirs(DATA_DIR, exist_ok=True)

set_log_level("DEBUG")


class Files:
    search_raw = "search_raw.json"
    user_by_id_raw = "user_by_id_raw.json"
    user_by_login_raw = "user_by_login_raw.json"
    tweet_details_raw = "tweet_details_raw.json"
    followers_raw = "followers_raw.json"
    following_raw = "following_raw.json"
    retweeters_raw = "retweeters_raw.json"
    favoriters_raw = "favoriters_raw.json"
    user_tweets_raw = "user_tweets_raw.json"
    user_tweets_and_replies_raw = "user_tweets_and_replies_raw.json"


def fake_rep(fn: str):
    filename = os.path.join(DATA_DIR, getattr(Files, fn))

    with open(filename) as fp:
        data = fp.read()

    rep = lambda: None  # noqa: E731
    rep.text = data
    rep.json = lambda: json.loads(data)
    return rep


def mock_rep(obj, fn: str):
    async def cb_rep(*args, **kwargs):
        return fake_rep(fn)

    setattr(obj, fn, cb_rep)


def mock_gen(obj, fn: str):
    async def cb_gen(*args, **kwargs):
        yield fake_rep(fn)

    setattr(obj, fn, cb_gen)


async def test_search():
    api = API(AccountsPool())
    mock_gen(api, "search_raw")

    items = await gather(api.search("elon musk lang:en", limit=20))
    assert len(items) > 0

    for x in items:
        assert x.id is not None
        assert x.user is not None

        tw_dict = x.json()
        assert x.id == tw_dict["id"]
        assert x.user.id == tw_dict["user"]["id"]


async def test_user_by_id():
    api = API(AccountsPool())
    mock_rep(api, "user_by_id_raw")

    rep = await api.user_by_id(2244994945)
    assert rep.id == 2244994945
    assert rep.username == "TwitterDev"

    obj = rep.json()
    assert rep.id == obj["id"]
    assert rep.username == obj["username"]


async def test_user_by_login():
    api = API(AccountsPool())
    mock_rep(api, "user_by_login_raw")

    rep = await api.user_by_login("twitterdev")
    assert rep.id == 2244994945
    assert rep.username == "TwitterDev"

    obj = rep.json()
    assert rep.id == obj["id"]
    assert rep.username == obj["username"]


async def test_tweet_details():
    api = API(AccountsPool())
    mock_rep(api, "tweet_details_raw")

    rep = await api.tweet_details(1649191520250245121)
    assert rep.id == 1649191520250245121
    assert rep.user is not None

    obj = rep.json()
    assert rep.id == obj["id"]
    assert rep.user.id == obj["user"]["id"]


async def test_followers():
    api = API(AccountsPool())
    mock_gen(api, "followers_raw")

    users = await gather(api.followers(2244994945))
    assert len(users) > 0

    for user in users:
        assert user.id is not None
        assert user.username is not None

        obj = user.json()
        assert user.id == obj["id"]
        assert user.username == obj["username"]


async def test_following():
    api = API(AccountsPool())
    mock_gen(api, "following_raw")

    users = await gather(api.following(2244994945))
    assert len(users) > 0

    for user in users:
        assert user.id is not None
        assert user.username is not None

        obj = user.json()
        assert user.id == obj["id"]
        assert user.username == obj["username"]


async def test_retweters():
    api = API(AccountsPool())
    mock_gen(api, "retweeters_raw")

    users = await gather(api.retweeters(1649191520250245121))
    assert len(users) > 0

    for user in users:
        assert user.id is not None
        assert user.username is not None

        obj = user.json()
        assert user.id == obj["id"]
        assert user.username == obj["username"]


async def test_favoriters():
    api = API(AccountsPool())
    mock_gen(api, "favoriters_raw")

    users = await gather(api.favoriters(1649191520250245121))
    assert len(users) > 0

    for user in users:
        assert user.id is not None
        assert user.username is not None

        obj = user.json()
        assert user.id == obj["id"]
        assert user.username == obj["username"]


async def test_user_tweets():
    api = API(AccountsPool())
    mock_gen(api, "user_tweets_raw")

    tweets = await gather(api.user_tweets(2244994945))
    assert len(tweets) > 0

    for tweet in tweets:
        assert tweet.id is not None
        assert tweet.user is not None

        obj = tweet.json()
        assert tweet.id == obj["id"]
        assert tweet.user.id == obj["user"]["id"]


async def test_user_tweets_and_replies():
    api = API(AccountsPool())
    mock_gen(api, "user_tweets_and_replies_raw")

    tweets = await gather(api.user_tweets_and_replies(2244994945))
    assert len(tweets) > 0

    for tweet in tweets:
        assert tweet.id is not None
        assert tweet.user is not None

        obj = tweet.json()
        assert tweet.id == obj["id"]
        assert tweet.user.id == obj["user"]["id"]


async def main():
    # prepare mock files from real twitter replies
    # you need to have some account to perform this

    pool = AccountsPool()
    pool.load_from_dir()

    api = API(pool)

    jobs = [
        (Files.search_raw, lambda: api.search_raw("elon musk lang:en", limit=20)),
        (Files.user_by_id_raw, lambda: api.user_by_id_raw(2244994945)),
        (Files.user_by_login_raw, lambda: api.user_by_login_raw("twitterdev")),
        (Files.tweet_details_raw, lambda: api.tweet_details_raw(1649191520250245121)),
        (Files.followers_raw, lambda: api.followers_raw(2244994945)),
        (Files.following_raw, lambda: api.following_raw(2244994945)),
        (Files.retweeters_raw, lambda: api.retweeters_raw(1649191520250245121)),
        (Files.favoriters_raw, lambda: api.favoriters_raw(1649191520250245121)),
        (Files.user_tweets_raw, lambda: api.user_tweets_raw(2244994945)),
        (Files.user_tweets_and_replies_raw, lambda: api.user_tweets_and_replies_raw(2244994945)),
    ]

    for filename, fn in jobs:
        filename = os.path.join(DATA_DIR, f"{filename}")
        print("-" * 20)
        if os.path.exists(filename):
            print(f"File {filename} already exists")
            continue

        print(f"Getting data for {filename}")

        rep = fn()
        is_coroutine = getattr(rep, "__aiter__", None) is None

        data = None
        if is_coroutine:
            data = await rep
        else:
            async for x in rep:
                data = x
                break

        if data is None:
            print(f"Failed to get data for {filename}")
            continue

        with open(filename, "w") as fp:
            fp.write(data.text)


if __name__ == "__main__":
    asyncio.run(main())
