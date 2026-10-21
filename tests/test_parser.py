import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, cast

import pytest

from twscrape import API, gather, models
from twscrape.models import (
    AppCard,
    Article,
    AudiospaceCard,
    BroadcastCard,
    LiveEventCard,
    MessageMeCard,
    PeriscopeBroadcastCard,
    PollCard,
    PromoImageConvoCard,
    PromoVideoConvoCard,
    SummaryCard,
    Trend,
    Tweet,
    User,
    UserParseError,
    UserRef,
    parse_tweet,
    parse_tweets,
    parse_user,
)
from twscrape.utils import find_obj, get_typed_object, to_old_rep

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


@pytest.mark.parametrize("path", ["core", "author_results"])
@pytest.mark.parametrize("user_format", ["legacy", "flat"])
def test_tweet_parser_uses_embedded_author_when_users_map_is_missing(path, user_format):
    obj = to_old_rep(fake_rep("raw_search").json())
    tweet = next(x for x in obj["tweets"].values() if x.get("user_id_str") in obj["users"])
    user_id = tweet["user_id_str"]
    user = obj["users"].pop(user_id)
    tweet.pop("core", None)
    tweet.pop("author_results", None)
    embedded = {"__typename": "User", "rest_id": user_id, "legacy": user}
    if user_format == "flat":
        embedded = {k: v for k, v in user.items() if k not in {"core", "legacy", "rest_id"}}

    if path == "core":
        tweet["core"] = {"user_results": {"result": embedded}}
    else:
        tweet["author_results"] = {"result": embedded}

    parsed = Tweet.parse(tweet, obj)

    assert parsed.user.id_str == user_id


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

    if doc.retweetedTweetId is not None:
        assert isinstance(doc.retweetedTweetId, int)
        assert isinstance(doc.retweetedTweetIdStr, str)
        assert str(doc.retweetedTweetId) == doc.retweetedTweetIdStr

    if doc.retweetedTweet is not None:
        assert doc.retweetedTweetId == doc.retweetedTweet.id

    if doc.quotedTweetId is not None:
        assert isinstance(doc.quotedTweetId, int)
        assert isinstance(doc.quotedTweetIdStr, str)
        assert str(doc.quotedTweetId) == doc.quotedTweetIdStr

    if doc.quotedTweet is not None:
        assert doc.quotedTweetId == doc.quotedTweet.id

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
        "Run: uv run scripts/update-mocked-data.py fetch --only search"
    )
    check_user_field_coverage(users)


async def test_user_by_id():
    api = get_api()
    mock_rep(api.user_by_id_raw, "raw_user_by_id")

    doc = await api.user_by_id(2244994945)
    assert doc is not None
    assert doc.id == 2244994945
    assert doc.username == "XDevelopers"
    assert doc.blueType == "Business"

    obj = doc.dict()
    assert doc.id == obj["id"]
    assert doc.username == obj["username"]

    txt = doc.json()
    assert isinstance(txt, str)
    assert str(doc.id) in txt


async def test_user_by_login():
    api = get_api()
    mock_rep(api.user_by_login_raw, "raw_user_by_login")

    doc = await api.user_by_login("xdevelopers")
    assert doc is not None
    assert doc.id == 2244994945
    assert doc.username == "XDevelopers"
    assert doc.blueType == "Business"

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
    assert doc.retweetedTweetId == 1658407192859492355
    assert doc.retweetedTweetIdStr == "1658407192859492355"
    check_tweet(doc.retweetedTweet)

    mock_rep(api.tweet_details_raw, "_issue_28_2")
    doc = await api.tweet_details(1658421690001502208)
    assert doc is not None
    check_tweet(doc)
    assert doc.id == 1658421690001502208
    assert doc.viewCount is not None

    assert doc.quotedTweet is not None
    assert doc.quotedTweet.id != doc.id
    assert doc.quotedTweetId == 1658407192859492355
    assert doc.quotedTweetIdStr == "1658407192859492355"
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


@pytest.mark.parametrize(
    "fixture, twid, quoted_id",
    [
        # Real TweetDetail responses: X sends the quoted ID with a TweetTombstone (account
        # gone) or a TweetUnavailable in place of the quoted tweet
        ("_quote_of_tombstone", 1553061790468161538, 1552999455422664704),
        ("_quote_of_unavailable", 1864361260982083963, 1864142818312171743),
    ],
)
def test_quote_of_unavailable_tweet_keeps_quoted_id(fixture, twid, quoted_id):
    doc = parse_tweet(fake_rep(fixture).json(), twid)
    assert doc is not None
    check_tweet(doc)
    assert doc.isQuoteStatus
    assert doc.quotedTweet is None
    assert doc.quotedTweetId == quoted_id
    assert doc.quotedTweetIdStr == str(quoted_id)
    assert doc.retweetedTweetId is None


def test_retweet_with_visibility_results_id():
    # Real TweetDetail response: the retweeted tweet is a TweetWithVisibilityResults, its ID
    # under retweeted_status_result.result.tweet.rest_id
    doc = parse_tweet(fake_rep("_retweet_with_visibility_results").json(), 1686409496019562496)
    assert doc is not None
    check_tweet(doc)
    assert doc.retweetedTweet is not None
    assert doc.retweetedTweetId == 1686408294095577090
    assert doc.retweetedTweetIdStr == "1686408294095577090"


def test_retweet_of_quote_ids():
    # The wrapper of a retweet of a quote also carries the quoted ID of the original
    tweets = {x.id: x for x in parse_tweets(fake_rep("_issue_315").json())}
    doc = tweets[2075724225273323678]
    check_tweet(doc)

    rt = doc.retweetedTweet
    assert rt is not None
    assert doc.retweetedTweetId == rt.id == 2075723878333141097
    assert rt.quotedTweetId == 2075716337603907695
    assert doc.quotedTweetId == rt.quotedTweetId
    assert doc.quotedTweet is not None
    assert doc.quotedTweet.id == rt.quotedTweetId


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


def test_article_tweet():
    # timelines get the article preview, without its content state
    raw = fake_rep("_issue_342_343").json()
    source = find_obj(raw, lambda x: "preview_text" in x)
    assert source is not None

    doc = {x.id: x for x in parse_tweets(raw)}[2079814622639469025]
    assert doc.retweetedTweet is not None

    article = doc.retweetedTweet.article
    assert article is not None
    assert article.id == int(source["rest_id"])
    assert article.title == source["title"]
    assert article.previewText == source["preview_text"]
    assert article.contentState is None
    assert article.publishedAt == datetime.fromtimestamp(
        source["metadata"]["first_published_at_secs"], timezone.utc
    )
    assert article.modifiedAt == datetime.fromtimestamp(
        source["lifecycle_state"]["modified_at_secs"], timezone.utc
    )


def test_article_rich_content():
    raw = fake_rep("article").json()
    source = find_obj(raw, lambda x: "content_state" in x)
    assert source is not None

    doc = parse_tweet(raw, 2075503860689281453)
    assert doc is not None
    assert isinstance(doc.article, Article)

    article = doc.article
    assert article.id_str == source["rest_id"]
    assert article.title == source["title"]
    assert article.summaryText == source["summary_text"]
    assert article.isGrokSummaryEligible is True
    assert article.coverMedia is not None
    assert article.coverMedia.mediaId == source["cover_media"]["media_id"]
    assert article.coverMedia.mediaInfo == source["cover_media"]["media_info"]
    assert article.mediaEntities == source["media_entities"]

    assert article.contentState is not None
    content = article.contentState
    assert [x.key for x in content.blocks] == [x["key"] for x in source["content_state"]["blocks"]]
    assert list(content.entityMap) == [str(x["key"]) for x in source["content_state"]["entityMap"]]
    assert {x.type for x in content.blocks} == {
        "unstyled",
        "atomic",
        "header-two",
        "unordered-list-item",
    }
    assert any(x.data.get("urls") for x in content.blocks)
    assert any(x.data.get("hashtags") for x in content.blocks)
    assert any(x.inlineStyleRanges for x in content.blocks)
    assert all(x.key in content.entityMap for block in content.blocks for x in block.entityRanges)

    entities = [content.entityMap[x.key] for block in content.blocks for x in block.entityRanges]
    assert {x.type for x in entities} >= {"MARKDOWN", "TWEMOJI", "DIVIDER"}
    assert any(x.data.get("markdown", "").startswith("```bash") for x in entities)
    assert any(x.data.get("url", "").endswith(".svg") for x in entities)
    assert any(x.type == "DIVIDER" and x.data == {} for x in entities)

    parsed = article.dict()
    assert len(parsed["contentState"]["blocks"]) == len(source["content_state"]["blocks"])
    assert parsed["contentState"]["entityMap"].keys() == content.entityMap.keys()


def test_article_malformed():
    # a bad article must never drop its tweet
    raw = fake_rep("article").json()
    source = find_obj(raw, lambda x: "content_state" in x)
    assert source is not None

    source["content_state"]["blocks"][0] = {"key": "k1"}
    del source["cover_media"]["media_key"]
    doc = parse_tweet(raw, 2075503860689281453)
    assert doc is not None and doc.article is not None
    assert doc.article.contentState is not None
    assert doc.article.contentState.blocks[0].text == ""
    assert doc.article.coverMedia is not None and doc.article.coverMedia.mediaKey == ""

    source["content_state"]["blocks"][0] = None
    source["rest_id"] = None
    doc = parse_tweet(raw, 2075503860689281453)
    assert doc is not None
    assert doc.article is None


async def test_issue_315():
    """Quoted tweets must not leak as standalone timeline items.

    UserTweets page of @XDevelopers, trimmed to retweets quoting @XDevelopers and @agno_three,
    a retweet of the @agno_three tweet and the thread module of the quoted @XDevelopers tweet.
    X returns quoted tweets embedded in the quoting tweet's payload and they must not be
    yielded as top-level items too: https://github.com/vladkens/twscrape/issues/315
    """
    tweets = list(parse_tweets(fake_rep("_issue_315").json()))
    top_level_ids = [x.id_str for x in tweets]

    # a self-quoted tweet X lists inside its own thread module entry remains a real result
    assert top_level_ids == [
        "2082669627528601817",
        "2082640274845811115",
        "2082640276389249363",
        "2075724225273323678",
        "2075722586172846484",
    ]

    other_user_quotes = {
        x.quotedTweet.id_str
        for x in tweets
        if x.quotedTweet is not None and x.quotedTweet.user.username != x.user.username
    }
    assert other_user_quotes == {"2075716337603907695"}


@pytest.mark.parametrize(
    "module",
    ["conversationthread", "list-conversation", "profile-grid", "tweetdetailrelatedtweets"],
)
def test_quoted_tweet_in_other_timeline_modules_is_standalone(module):
    raw = fake_rep("_issue_315").json()
    quoted_id = "2082640274845811115"
    entry = find_obj(raw, lambda x: x.get("entryId", "").endswith(f"-tweet-{quoted_id}"))
    assert entry is not None
    entry["entryId"] = entry["entryId"].replace("profile-conversation-", f"{module}-", 1)

    assert quoted_id in {tweet.id_str for tweet in parse_tweets(raw)}


def _automated_by_label(user_id: str, screen_name: str) -> dict:
    # A bot's "Automated by @operator" label embeds the operator as a partial User
    mention = {"__typename": "User", "rest_id": user_id, "core": {"screen_name": screen_name}}
    entity = {"ref": {"mention_results": {"result": mention}}}
    return {"label": {"longDescription": {"entities": [entity]}}}


def test_partial_user_does_not_overwrite_full_user():
    # https://github.com/vladkens/twscrape/issues/341
    # Real UserTweets page: two retweets of @rodalies, then a retweet of the bot @rod11cat
    # whose "Automated by @rodalies" label embeds @rodalies as a partial User.
    raw = fake_rep("_issue_341").json()

    assert to_old_rep(raw)["users"]["110680768"]["name"] == "Rodalies Catalunya"

    tweets = {x.id: x for x in parse_tweets(raw)}
    for twid in (2106637440312369380, 2106444684209893707):
        rt = tweets[twid].retweetedTweet
        assert rt is not None
        assert rt.user.username == "rodalies"


def test_partial_only_user_keeps_user_lookup_single(monkeypatch):
    # The operator of a looked-up bot exists only as a partial User: the lookup returns the
    # bot, without a parse error for the operator.
    expected = parse_user(fake_rep("raw_user_by_login").json())
    assert expected is not None

    raw = fake_rep("raw_user_by_login").json()
    label = _automated_by_label("123456789", "operator_account")
    raw["data"]["user"]["result"]["affiliates_highlighted_label"] = label

    dumps = []
    monkeypatch.setattr(models, "_write_dump", lambda *args: dumps.append(args))
    assert parse_user(raw) == expected
    assert dumps == []


@pytest.mark.parametrize("missing", ["name", "screen_name", "core"])
def test_user_lookup_normalization_failure_raises(missing):
    # https://github.com/vladkens/twscrape/issues/346
    # A user X sent but that can't be parsed must not read as "no user", e.g. the looked-up
    # user lacks its name, like the partial users of #341 and #342.
    raw = fake_rep("raw_user_by_id").json()
    user = raw["data"]["user"]["result"]
    if missing == "core":
        del user["core"]
    else:
        del user["core"][missing]

    with pytest.raises(UserParseError, match="Failed to parse user"):
        parse_user(raw)


def test_user_lookup_parse_failure_keeps_cause():
    # A looked-up user that normalizes but fails User.parse wraps the original error
    raw = fake_rep("raw_user_by_id").json()
    raw["data"]["user"]["result"]["core"]["created_at"] = "not a date"

    with pytest.raises(UserParseError, match="Failed to parse user") as exc:
        parse_user(raw)

    assert isinstance(exc.value.__cause__, ValueError)


def test_bot_reply_to_partial_only_operator():
    # Two own retweets from production UserTweets pages (@NatMus_SWE, @betaworks). Each
    # retweets a bot's reply to its operator, whose "Automated by @operator" label is the
    # only User of the operator on the page, partial, without name.
    tweets = {x.id: x for x in parse_tweets(fake_rep("_user_tweets_bot_reply_to_operator").json())}
    for twid, bot, operator in (
        (
            956082660291555328,
            "Emojimuseet",
            (185260921, "AronAmbrosiani", "Aron Ambrosiani @aronambrosiani@glammr.us"),
        ),
        (1934744325579051137, "opus_genesis", (1614308799220695045, "veryvanya", "veryvanya")),
    ):
        rt = tweets[twid].retweetedTweet
        assert rt is not None
        assert rt.user.username == bot
        reply_to = rt.inReplyToUser
        assert reply_to is not None
        assert (reply_to.id, reply_to.username, reply_to.displayname) == operator


def test_nested_author_without_profile_keeps_outer_tweet():
    # https://github.com/vladkens/twscrape/issues/342
    # https://github.com/vladkens/twscrape/issues/343
    # UserTweets page from raw_user_tweets, with nested authors replaced by the shapes X sent
    # in production: UserUnavailable (#343) and a User stub without core (#342).
    tweets = {x.id: x for x in parse_tweets(fake_rep("_issue_342_343").json())}

    # retweet of an unavailable author: handle and name from the retweet's user_mentions
    rt = tweets[2083305234688803178].retweetedTweet
    assert rt is not None
    assert rt.id == 2083289084567724316
    assert rt.rawContent.startswith("Overhauled the 𝕏 Developer Console")
    assert (rt.user.id, rt.user.username, rt.user.displayname) == (
        2606432720,
        "benjitaylor",
        "Benji Taylor",
    )

    # unavailable author of a tweet quoted by a retweet: handle from quoted_status_permalink
    rt = tweets[2082157691451920667].retweetedTweet
    assert rt is not None
    qt = rt.quotedTweet
    assert qt is not None
    assert qt.id == 2082134521370272218
    assert (qt.user.id, qt.user.username) == (2867234365, "milichab")

    # retweet of a stub author
    rt = tweets[2079814622639469025].retweetedTweet
    assert rt is not None
    assert (rt.user.id, rt.user.username, rt.user.displayname) == (
        1818311005698678784,
        "XFreeze",
        "X Freeze",
    )


def test_retweet_author_from_text_prefix_without_mention():
    # The retweet of an unavailable author from _issue_342_343, without the user_mentions
    # entry that names the author: the handle comes from the retweet's "RT @handle: " prefix,
    # so the truncated retweet text is still restored with it.
    raw = fake_rep("_issue_342_343").json()
    tweet = find_obj(raw, lambda x: x.get("rest_id") == "2083305234688803178" and "legacy" in x)
    assert tweet is not None
    tweet["legacy"]["entities"]["user_mentions"] = []

    tweet = {x.id: x for x in parse_tweets(raw)}[2083305234688803178]
    rt = tweet.retweetedTweet
    assert rt is not None
    assert (rt.user.id, rt.user.username, rt.user.displayname) == (2606432720, "benjitaylor", "")
    assert tweet.rawContent == f"RT @benjitaylor: {rt.rawContent}"


@pytest.mark.parametrize(
    "shape", ["empty", "stub", "stub_empty_core", "stub_empty_legacy", "partial", "absent"]
)
def test_own_author_without_profile_keeps_tweets(shape, monkeypatch):
    # Real UserTweets page of @scottyenor (April 2023 part, trimmed to 4 entries), with the
    # author of every own tweet sent as empty user_results, as X did in production for this
    # page on 2026-10-05. The other shapes seen that day, a User stub without core and no
    # core at all, are applied over it, as well as stubs with empty core or legacy and a
    # partial User with only screen_name. The tweets are complete: kept, with an ID-only author.
    raw = fake_rep("_user_tweets_own_author_without_profile").json()
    uid = "1380623475023355907"
    stubs = {
        "stub": {"privacy": {"protected": False}},
        "stub_empty_core": {"core": {}},
        "stub_empty_legacy": {"legacy": {}},
        "partial": {"core": {"screen_name": "scottyenor"}},
    }

    for x in get_typed_object(raw, defaultdict(list))["Tweet"]:
        if shape == "empty" or x["legacy"]["user_id_str"] != uid:
            continue

        if shape == "absent":
            del x["core"]
        else:
            stub = {"__typename": "User", "rest_id": uid, **stubs[shape]}
            x["core"] = {"user_results": {"result": stub}}

    assert uid not in to_old_rep(raw)["users"]

    warnings = []
    monkeypatch.setattr(models.logger, "warning", warnings.append)
    tweets = {x.id: x for x in parse_tweets(raw)}
    assert len(tweets) == 7
    assert len(warnings) == 1  # once per author per page
    for tw in tweets.values():
        assert (tw.user.id_str, tw.user.username, tw.user.displayname) == (uid, "", "")
        assert tw.url == f"https://x.com/i/status/{tw.id}"

    # self-replies of two threads: the replied-to user comes from the reply's own fields
    for twid in (
        1643335556762329089,
        1643612772930813956,
        1643335820617678854,
        1643336000138092545,
    ):
        reply_to = tweets[twid].inReplyToUser
        assert reply_to is not None
        assert (reply_to.id_str, reply_to.username) == (uid, "scottyenor")

    # the retweeted author is unaffected
    rt = tweets[1645841834814341125].retweetedTweet
    assert rt is not None
    assert rt.user.username == "megbasham"


# Issues:
# - https://github.com/vladkens/twscrape/issues/72
# - https://github.com/vladkens/twscrape/issues/191
# fixture, tweet id, card class, expected attrs (`...` means not None)
CARDS = {
    "summary": (
        "card_summary",
        1696922210588410217,
        SummaryCard,
        {"_type": "summary", "title": ..., "description": ..., "url": ...},
    ),
    "poll": (
        "card_poll",
        1780666831310877100,
        PollCard,
        {"_type": "poll", "finished": ..., "options": ...},
    ),
    "poll2choice_video": (
        "card_poll_video",
        1114574134397165568,
        PollCard,
        {"_type": "poll", "finished": True, "videoUrl": ..., "durationSeconds": 24, "photo": ...},
    ),
    "broadcast": (
        "card_broadcast",
        1790441814857826439,
        BroadcastCard,
        {"_type": "broadcast", "title": ..., "url": ..., "photo": ...},
    ),
    "audiospace": (
        "card_audiospace",
        1789054061729173804,
        AudiospaceCard,
        {"_type": "audiospace", "url": ...},
    ),
    "message_me": (
        "card_message_me",
        1916063270131191983,
        MessageMeCard,
        {"_type": "message_me", "url": ..., "cta": ..., "recipientId": "85741735"},
    ),
    "periscope_broadcast": (
        "card_periscope_broadcast",
        822817044450013184,
        PeriscopeBroadcastCard,
        {
            "_type": "periscope_broadcast",
            "title": ...,
            "url": ...,
            "state": "ENDED",
            "broadcasterUsername": "womensmarch",
            "thumbnailUrl": ...,
        },
    ),
    "promo_video_convo": (
        "card_promo_video_convo",
        1090673433690685441,
        PromoVideoConvoCard,
        {
            "_type": "promo_video_convo",
            "title": "Add your voice.",
            "thankYouText": ...,
            "videoUrl": ...,
            "durationSeconds": 5,
            "ctas": ["#BellLetsTalk"],
            "photo": ...,
        },
    ),
    "promo_image_convo": (
        "card_promo_image_convo",
        2078218219689492480,
        PromoImageConvoCard,
        {
            "_type": "promo_image_convo",
            "title": ...,
            "thankYouText": ...,
            "thankYouUrl": ...,
            "ctas": ["#onerufflecheddarlong"],
            "photo": ...,
        },
    ),
    "live_event": (
        "card_live_event",
        1463203718153703425,
        LiveEventCard,
        {
            "_type": "live_event",
            "title": ...,
            "url": ...,
            "eventId": "1461789549739143169",
            "category": "Music",
            "subtitle": ...,
            "photo": ...,
        },
    ),
    "app": (
        "card_app",
        1249486216266788865,
        AppCard,
        {
            "_type": "app",
            "title": "The NBC App – Stream TV Shows",
            "url": ...,
            "description": ...,
            "starRating": 4.57233,
            "numRatings": 289838,
            "photo": ...,
        },
    ),
}


@pytest.mark.parametrize("name, twid, cls, attrs", CARDS.values(), ids=CARDS.keys())
def test_cards(name, twid, cls, attrs):
    doc = parse_tweet(fake_rep(name).json(), twid)
    assert doc is not None
    assert isinstance(doc.card, cls)

    for k, v in attrs.items():
        x = getattr(doc.card, k)
        assert x is not None if v is ... else x == v, k


@pytest.mark.parametrize(
    "name, twid, count",
    [("card_poll", 1780666831310877100, 2), ("card_poll_video", 1114574134397165568, 2)],
)
def test_poll_card_options(name, twid, count):
    doc = parse_tweet(fake_rep(name).json(), twid)
    assert doc is not None and isinstance(doc.card, PollCard)
    assert len(doc.card.options) == count
    for x in doc.card.options:
        assert x.label is not None
        assert x.votesCount is not None


def test_poll_card_with_choice_images():
    raw = fake_rep("card_poll").json()
    card = find_obj(
        raw,
        lambda x: (
            isinstance(x.get("legacy"), dict)
            and str(x["legacy"].get("name", "")).startswith("poll")
        ),
    )
    assert card is not None

    card["legacy"]["name"] = "1906814671912599552:poll_choice_images"
    doc = parse_tweet(raw, 1780666831310877100)
    assert doc is not None
    assert isinstance(doc.card, PollCard)


def test_promo_image_convo_card_photo():
    # main image, not the cover_promo_image ad cover (that one lives under /ad_img/)
    doc = parse_tweet(fake_rep("card_promo_image_convo").json(), 2078218219689492480)
    assert doc is not None and isinstance(doc.card, PromoImageConvoCard)
    assert doc.card.photo is not None
    assert "/ad_img/" not in doc.card.photo.url


@pytest.mark.parametrize(
    "name, twid, key, value, attr",
    [
        ("card_app", 1249486216266788865, "app_star_rating", "n/a", "starRating"),
        ("card_app", 1249486216266788865, "app_num_ratings", "1.2K", "numRatings"),
        (
            "card_promo_video_convo",
            1090673433690685441,
            "content_duration_seconds",
            "",
            "durationSeconds",
        ),
    ],
)
def test_card_bad_numbers(name, twid, key, value, attr, monkeypatch):
    raw = fake_rep(name).json()
    item = find_obj(raw, lambda x: x.get("key") == key)
    assert item is not None

    item["value"]["string_value"] = value
    warnings = []
    monkeypatch.setattr(models.logger, "warning", warnings.append)
    doc = parse_tweet(raw, twid)
    assert doc is not None and doc.card is not None
    assert getattr(doc.card, attr) is None
    assert len(warnings) == 1 and f"{key}={value!r}" in warnings[0]


async def test_tweet_new_fields():
    tweets = [
        *parse_tweets(fake_rep("raw_search").json()),
        *parse_tweets(fake_rep("raw_tweet_replies").json()),
    ]
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
