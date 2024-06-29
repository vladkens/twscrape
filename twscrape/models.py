import email.utils
import json
import os
import random
import re
import string
import sys
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Generator, Optional, Union

import httpx

from .logger import logger
from .utils import find_item, get_or, int_or, to_old_rep, utc


@dataclass
class JSONTrait:
    def dict(self):
        return asdict(self)

    def json(self):
        return json.dumps(self.dict(), default=str)


@dataclass
class Coordinates(JSONTrait):
    longitude: float
    latitude: float

    @staticmethod
    def parse(tw_obj: dict):
        if tw_obj.get("coordinates"):
            coords = tw_obj["coordinates"]["coordinates"]
            return Coordinates(coords[0], coords[1])
        if tw_obj.get("geo"):
            coords = tw_obj["geo"]["coordinates"]
            return Coordinates(coords[1], coords[0])
        return None


@dataclass
class Place(JSONTrait):
    id: str
    fullName: str
    name: str
    type: str
    country: str
    countryCode: str

    @staticmethod
    def parse(obj: dict):
        return Place(
            id=obj["id"],
            fullName=obj["full_name"],
            name=obj["name"],
            type=obj["place_type"],
            country=obj["country"],
            countryCode=obj["country_code"],
        )


@dataclass
class TextLink(JSONTrait):
    url: str
    text: str | None
    tcourl: str | None

    @staticmethod
    def parse(obj: dict):
        tmp = TextLink(
            url=obj.get("expanded_url", None),
            text=obj.get("display_url", None),
            tcourl=obj.get("url", None),
        )

        if tmp.url is None or tmp.tcourl is None:
            return None

        return tmp


@dataclass
class UserRef(JSONTrait):
    id: int
    id_str: str
    username: str
    displayname: str
    _type: str = "snscrape.modules.twitter.UserRef"

    @staticmethod
    def parse(obj: dict):
        return UserRef(
            id=int(obj["id_str"]),
            id_str=obj["id_str"],
            username=obj["screen_name"],
            displayname=obj["name"],
        )


@dataclass
class User(JSONTrait):
    id: int
    id_str: str
    url: str
    username: str
    displayname: str
    rawDescription: str
    created: datetime
    followersCount: int
    friendsCount: int
    statusesCount: int
    favouritesCount: int
    listedCount: int
    mediaCount: int
    location: str
    profileImageUrl: str
    profileBannerUrl: str | None = None
    protected: bool | None = None
    verified: bool | None = None
    blue: bool | None = None
    blueType: str | None = None
    descriptionLinks: list[TextLink] = field(default_factory=list)
    pinnedIds: list[int] = field(default_factory=list)
    _type: str = "snscrape.modules.twitter.User"

    # todo:
    # link: typing.Optional[TextLink] = None
    # label: typing.Optional["UserLabel"] = None

    @staticmethod
    def parse(obj: dict, res=None):
        return User(
            id=int(obj["id_str"]),
            id_str=obj["id_str"],
            url=f'https://x.com/{obj["screen_name"]}',
            username=obj["screen_name"],
            displayname=obj["name"],
            rawDescription=obj["description"],
            created=email.utils.parsedate_to_datetime(obj["created_at"]),
            followersCount=obj["followers_count"],
            friendsCount=obj["friends_count"],
            statusesCount=obj["statuses_count"],
            favouritesCount=obj["favourites_count"],
            listedCount=obj["listed_count"],
            mediaCount=obj["media_count"],
            location=obj["location"],
            profileImageUrl=obj["profile_image_url_https"],
            profileBannerUrl=obj.get("profile_banner_url"),
            verified=obj.get("verified"),
            blue=obj.get("is_blue_verified"),
            blueType=obj.get("verified_type"),
            protected=obj.get("protected"),
            descriptionLinks=_parse_links(obj, ["entities.description.urls", "entities.url.urls"]),
            pinnedIds=[int(x) for x in obj.get("pinned_tweet_ids_str", [])],
        )


@dataclass
class Tweet(JSONTrait):
    id: int
    id_str: str
    url: str
    date: datetime
    user: User
    lang: str
    rawContent: str
    replyCount: int
    retweetCount: int
    likeCount: int
    quoteCount: int
    bookmarkedCount: int
    conversationId: int
    conversationIdStr: str
    hashtags: list[str]
    cashtags: list[str]
    mentionedUsers: list[UserRef]
    links: list[TextLink]
    viewCount: int | None = None
    retweetedTweet: Optional["Tweet"] = None
    quotedTweet: Optional["Tweet"] = None
    place: Optional[Place] = None
    coordinates: Optional[Coordinates] = None
    inReplyToTweetId: int | None = None
    inReplyToTweetIdStr: str | None = None
    inReplyToUser: UserRef | None = None
    source: str | None = None
    sourceUrl: str | None = None
    sourceLabel: str | None = None
    media: Optional["Media"] = None
    card: Union[None, "SummaryCard", "PollCard", "BroadcastCard", "AudiospaceCard"] = None
    _type: str = "snscrape.modules.twitter.Tweet"

    # todo:
    # renderedContent: str
    # vibe: Optional["Vibe"] = None

    @staticmethod
    def parse(obj: dict, res: dict):
        tw_usr = User.parse(res["users"][obj["user_id_str"]])

        rt_id_path = [
            "retweeted_status_id_str",
            "retweeted_status_result.result.rest_id",
            "retweeted_status_result.result.tweet.rest_id",
        ]

        qt_id_path = [
            "quoted_status_id_str",
            "quoted_status_result.result.rest_id",
            "quoted_status_result.result.tweet.rest_id",
        ]

        rt_obj = get_or(res, f"tweets.{_first(obj, rt_id_path)}")
        qt_obj = get_or(res, f"tweets.{_first(obj, qt_id_path)}")

        url = f'https://x.com/{tw_usr.username}/status/{obj["id_str"]}'
        doc = Tweet(
            id=int(obj["id_str"]),
            id_str=obj["id_str"],
            url=url,
            date=email.utils.parsedate_to_datetime(obj["created_at"]),
            user=tw_usr,
            lang=obj["lang"],
            rawContent=get_or(obj, "note_tweet.note_tweet_results.result.text", obj["full_text"]),
            replyCount=obj["reply_count"],
            retweetCount=obj["retweet_count"],
            likeCount=obj["favorite_count"],
            quoteCount=obj["quote_count"],
            bookmarkedCount=get_or(obj, "bookmark_count", 0),
            conversationId=int(obj["conversation_id_str"]),
            conversationIdStr=obj["conversation_id_str"],
            hashtags=[x["text"] for x in get_or(obj, "entities.hashtags", [])],
            cashtags=[x["text"] for x in get_or(obj, "entities.symbols", [])],
            mentionedUsers=[UserRef.parse(x) for x in get_or(obj, "entities.user_mentions", [])],
            links=_parse_links(
                obj, ["entities.urls", "note_tweet.note_tweet_results.result.entity_set.urls"]
            ),
            viewCount=_get_views(obj, rt_obj or {}),
            retweetedTweet=Tweet.parse(rt_obj, res) if rt_obj else None,
            quotedTweet=Tweet.parse(qt_obj, res) if qt_obj else None,
            place=Place.parse(obj["place"]) if obj.get("place") else None,
            coordinates=Coordinates.parse(obj),
            inReplyToTweetId=int_or(obj, "in_reply_to_status_id_str"),
            inReplyToTweetIdStr=get_or(obj, "in_reply_to_status_id_str"),
            inReplyToUser=_get_reply_user(obj, res),
            source=obj.get("source", None),
            sourceUrl=_get_source_url(obj),
            sourceLabel=_get_source_label(obj),
            media=Media.parse(obj),
            card=_parse_card(obj, url),
        )

        # issue #42 – restore full rt text
        rt = doc.retweetedTweet
        if rt is not None and rt.user is not None and doc.rawContent.endswith("…"):
            rt_msg = f"RT @{rt.user.username}: {rt.rawContent}"
            if doc.rawContent != rt_msg:
                doc.rawContent = rt_msg

        return doc


@dataclass
class MediaPhoto(JSONTrait):
    url: str

    @staticmethod
    def parse(obj: dict):
        return MediaPhoto(url=obj["media_url_https"])


@dataclass
class MediaVideo(JSONTrait):
    thumbnailUrl: str
    variants: list["MediaVideoVariant"]
    duration: int
    views: int | None = None

    @staticmethod
    def parse(obj: dict):
        return MediaVideo(
            thumbnailUrl=obj["media_url_https"],
            variants=[
                MediaVideoVariant.parse(x) for x in obj["video_info"]["variants"] if "bitrate" in x
            ],
            duration=obj["video_info"]["duration_millis"],
            views=int_or(obj, "mediaStats.viewCount"),
        )


@dataclass
class MediaAnimated(JSONTrait):
    thumbnailUrl: str
    videoUrl: str

    @staticmethod
    def parse(obj: dict):
        try:
            return MediaAnimated(
                thumbnailUrl=obj["media_url_https"],
                videoUrl=obj["video_info"]["variants"][0]["url"],
            )
        except KeyError:
            return None


@dataclass
class MediaVideoVariant(JSONTrait):
    contentType: str
    bitrate: int
    url: str

    @staticmethod
    def parse(obj: dict):
        return MediaVideoVariant(
            contentType=obj["content_type"],
            bitrate=obj["bitrate"],
            url=obj["url"],
        )


@dataclass
class Media(JSONTrait):
    photos: list[MediaPhoto] = field(default_factory=list)
    videos: list[MediaVideo] = field(default_factory=list)
    animated: list[MediaAnimated] = field(default_factory=list)

    @staticmethod
    def parse(obj: dict):
        photos: list[MediaPhoto] = []
        videos: list[MediaVideo] = []
        animated: list[MediaAnimated] = []

        for x in get_or(obj, "extended_entities.media", []):
            if x["type"] == "video":
                if video := MediaVideo.parse(x):
                    videos.append(video)
                continue

            if x["type"] == "photo":
                if photo := MediaPhoto.parse(x):
                    photos.append(photo)
                continue

            if x["type"] == "animated_gif":
                if animated_gif := MediaAnimated.parse(x):
                    animated.append(animated_gif)
                continue

            logger.warning(f"Unknown media type: {x['type']}: {json.dumps(x)}")

        return Media(photos=photos, videos=videos, animated=animated)


@dataclass
class Card(JSONTrait):
    pass


@dataclass
class SummaryCard(Card):
    title: str
    description: str
    vanityUrl: str
    url: str
    photo: MediaPhoto | None = None
    video: MediaVideo | None = None
    _type: str = "summary"


@dataclass
class PollOption(JSONTrait):
    label: str
    votesCount: int


@dataclass
class PollCard(Card):
    options: list[PollOption]
    finished: bool
    _type: str = "poll"


@dataclass
class BroadcastCard(Card):
    title: str
    url: str
    photo: MediaPhoto | None = None
    _type: str = "broadcast"


@dataclass
class AudiospaceCard(Card):
    url: str
    _type: str = "audiospace"


def _parse_card_get_bool(values: list[dict], key: str):
    for x in values:
        if x["key"] == key:
            return x["value"]["boolean_value"]
    return False


def _parse_card_get_str(values: list[dict], key: str, defaultVal=None) -> str | None:
    for x in values:
        if x["key"] == key:
            return x["value"]["string_value"]
    return defaultVal


def _parse_card_extract_str(values: list[dict], key: str):
    pretenders = [x["value"]["string_value"] for x in values if x["key"] == key]
    new_values = [x for x in values if x["key"] != key]
    return pretenders[0] if pretenders else "", new_values


def _parse_card_extract_title(values: list[dict]):
    new_values, pretenders = [], []
    # title is trimmed to 70 chars, so try to find the longest text in alt_text
    for x in values:
        k = x["key"]
        if k == "title" or k.endswith("_alt_text"):
            pretenders.append(x["value"]["string_value"])
        else:
            new_values.append(x)

    pretenders = sorted(pretenders, key=lambda x: len(x), reverse=True)
    return pretenders[0] if pretenders else "", new_values


def _parse_card_extract_largest_photo(values: list[dict]):
    photos = [x for x in values if x["value"]["type"] == "IMAGE"]
    photos = sorted(photos, key=lambda x: x["value"]["image_value"]["height"], reverse=True)
    values = [x for x in values if x["value"]["type"] != "IMAGE"]
    if photos:
        return MediaPhoto(url=photos[0]["value"]["image_value"]["url"]), values
    else:
        return None, values


def _parse_card_prepare_values(obj: dict):
    values = get_or(obj, "card.legacy.binding_values", [])
    # values = sorted(values, key=lambda x: x["key"])
    # values = [x for x in values if x["key"] not in {"domain", "creator", "site"}]
    values = [x for x in values if x["value"]["type"] != "IMAGE_COLOR"]
    return values


def _parse_card(obj: dict, url: str):
    name = get_or(obj, "card.legacy.name", None)
    if not name:
        return None

    if name in {"summary", "summary_large_image", "player"}:
        val = _parse_card_prepare_values(obj)
        title, val = _parse_card_extract_title(val)
        description, val = _parse_card_extract_str(val, "description")
        vanity_url, val = _parse_card_extract_str(val, "vanity_url")
        url, val = _parse_card_extract_str(val, "card_url")
        photo, val = _parse_card_extract_largest_photo(val)

        return SummaryCard(
            title=title,
            description=description,
            vanityUrl=vanity_url,
            url=url,
            photo=photo,
        )

    if name == "unified_card":
        val = _parse_card_prepare_values(obj)
        val = [x for x in val if x["key"] == "unified_card"][0]["value"]["string_value"]
        val = json.loads(val)

        co = get_or(val, "component_objects", {})
        do = get_or(val, "destination_objects", {})
        me = list(get_or(val, "media_entities", {}).values())
        if len(me) > 1:
            logger.debug(f"[Card] Multiple media entities: {json.dumps(me, indent=2)}")

        me = me[0] if me else {}

        title = get_or(co, "details_1.data.title.content", "")
        description = get_or(co, "details_1.data.subtitle.content", "")
        vanity_url = get_or(do, "browser_with_docked_media_1.data.url_data.vanity", "")
        url = get_or(do, "browser_with_docked_media_1.data.url_data.url", "")
        video = MediaVideo.parse(me) if me and me["type"] == "video" else None
        photo = MediaPhoto.parse(me) if me and me["type"] == "photo" else None

        return SummaryCard(
            title=title,
            description=description,
            vanityUrl=vanity_url,
            url=url,
            photo=photo,
            video=video,
        )

    if re.match(r"poll\d+choice_text_only", name):
        val = _parse_card_prepare_values(obj)

        options = []
        for x in range(20):
            label = _parse_card_get_str(val, f"choice{x+1}_label")
            votes = _parse_card_get_str(val, f"choice{x+1}_count")
            if label is None or votes is None:
                break

            options.append(PollOption(label=label, votesCount=int(votes)))

        finished = _parse_card_get_bool(val, "counts_are_final")
        # duration_minutes = int(_parse_card_get_str(val, "duration_minutes") or "0")
        # end_datetime_utc = _parse_card_get_str(val, "end_datetime_utc")
        # print(json.dumps(val, indent=2))
        return PollCard(options=options, finished=finished)

    if name == "745291183405076480:broadcast":
        val = _parse_card_prepare_values(obj)
        card_url = _parse_card_get_str(val, "broadcast_url")
        card_title = _parse_card_get_str(val, "broadcast_title")
        photo, _ = _parse_card_extract_largest_photo(val)
        if card_url is None or card_title is None:
            return None

        return BroadcastCard(title=card_title, url=card_url, photo=photo)

    if name == "3691233323:audiospace":
        # no more data in this object, possible extra api call needed to get card info
        val = _parse_card_prepare_values(obj)
        card_url = _parse_card_get_str(val, "card_url")
        if card_url is None:
            return None

        # print(json.dumps(val, indent=2))
        return AudiospaceCard(url=card_url)

    logger.warning(f"Unknown card type '{name}' on {url}")
    if "PYTEST_CURRENT_TEST" in os.environ:  # help debugging tests
        print(f"Unknown card type '{name}' on {url}", file=sys.stderr)
        # print(json.dumps(obj["card"]["legacy"], indent=2))
    return None


# internal helpers


def _get_reply_user(tw_obj: dict, res: dict):
    user_id = tw_obj.get("in_reply_to_user_id_str", None)
    if user_id is None:
        return None

    if user_id in res["users"]:
        return UserRef.parse(res["users"][user_id])

    mentions = get_or(tw_obj, "entities.user_mentions", [])
    mention = find_item(mentions, lambda x: x["id_str"] == tw_obj["in_reply_to_user_id_str"])
    if mention:
        return UserRef.parse(mention)

    # todo: user not found in reply (probably deleted or hidden)
    return None


def _get_source_url(tw_obj: dict):
    source = tw_obj.get("source", None)
    if source and (match := re.search(r'href=[\'"]?([^\'" >]+)', source)):
        return str(match.group(1))
    return None


def _get_source_label(tw_obj: dict):
    source = tw_obj.get("source", None)
    if source and (match := re.search(r">([^<]*)<", source)):
        return str(match.group(1))
    return None


def _parse_links(obj: dict, paths: list[str]):
    links = []
    for x in paths:
        links.extend(get_or(obj, x, []))

    links = [TextLink.parse(x) for x in links]
    links = [x for x in links if x is not None]

    return links


def _first(obj: dict, paths: list[str]):
    for x in paths:
        cid = get_or(obj, x, None)
        if cid is not None:
            return cid
    return None


def _get_views(obj: dict, rt_obj: dict):
    for x in [obj, rt_obj]:
        for y in ["ext_views.count", "views.count"]:
            k = int_or(x, y)
            if k is not None:
                return k
    return None


def _write_dump(kind: str, e: Exception, x: dict, obj: dict):
    uniq = "".join(random.choice(string.ascii_lowercase) for _ in range(5))
    time = utc.now().strftime("%Y-%m-%d_%H-%M-%S")
    dumpfile = f"/tmp/twscrape/twscrape_parse_error_{time}_{uniq}.txt"
    os.makedirs(os.path.dirname(dumpfile), exist_ok=True)

    with open(dumpfile, "w") as fp:
        msg = [
            f"Error parsing {kind}. Error: {type(e)}",
            traceback.format_exc(),
            json.dumps(x, default=str),
            json.dumps(obj, default=str),
        ]
        fp.write("\n\n".join(msg))

    logger.error(f"Failed to parse response of {kind}, writing dump to {dumpfile}")


def _parse_items(rep: httpx.Response, kind: str, limit: int = -1):
    if kind == "user":
        Cls, key = User, "users"
    elif kind == "tweet":
        Cls, key = Tweet, "tweets"
    else:
        raise ValueError(f"Invalid kind: {kind}")

    # check for dict, because httpx.Response can be mocked in tests with different type
    res = rep if isinstance(rep, dict) else rep.json()
    obj = to_old_rep(res)

    ids = set()
    for x in obj[key].values():
        if limit != -1 and len(ids) >= limit:
            # todo: move somewhere in configuration like force_limit
            # https://github.com/vladkens/twscrape/issues/26#issuecomment-1656875132
            # break
            pass

        try:
            tmp = Cls.parse(x, obj)
            if tmp.id not in ids:
                ids.add(tmp.id)
                yield tmp
        except Exception as e:
            _write_dump(kind, e, x, obj)
            continue


# public helpers


def parse_tweets(rep: httpx.Response, limit: int = -1) -> Generator[Tweet, None, None]:
    return _parse_items(rep, "tweet", limit)  # type: ignore


def parse_users(rep: httpx.Response, limit: int = -1) -> Generator[User, None, None]:
    return _parse_items(rep, "user", limit)  # type: ignore


def parse_tweet(rep: httpx.Response, twid: int) -> Tweet | None:
    try:
        docs = list(parse_tweets(rep))
        for x in docs:
            if x.id == twid:
                return x
        return None
    except Exception as e:
        logger.error(f"Failed to parse tweet {twid} - {type(e)}:\n{traceback.format_exc()}")
        return None


def parse_user(rep: httpx.Response) -> User | None:
    try:
        docs = list(parse_users(rep))
        if len(docs) == 1:
            return docs[0]
        return None
    except Exception as e:
        logger.error(f"Failed to parse user - {type(e)}:\n{traceback.format_exc()}")
        return None
