import json
import os
from typing import Any, Callable, cast

from twscrape import API, gather
from twscrape.models import (
    AudiospaceCard,
    BroadcastCard,
    PollCard,
    SummaryCard,
    Trend,
    Tweet,
    User,
    UserRef,
    parse_tweet,
    parse_tweets,
)

BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "mocked-data")
os.makedirs(DATA_DIR, exist_ok=True)


def get_api():
    api = API()
    # To be sure all tests are mocked
    api.pool = None  # type: ignore
    return api


class FakeRep:
    text: str

    def __init__(self, text: str):
        self.text = text

    def json(self):
        return json.loads(self.text)


def fake_rep(filename: str):
    filename = filename if filename.endswith(".json") else f"{filename}.json"
    filename = filename if filename.startswith("/") else os.path.join(DATA_DIR, filename)

    with open(filename) as fp:
        return FakeRep(fp.read())


def mock_rep(fn: Callable[..., Any], filename: str, as_generator=False):
    rep = fake_rep(filename)

    async def cb_rep(*args, **kwargs):
        return rep

    async def cb_gen(*args, **kwargs):
        yield rep

    owner = getattr(fn, "__self__")
    name = getattr(fn, "__name__")
    cb = cast(Any, cb_gen if as_generator else cb_rep)
    cb.__name__ = name
    cb.__self__ = owner
    setattr(owner, name, cb)


def check_tweet(doc: Tweet | None):
    assert doc is not None
    assert isinstance(doc.id, int)
    assert isinstance(doc.id_str, str)
    assert str(doc.id) == doc.id_str

    assert doc.url is not None
    assert doc.id_str in doc.url
    assert doc.user is not None

    assert isinstance(doc.conversationId, int)
    assert isinstance(doc.conversationIdStr, str)
    assert str(doc.conversationId) == doc.conversationIdStr

    if doc.inReplyToTweetId is not None:
        assert isinstance(doc.inReplyToTweetId, int)
        assert isinstance(doc.inReplyToTweetIdStr, str)
        assert str(doc.inReplyToTweetId) == doc.inReplyToTweetIdStr

    if doc.inReplyToUser:
        check_user_ref(doc.inReplyToUser)

    if doc.mentionedUsers:
        for x in doc.mentionedUsers:
            check_user_ref(x)

    obj = doc.dict()
    assert doc.id == obj["id"]
    assert doc.id_str == obj["id_str"]
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
    assert doc.bookmarkedCount is not None


def check_user(doc: User):
    assert doc.id is not None
    assert isinstance(doc.id, int)
    assert isinstance(doc.id_str, str)
    assert str(doc.id) == doc.id_str

    assert doc.username is not None
    assert isinstance(doc.profileImageUrl, str)
    assert doc.profileImageUrl != ""
    assert doc.descriptionLinks is not None
    assert doc.pinnedIds is not None
    if doc.pinnedIds:
        for x in doc.pinnedIds:
            assert isinstance(x, int)

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


def collect_tweet_users(doc: Tweet | None):
    if doc is None:
        return []

    users = [doc.user]
    if doc.retweetedTweet is not None:
        users.extend(collect_tweet_users(doc.retweetedTweet))
    if doc.quotedTweet is not None:
        users.extend(collect_tweet_users(doc.quotedTweet))
    return users


def check_user_field_coverage(users: list[User]):
    assert len(users) > 0
    assert any(x.location != "" for x in users)
    assert any(x.profileBannerUrl is not None for x in users)
    assert any(isinstance(x.protected, bool) for x in users)
    assert any(isinstance(x.verified, bool) for x in users)
    assert any(x.blueType is not None for x in users)


def check_user_ref(doc: UserRef):
    assert isinstance(doc.id, int)
    assert isinstance(doc.id_str, str)
    assert str(doc.id) == doc.id_str

    assert doc.username is not None
    assert doc.displayname is not None

    obj = doc.dict()
    assert doc.id == obj["id"]
    assert doc.id_str == obj["id_str"]


def check_trend(doc: Trend):
    assert doc.name is not None
    assert doc.trend_url is not None
    assert doc.trend_metadata is not None
    assert isinstance(doc.grouped_trends, list) or doc.grouped_trends is None

    assert doc.trend_url.url is not None
    assert doc.trend_url.urlType is not None


async def test_search():
    api = get_api()
    mock_rep(api.search_raw, "raw_search", as_generator=True)

    items = await gather(api.search("elon musk lang:en", limit=20))
    assert len(items) > 0

    bookmarks_count = 0
    users = []
    for doc in items:
        check_tweet(doc)
        bookmarks_count += doc.bookmarkedCount
        users.extend(collect_tweet_users(doc))

    assert bookmarks_count > 0, (
        "`bookmark_fields` key is changed or unlucky search data. "
        "Run: uv run scripts/update_mocked_data.py --only search"
    )
    check_user_field_coverage(users)


async def test_user_by_login():
    api = get_api()
    mock_rep(api.user_by_login_raw, "raw_user_by_login")

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


async def test_user_about():
    api = get_api()
    mock_rep(api.user_about_raw, "raw_user_about")

    doc = await api.user_about("xdevelopers")
    assert doc is not None
    assert doc.screen_name == "XDevelopers"
    assert isinstance(doc.rest_id, int)
    assert isinstance(doc.name, str) and len(doc.name) > 0
    assert doc.account_based_in is not None
    assert doc.location_accurate is not None
    assert doc.affiliate_username is not None
    assert doc.source is not None
    assert isinstance(doc.username_changes, int)
    assert isinstance(doc.username_last_changed_at, int)
    assert doc.is_identity_verified is not None
    assert isinstance(doc.verified_since_msec, int)

    obj = doc.dict()
    assert doc.screen_name == obj["screen_name"]

    txt = doc.json()
    assert isinstance(txt, str)
    assert doc.screen_name in txt


async def test_tweet_details():
    api = get_api()
    mock_rep(api.tweet_details_raw, "raw_tweet_details")

    doc = await api.tweet_details(1649191520250245121)
    assert doc is not None, "tweet should not be None"
    check_tweet(doc)

    assert doc.id == 1649191520250245121
    assert doc.user is not None, "tweet.user should not be None"
    check_user_field_coverage(collect_tweet_users(doc))


async def test_tweet_replies():
    api = get_api()
    mock_rep(api.tweet_replies_raw, "raw_tweet_replies", as_generator=True)

    twid = 1649191520250245121
    tweets = await gather(api.tweet_replies(twid, limit=20))
    assert len(tweets) > 0

    for doc in tweets:
        check_tweet(doc)
        assert doc.inReplyToTweetId == twid


async def test_tweet_thread():
    api = get_api()
    mock_rep(api.tweet_thread_raw, "raw_tweet_thread", as_generator=True)

    twid = 1649191520250245121
    tweets = await gather(api.tweet_thread(twid, limit=20))
    assert len(tweets) > 0

    for doc in tweets:
        check_tweet(doc)
        assert doc.conversationId == twid


async def test_followers():
    api = get_api()
    mock_rep(api.followers_raw, "raw_followers", as_generator=True)

    users = await gather(api.followers(2244994945))
    assert len(users) > 0

    for doc in users:
        check_user(doc)


async def test_verified_followers():
    api = get_api()
    mock_rep(api.verified_followers_raw, "raw_verified_followers", as_generator=True)

    users = await gather(api.verified_followers(2244994945))
    assert len(users) > 0

    for doc in users:
        check_user(doc)
        assert doc.blue is True, "snould be only Blue users"


async def test_subscriptions():
    api = get_api()
    mock_rep(api.subscriptions_raw, "raw_subscriptions", as_generator=True)

    users = await gather(api.subscriptions(44196397))
    assert len(users) > 0

    for doc in users:
        check_user(doc)


async def test_following():
    api = get_api()
    mock_rep(api.following_raw, "raw_following", as_generator=True)

    users = await gather(api.following(2244994945))
    assert len(users) > 0

    for doc in users:
        check_user(doc)


async def test_retweters():
    api = get_api()
    mock_rep(api.retweeters_raw, "raw_retweeters", as_generator=True)

    users = await gather(api.retweeters(1649191520250245121))
    assert len(users) > 0

    for doc in users:
        check_user(doc)


async def test_user_tweets():
    api = get_api()
    mock_rep(api.user_tweets_raw, "raw_user_tweets", as_generator=True)

    tweets = await gather(api.user_tweets(2244994945))
    assert len(tweets) > 0

    is_any_pinned = False
    for doc in tweets:
        check_tweet(doc)
        is_any_pinned = is_any_pinned or doc.id in doc.user.pinnedIds

    assert is_any_pinned, "at least one tweet should be pinned (or bad luck with data)"


async def test_user_tweets_and_replies():
    api = get_api()
    mock_rep(api.user_tweets_and_replies_raw, "raw_user_tweets_and_replies", as_generator=True)

    tweets = await gather(api.user_tweets_and_replies(2244994945))
    assert len(tweets) > 0

    for doc in tweets:
        check_tweet(doc)


async def test_raw_user_media():
    api = get_api()
    mock_rep(api.user_media_raw, "raw_user_media", as_generator=True)

    tweets = await gather(api.user_media(2244994945))
    assert len(tweets) > 0

    for doc in tweets:
        check_tweet(doc)
        assert doc.media is not None
        media_count = len(doc.media.photos) + len(doc.media.videos) + len(doc.media.animated)
        assert media_count > 0, f"{doc.url} should have media"


async def test_list_timeline():
    api = get_api()
    mock_rep(api.list_timeline_raw, "raw_list_timeline", as_generator=True)

    tweets = await gather(api.list_timeline(1494877848087187461))
    assert len(tweets) > 0

    users = []
    for doc in tweets:
        check_tweet(doc)
        users.extend(collect_tweet_users(doc))

    check_user_field_coverage(users)


async def test_list_members():
    api = get_api()
    mock_rep(api.list_members_raw, "raw_list_members", as_generator=True)

    users = await gather(api.list_members(1494877848087187461))
    assert len(users) > 0

    for doc in users:
        check_user(doc)


async def test_community_info():
    api = get_api()
    mock_rep(api.community_info_raw, "raw_community_info")

    info = await api.community_info(1501272736215322629)
    assert info is not None
    assert isinstance(info.id, int)
    assert info.name is not None
    assert isinstance(info.memberCount, int)


async def test_community_members():
    api = get_api()
    mock_rep(api.community_members_raw, "raw_community_members", as_generator=True)

    users = await gather(api.community_members(1501272736215322629))
    assert len(users) > 0

    for doc in users:
        check_user(doc)


async def test_community_moderators():
    api = get_api()
    mock_rep(api.community_moderators_raw, "raw_community_moderators", as_generator=True)

    users = await gather(api.community_moderators(1501272736215322629))
    assert len(users) > 0

    for doc in users:
        check_user(doc)


async def test_community_tweets():
    api = get_api()
    mock_rep(api.community_tweets_raw, "raw_community_tweets", as_generator=True)

    tweets = await gather(api.community_tweets(1501272736215322629))
    assert len(tweets) > 0

    for doc in tweets:
        check_tweet(doc)


async def test_trends():
    api = get_api()
    mock_rep(api.trends_raw, "raw_trends", as_generator=True)

    items = await gather(api.trends("sport"))
    assert len(items) > 0

    for doc in items:
        check_trend(doc)


async def test_tweet_with_video():
    api = get_api()

    files = [
        ("manual_tweet_with_video_1.json", 1671508600538161153),
        ("manual_tweet_with_video_2.json", 1671753569412820992),
    ]

    for file, twid in files:
        mock_rep(api.tweet_details_raw, file)
        doc = await api.tweet_details(twid)
        assert doc is not None
        check_tweet(doc)


async def test_issue_28():
    api = get_api()

    mock_rep(api.tweet_details_raw, "_issue_28_1")
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

    mock_rep(api.tweet_details_raw, "_issue_28_2")
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
    raw = fake_rep("_issue_42").json()
    doc = parse_tweet(raw, 1665951747842641921)
    assert doc is not None
    assert doc.retweetedTweet is not None
    assert doc.rawContent is not None
    assert doc.retweetedTweet.rawContent is not None
    assert doc.rawContent.endswith(doc.retweetedTweet.rawContent)


def test_retweet_not_duplicated():
    """The original tweet embedded inside a retweet must not also be yielded
    as a standalone top-level item by parse_tweets."""
    raw = fake_rep("_issue_42").json()
    tweets = list(parse_tweets(raw))

    rt_wrapper = next((t for t in tweets if t.id == 1665951747842641921), None)
    assert rt_wrapper is not None, "RT wrapper tweet not found"
    assert rt_wrapper.retweetedTweet is not None

    original_id = rt_wrapper.retweetedTweet.id
    assert all(t.id != original_id for t in tweets), (
        f"retweetedTweet {original_id} leaked as a standalone top-level item"
    )


async def test_issue_56():
    raw = fake_rep("_issue_56").json()
    doc = parse_tweet(raw, 1682072224013099008)
    assert doc is not None
    assert len({x.tcourl for x in doc.links}) == len(doc.links)
    assert len(doc.links) == 5


async def test_issue_310():
    api = get_api()
    mock_rep(api.user_tweets_raw, "raw_user_tweets", as_generator=True)

    tweets = await gather(api.user_tweets(2244994945))
    top_level_ids = {x.id for x in tweets}
    retweeted_ids = {x.retweetedTweet.id for x in tweets if x.retweetedTweet is not None}
    leaked_ids = top_level_ids & retweeted_ids

    assert retweeted_ids
    assert not leaked_ids, (
        f"top_level={len(top_level_ids)}, "
        f"retweets={sum(x.retweetedTweet is not None for x in tweets)}, "
        f"retweeted_children={len(retweeted_ids)}, "
        f"leaked={len(leaked_ids)}"
    )


async def test_cards():
    # Issues:
    # - https://github.com/vladkens/twscrape/issues/72
    # - https://github.com/vladkens/twscrape/issues/191

    # Check SummaryCard
    raw = fake_rep("card_summary").json()
    doc = parse_tweet(raw, 1696922210588410217)
    assert doc is not None
    assert doc.card is not None
    assert isinstance(doc.card, SummaryCard)
    assert doc.card._type == "summary"
    assert doc.card.title is not None
    assert doc.card.description is not None
    assert doc.card.url is not None

    # Check PollCard
    raw = fake_rep("card_poll").json()
    doc = parse_tweet(raw, 1780666831310877100)
    assert doc is not None
    assert doc.card is not None
    assert isinstance(doc.card, PollCard)
    assert doc.card._type == "poll"
    assert doc.card.finished is not None
    assert doc.card.options is not None
    assert len(doc.card.options) > 0
    for x in doc.card.options:
        assert x.label is not None
        assert x.votesCount is not None

    # Check BrodcastCard
    raw = fake_rep("card_broadcast").json()
    doc = parse_tweet(raw, 1790441814857826439)
    assert doc is not None and doc.card is not None
    assert doc.card._type == "broadcast"
    assert isinstance(doc.card, BroadcastCard)
    assert doc.card.title is not None
    assert doc.card.url is not None
    assert doc.card.photo is not None

    # Check AudiospaceCard
    raw = fake_rep("card_audiospace").json()
    doc = parse_tweet(raw, 1789054061729173804)
    assert doc is not None and doc.card is not None
    assert doc.card._type == "audiospace"
    assert isinstance(doc.card, AudiospaceCard)
    assert doc.card.url is not None


async def test_tweet_new_fields():
    tweets = list(parse_tweets(fake_rep("raw_search").json()))
    assert len(tweets) > 0

    for doc in tweets:
        assert isinstance(doc.isQuoteStatus, bool)
        assert isinstance(doc.isTranslatable, bool)

        if doc.displayTextRange is not None:
            assert isinstance(doc.displayTextRange, list)
            assert len(doc.displayTextRange) == 2
            assert all(isinstance(x, int) for x in doc.displayTextRange)

        if doc.inReplyToScreenName is not None:
            assert isinstance(doc.inReplyToScreenName, str)
            assert len(doc.inReplyToScreenName) > 0

        if doc.editControl is not None:
            assert isinstance(doc.editControl, dict)
            assert "edit_tweet_ids" in doc.editControl
            assert isinstance(doc.editControl["edit_tweet_ids"], list)
            assert "is_edit_eligible" in doc.editControl
            assert isinstance(doc.editControl["is_edit_eligible"], bool)

        assert doc.voiceInfo is None or isinstance(doc.voiceInfo, dict)

    assert any(doc.isQuoteStatus for doc in tweets), "expected at least one quote tweet"
    assert any(doc.inReplyToScreenName for doc in tweets), "expected at least one reply tweet"
    assert any(doc.editControl is not None for doc in tweets), (
        "expected editControl in at least one tweet"
    )
    assert any(doc.displayTextRange is not None for doc in tweets), (
        "expected displayTextRange in at least one tweet"
    )
