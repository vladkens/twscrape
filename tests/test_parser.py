import json
import os

from twscrape import API, gather
from twscrape.logger import set_log_level
from twscrape.models import Tweet, User, parse_tweet

BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "mocked-data")
os.makedirs(DATA_DIR, exist_ok=True)

set_log_level("DEBUG")


def load_mock(name: str):
    file = os.path.join(os.path.dirname(__file__), f"mocked-data/{name}.json")
    with open(file) as f:
        return json.load(f)


def fake_rep(fn: str, filename: str):
    if not filename.startswith("/"):
        filename = os.path.join(DATA_DIR, filename)

    if not filename.endswith(".json"):
        filename += ".json"

    with open(filename) as fp:
        data = fp.read()

    rep = lambda: None  # noqa: E731
    rep.text = data
    rep.json = lambda: json.loads(data)
    return rep


def mock_rep(obj, fn: str, filename: str | None = None):
    async def cb_rep(*args, **kwargs):
        return fake_rep(fn, filename or fn)

    setattr(obj, fn, cb_rep)


def mock_gen(obj, fn: str):
    async def cb_gen(*args, **kwargs):
        yield fake_rep(fn, fn)

    setattr(obj, fn, cb_gen)


def check_tweet(doc: Tweet | None):
    assert doc is not None
    assert doc.id is not None
    assert doc.id_str is not None
    assert isinstance(doc.id, int)
    assert isinstance(doc.id_str, str)
    assert doc.id == int(doc.id_str)

    assert doc.url is not None
    assert doc.id_str in doc.url
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

    if doc.media is not None:
        if len(doc.media.photos) > 0:
            assert doc.media.photos[0].url is not None

        if len(doc.media.videos) > 0:
            for x in doc.media.videos:
                assert x.thumbnailUrl is not None
                assert x.duration is not None
                for v in x.variants:
                    assert v.url is not None
                    assert v.bitrate is not None
                    assert v.contentType is not None

    if doc.retweetedTweet is not None:
        try:
            assert doc.rawContent.endswith(doc.retweetedTweet.rawContent), "content should be full"
        except AssertionError as e:
            print("\n" + "-" * 60)
            print(doc.url)
            print("1:", doc.rawContent)
            print("2:", doc.retweetedTweet.rawContent)
            print("-" * 60)
            raise e

    check_user(doc.user)


def check_user(doc: User):
    assert doc.id is not None
    assert doc.id_str is not None
    assert isinstance(doc.id, int)
    assert isinstance(doc.id_str, str)
    assert doc.id == int(doc.id_str)

    assert doc.username is not None
    assert doc.descriptionLinks is not None

    if len(doc.descriptionLinks) > 0:
        for x in doc.descriptionLinks:
            assert x.url is not None
            assert x.text is not None
            assert x.tcourl is not None

    obj = doc.dict()
    assert doc.id == obj["id"]
    assert doc.username == obj["username"]

    txt = doc.json()
    assert isinstance(txt, str)
    assert str(doc.id) in txt


async def test_search():
    api = API()
    mock_gen(api, "search_raw")

    items = await gather(api.search("elon musk lang:en", limit=20))
    assert len(items) > 0

    for doc in items:
        check_tweet(doc)


async def test_user_by_id():
    api = API()
    mock_rep(api, "user_by_id_raw")

    doc = await api.user_by_id(2244994945)
    assert doc is not None
    assert doc.id == 2244994945
    assert doc.username == "XDevelopers"

    obj = doc.dict()
    assert doc.id == obj["id"]
    assert doc.username == obj["username"]

    txt = doc.json()
    assert isinstance(txt, str)
    assert str(doc.id) in txt


async def test_user_by_login():
    api = API()
    mock_rep(api, "user_by_login_raw")

    doc = await api.user_by_login("xdevelopers")
    assert doc is not None
    assert doc.id == 2244994945
    assert doc.username == "XDevelopers"

    obj = doc.dict()
    assert doc.id == obj["id"]
    assert doc.username == obj["username"]

    txt = doc.json()
    assert isinstance(txt, str)
    assert str(doc.id) in txt


async def test_tweet_details():
    api = API()
    mock_rep(api, "tweet_details_raw")

    doc = await api.tweet_details(1649191520250245121)
    assert doc is not None, "tweet should not be None"
    check_tweet(doc)

    assert doc.id == 1649191520250245121
    assert doc.user is not None, "tweet.user should not be None"


async def test_followers():
    api = API()
    mock_gen(api, "followers_raw")

    users = await gather(api.followers(2244994945))
    assert len(users) > 0

    for doc in users:
        check_user(doc)


async def test_following():
    api = API()
    mock_gen(api, "following_raw")

    users = await gather(api.following(2244994945))
    assert len(users) > 0

    for doc in users:
        check_user(doc)


async def test_retweters():
    api = API()
    mock_gen(api, "retweeters_raw")

    users = await gather(api.retweeters(1649191520250245121))
    assert len(users) > 0

    for doc in users:
        check_user(doc)


async def test_favoriters():
    api = API()
    mock_gen(api, "favoriters_raw")

    users = await gather(api.favoriters(1649191520250245121))
    assert len(users) > 0

    for doc in users:
        check_user(doc)


async def test_user_tweets():
    api = API()
    mock_gen(api, "user_tweets_raw")

    tweets = await gather(api.user_tweets(2244994945))
    assert len(tweets) > 0

    for doc in tweets:
        check_tweet(doc)


async def test_user_tweets_and_replies():
    api = API()
    mock_gen(api, "user_tweets_and_replies_raw")

    tweets = await gather(api.user_tweets_and_replies(2244994945))
    assert len(tweets) > 0

    for doc in tweets:
        check_tweet(doc)


async def test_tweet_with_video():
    api = API()

    files = [
        ("manual_tweet_with_video_1.json", 1671508600538161153),
        ("manual_tweet_with_video_2.json", 1671753569412820992),
    ]

    for file, twid in files:
        mock_rep(api, "tweet_details_raw", file)
        doc = await api.tweet_details(twid)
        assert doc is not None
        check_tweet(doc)


async def test_issue_28():
    api = API()

    mock_rep(api, "tweet_details_raw", "_issue_28_1")
    doc = await api.tweet_details(1658409412799737856)
    assert doc is not None
    check_tweet(doc)

    assert doc.id == 1658409412799737856
    assert doc.user is not None

    assert doc.retweetedTweet is not None
    assert doc.retweetedTweet.viewCount is not None
    assert doc.viewCount is not None  # views should come from retweetedTweet
    assert doc.viewCount == doc.retweetedTweet.viewCount
    check_tweet(doc.retweetedTweet)

    mock_rep(api, "tweet_details_raw", "_issue_28_2")
    doc = await api.tweet_details(1658421690001502208)
    assert doc is not None
    check_tweet(doc)
    assert doc.id == 1658421690001502208
    assert doc.viewCount is not None

    assert doc.quotedTweet is not None
    assert doc.quotedTweet.id != doc.id
    check_tweet(doc.quotedTweet)
    assert doc.quotedTweet.viewCount is not None


async def test_issue_42():
    raw = load_mock("_issue_42")
    doc = parse_tweet(raw, 1665951747842641921)
    assert doc is not None
    assert doc.retweetedTweet is not None
    assert doc.rawContent is not None
    assert doc.retweetedTweet.rawContent is not None
    assert doc.rawContent.endswith(doc.retweetedTweet.rawContent)


async def test_issue_56():
    raw = load_mock("_issue_56")
    doc = parse_tweet(raw, 1682072224013099008)
    assert doc is not None
    assert len(set([x.tcourl for x in doc.links])) == len(doc.links)
    assert len(doc.links) == 5
