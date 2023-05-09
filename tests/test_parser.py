import asyncio
import json
import os

from twscrape import API, AccountsPool, gather
from twscrape.logger import set_log_level

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

    for doc in items:
        assert doc.id is not None
        assert doc.user is not None

        obj = doc.dict()
        assert doc.id == obj["id"]
        assert doc.user.id == obj["user"]["id"]

        assert "url" in obj
        assert "_type" in obj
        assert obj["_type"] == "snscrape.modules.twitter.Tweet"

        assert "url" in obj["user"]
        assert "_type" in obj["user"]
        assert obj["user"]["_type"] == "snscrape.modules.twitter.User"

        txt = doc.json()
        assert isinstance(txt, str)
        assert str(doc.id) in txt


async def test_user_by_id():
    api = API(AccountsPool())
    mock_rep(api, "user_by_id_raw")

    doc = await api.user_by_id(2244994945)
    assert doc.id == 2244994945
    assert doc.username == "TwitterDev"

    obj = doc.dict()
    assert doc.id == obj["id"]
    assert doc.username == obj["username"]

    txt = doc.json()
    assert isinstance(txt, str)
    assert str(doc.id) in txt


async def test_user_by_login():
    api = API(AccountsPool())
    mock_rep(api, "user_by_login_raw")

    doc = await api.user_by_login("twitterdev")
    assert doc.id == 2244994945
    assert doc.username == "TwitterDev"

    obj = doc.dict()
    assert doc.id == obj["id"]
    assert doc.username == obj["username"]

    txt = doc.json()
    assert isinstance(txt, str)
    assert str(doc.id) in txt


async def test_tweet_details():
    api = API(AccountsPool())
    mock_rep(api, "tweet_details_raw")

    doc = await api.tweet_details(1649191520250245121)
    assert doc.id == 1649191520250245121
    assert doc.user is not None

    obj = doc.dict()
    assert doc.id == obj["id"]
    assert doc.user.id == obj["user"]["id"]

    txt = doc.json()
    assert isinstance(txt, str)
    assert str(doc.id) in txt


async def test_followers():
    api = API(AccountsPool())
    mock_gen(api, "followers_raw")

    users = await gather(api.followers(2244994945))
    assert len(users) > 0

    for doc in users:
        assert doc.id is not None
        assert doc.username is not None

        obj = doc.dict()
        assert doc.id == obj["id"]
        assert doc.username == obj["username"]

        txt = doc.json()
        assert isinstance(txt, str)
        assert str(doc.id) in txt


async def test_following():
    api = API(AccountsPool())
    mock_gen(api, "following_raw")

    users = await gather(api.following(2244994945))
    assert len(users) > 0

    for doc in users:
        assert doc.id is not None
        assert doc.username is not None

        obj = doc.dict()
        assert doc.id == obj["id"]
        assert doc.username == obj["username"]

        txt = doc.json()
        assert isinstance(txt, str)
        assert str(doc.id) in txt


async def test_retweters():
    api = API(AccountsPool())
    mock_gen(api, "retweeters_raw")

    users = await gather(api.retweeters(1649191520250245121))
    assert len(users) > 0

    for doc in users:
        assert doc.id is not None
        assert doc.username is not None

        obj = doc.dict()
        assert doc.id == obj["id"]
        assert doc.username == obj["username"]

        txt = doc.json()
        assert isinstance(txt, str)
        assert str(doc.id) in txt


async def test_favoriters():
    api = API(AccountsPool())
    mock_gen(api, "favoriters_raw")

    users = await gather(api.favoriters(1649191520250245121))
    assert len(users) > 0

    for doc in users:
        assert doc.id is not None
        assert doc.username is not None

        obj = doc.dict()
        assert doc.id == obj["id"]
        assert doc.username == obj["username"]

        txt = doc.json()
        assert isinstance(txt, str)
        assert str(doc.id) in txt


async def test_user_tweets():
    api = API(AccountsPool())
    mock_gen(api, "user_tweets_raw")

    tweets = await gather(api.user_tweets(2244994945))
    assert len(tweets) > 0

    for doc in tweets:
        assert doc.id is not None
        assert doc.user is not None

        obj = doc.dict()
        assert doc.id == obj["id"]
        assert doc.user.id == obj["user"]["id"]

        txt = doc.json()
        assert isinstance(txt, str)
        assert str(doc.id) in txt


async def test_user_tweets_and_replies():
    api = API(AccountsPool())
    mock_gen(api, "user_tweets_and_replies_raw")

    tweets = await gather(api.user_tweets_and_replies(2244994945))
    assert len(tweets) > 0

    for doc in tweets:
        assert doc.id is not None
        assert doc.user is not None

        obj = doc.dict()
        assert doc.id == obj["id"]
        assert doc.user.id == obj["user"]["id"]

        txt = doc.json()
        assert isinstance(txt, str)
        assert str(doc.id) in txt


async def main():
    # prepare mock files from real twitter replies
    # you need to have some account to perform this
    FRESH = False

    pool = AccountsPool()
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
        if os.path.exists(filename) and FRESH is False:
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
