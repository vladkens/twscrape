import email.utils
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional

from .utils import get_or, int_or_none


@dataclass
class JSONTrait:
    def json(self):
        return asdict(self)


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

    @staticmethod
    def parse(obj: dict):
        return UserRef(id=int(obj["id_str"]), username=obj["screen_name"], displayname=obj["name"])


@dataclass
class User(JSONTrait):
    id: int
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

    # descriptionLinks: typing.Optional[typing.List[TextLink]] = None
    # link: typing.Optional[TextLink] = None
    # label: typing.Optional["UserLabel"] = None

    @property
    def url(self) -> str:
        return f"https://twitter.com/{self.username}"

    @staticmethod
    def parse(obj: dict):
        return User(
            id=int(obj["id_str"]),
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

    # renderedContent: str
    # source: str | None = None
    # sourceUrl: str | None = None
    # sourceLabel: str | None = None
    # media: typing.Optional[typing.List["Medium"]] = None
    # inReplyToTweetId: typing.Optional[int] = None
    # inReplyToUser: typing.Optional["User"] = None
    # card: typing.Optional["Card"] = None
    # vibe: typing.Optional["Vibe"] = None

    @property
    def url(self):
        return f"https://twitter.com/{self.user.username}/status/{self.id}"

    @staticmethod
    def parse(obj: dict, res: dict):
        rt_obj = get_or(res, f"tweets.{obj.get('retweeted_status_id_str')}")
        qt_obj = get_or(res, f"tweets.{obj.get('quoted_status_id_str')}")

        return Tweet(
            id=int(obj["id_str"]),
            date=email.utils.parsedate_to_datetime(obj["created_at"]),
            user=User.parse(res["users"][obj["user_id_str"]]),
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
        )
