import email.utils
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

from .logger import logger
from .utils import find_item, get_or, int_or_none


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
    indices: tuple[int, int]

    @staticmethod
    def parse(obj: dict):
        return TextLink(
            url=obj["expanded_url"],
            text=obj["display_url"],
            tcourl=obj["url"],
            indices=tuple(obj["indices"]),
        )


@dataclass
class UserRef(JSONTrait):
    id: int
    username: str
    displayname: str
    _type: str = "snscrape.modules.twitter.UserRef"

    @staticmethod
    def parse(obj: dict):
        return UserRef(id=int(obj["id_str"]), username=obj["screen_name"], displayname=obj["name"])


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
    _type: str = "snscrape.modules.twitter.User"

    # todo:
    # descriptionLinks: typing.Optional[typing.List[TextLink]] = None
    # link: typing.Optional[TextLink] = None
    # label: typing.Optional["UserLabel"] = None

    @staticmethod
    def parse(obj: dict):
        return User(
            id=int(obj["id_str"]),
            id_str=obj["id_str"],
            url=f'https://twitter.com/{obj["screen_name"]}',
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
            protected=obj.get("protected"),
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
    conversationId: int
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
    inReplyToUser: UserRef | None = None
    source: str | None = None
    sourceUrl: str | None = None
    sourceLabel: str | None = None
    media: Optional["Media"] = None
    _type: str = "snscrape.modules.twitter.Tweet"

    # todo:
    # renderedContent: str
    # card: typing.Optional["Card"] = None
    # vibe: typing.Optional["Vibe"] = None

    @staticmethod
    def parse(obj: dict, res: dict):
        tw_usr = User.parse(res["users"][obj["user_id_str"]])
        rt_obj = get_or(res, f"tweets.{obj.get('retweeted_status_id_str')}")
        qt_obj = get_or(res, f"tweets.{obj.get('quoted_status_id_str')}")

        return Tweet(
            id=int(obj["id_str"]),
            id_str=obj["id_str"],
            url=f'https://twitter.com/{tw_usr.username}/status/{obj["id_str"]}',
            date=email.utils.parsedate_to_datetime(obj["created_at"]),
            user=tw_usr,
            lang=obj["lang"],
            rawContent=obj["full_text"],
            replyCount=obj["reply_count"],
            retweetCount=obj["retweet_count"],
            likeCount=obj["favorite_count"],
            quoteCount=obj["quote_count"],
            conversationId=int(obj["conversation_id_str"]),
            hashtags=[x["text"] for x in get_or(obj, "entities.hashtags", [])],
            cashtags=[x["text"] for x in get_or(obj, "entities.symbols", [])],
            mentionedUsers=[UserRef.parse(x) for x in get_or(obj, "entities.user_mentions", [])],
            links=[TextLink.parse(x) for x in get_or(obj, "entities.urls", [])],
            viewCount=int_or_none(obj, "ext_views.count"),
            retweetedTweet=Tweet.parse(rt_obj, res) if rt_obj else None,
            quotedTweet=Tweet.parse(qt_obj, res) if qt_obj else None,
            place=Place.parse(obj["place"]) if obj.get("place") else None,
            coordinates=Coordinates.parse(obj),
            inReplyToTweetId=int_or_none(obj, "in_reply_to_status_id_str"),
            inReplyToUser=_get_reply_user(obj, res),
            source=obj.get("source", None),
            sourceUrl=_get_source_url(obj),
            sourceLabel=_get_source_label(obj),
            media=Media.parse(obj),
        )


@dataclass
class MediaPhoto(JSONTrait):
    url: str

    @staticmethod
    def parse(obj: dict):
        return MediaPhoto(
            url=obj["media_url_https"],
        )


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
            views=int_or_none(obj, "mediaStats.viewCount"),
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
