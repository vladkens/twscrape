from contextlib import aclosing
from datetime import datetime
from typing import Any, AsyncGenerator

from .accounts_pool import AccountsPool
from .api import API
from .models import Tweet, User


class XApiNotFoundError(Exception):
    pass


def parse_limit(value: str | None, default: int = 20) -> int:
    if value is None:
        return default
    try:
        limit = int(value)
    except ValueError as error:
        raise ValueError("limit must be an integer") from error
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    return limit


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise ValueError("include_replies must be true or false")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def user_to_dict(user: User) -> dict[str, Any]:
    return {
        "id": user.id_str,
        "username": user.username,
        "fullname": user.displayname or "",
        "bio": user.rawDescription or "",
        "location": user.location or "",
        "url": user.url or "",
        "userPic": user.profileImageUrl or "",
        "banner": user.profileBannerUrl or "",
        "followers": user.followersCount or 0,
        "following": user.friendsCount or 0,
        "tweets": user.statusesCount or 0,
        "likes": user.favouritesCount or 0,
        "media": user.mediaCount or 0,
        "listed": user.listedCount or 0,
        "verified": bool(user.verified),
        "blue": bool(user.blue),
        "protected": bool(user.protected),
        "joinDate": _iso(user.created),
        "pinnedTweetIds": [str(tweet_id) for tweet_id in user.pinnedIds],
    }


def _media_to_list(tweet: Tweet) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for photo in tweet.media.photos:
        items.append({"kind": "photo", "url": photo.url, "thumb": "", "altText": ""})
    for video in tweet.media.videos:
        variants = video.variants or []
        best = max(variants, key=lambda variant: variant.bitrate or 0).url if variants else ""
        items.append(
            {
                "kind": "video",
                "url": best,
                "thumb": video.thumbnailUrl or "",
                "altText": "",
            }
        )
    for animated in tweet.media.animated:
        items.append(
            {
                "kind": "gif",
                "url": animated.videoUrl or "",
                "thumb": animated.thumbnailUrl or "",
                "altText": "",
            }
        )
    return items


def tweet_to_dict(tweet: Tweet, depth: int = 0) -> dict[str, Any]:
    nested = depth < 2
    return {
        "id": tweet.id_str,
        "url": tweet.url,
        "user": user_to_dict(tweet.user),
        "text": tweet.rawContent or "",
        "lang": tweet.lang or "",
        "date": _iso(tweet.date),
        "replies": tweet.replyCount or 0,
        "retweets": tweet.retweetCount or 0,
        "likes": tweet.likeCount or 0,
        "quotes": tweet.quoteCount or 0,
        "views": tweet.viewCount or 0,
        "bookmarks": tweet.bookmarkedCount or 0,
        "conversationId": tweet.conversationIdStr,
        "inReplyToTweetId": tweet.inReplyToTweetIdStr,
        "inReplyToUsername": tweet.inReplyToScreenName,
        "hashtags": list(tweet.hashtags or []),
        "cashtags": list(tweet.cashtags or []),
        "mentions": [user.username for user in (tweet.mentionedUsers or [])],
        "links": [link.url for link in (tweet.links or [])],
        "media": _media_to_list(tweet),
        "quote": tweet_to_dict(tweet.quotedTweet, depth + 1)
        if nested and tweet.quotedTweet
        else None,
        "retweet": tweet_to_dict(tweet.retweetedTweet, depth + 1)
        if nested and tweet.retweetedTweet
        else None,
    }


async def _collect(source: AsyncGenerator[Tweet, None], limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    async with aclosing(source):
        async for tweet in source:
            items.append(tweet_to_dict(tweet))
            if len(items) >= limit:
                break
    return items


async def _collect_users(source: AsyncGenerator[User, None], limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    async with aclosing(source):
        async for user in source:
            items.append(user_to_dict(user))
            if len(items) >= limit:
                break
    return items


class XApiService:
    """Read-only JSON facade over twscrape using the existing account pool."""

    def __init__(self, pool: AccountsPool):
        self.api = API(pool)

    async def user(self, username: str) -> dict[str, Any]:
        user = await self.api.user_by_login(username)
        if user is None:
            raise XApiNotFoundError(f'User "{username}" not found')
        return user_to_dict(user)

    async def user_tweets(self, username: str, limit: int, include_replies: bool) -> dict[str, Any]:
        user = await self.api.user_by_login(username)
        if user is None:
            raise XApiNotFoundError(f'User "{username}" not found')
        source = (
            self.api.user_tweets_and_replies(user.id, limit=limit)
            if include_replies
            else self.api.user_tweets(user.id, limit=limit)
        )
        tweets = await _collect(source, limit)
        return {"user": user_to_dict(user), "tweets": tweets, "count": len(tweets)}

    async def followers(self, username: str, limit: int) -> dict[str, Any]:
        return await self._social_graph(username, limit, "followers")

    async def following(self, username: str, limit: int) -> dict[str, Any]:
        return await self._social_graph(username, limit, "following")

    async def _social_graph(self, username: str, limit: int, kind: str) -> dict[str, Any]:
        user = await self.api.user_by_login(username)
        if user is None:
            raise XApiNotFoundError(f'User "{username}" not found')
        source = (
            self.api.followers(user.id, limit=limit)
            if kind == "followers"
            else self.api.following(user.id, limit=limit)
        )
        users = await _collect_users(source, limit)
        return {
            "kind": kind,
            "user": user_to_dict(user),
            "users": users,
            "count": len(users),
        }

    async def tweet(self, tweet_id: int) -> dict[str, Any]:
        tweet = await self.api.tweet_details(tweet_id)
        if tweet is None:
            raise XApiNotFoundError(f"Tweet {tweet_id} not found")
        return tweet_to_dict(tweet)

    async def search(self, query: str, limit: int) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise ValueError("q is required")
        if len(query) > 500:
            raise ValueError("q must not exceed 500 characters")
        tweets = await _collect(self.api.search(query, limit=limit), limit)
        return {"kind": "tweets", "query": query, "tweets": tweets, "count": len(tweets)}
