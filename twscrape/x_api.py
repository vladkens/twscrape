from contextlib import aclosing
from datetime import datetime
from typing import Any, AsyncGenerator

from .accounts_pool import AccountsPool
from .api import API
from .models import Tweet, User, parse_user


class XApiNotFoundError(Exception):
    pass


class XApiUnavailableError(Exception):
    def __init__(self, message: str, reason: str):
        super().__init__(message)
        self.reason = reason


def _unavailable_user(rep: Any) -> tuple[str, str] | None:
    try:
        payload = rep.json()
        result = payload.get("data", {}).get("user", {}).get("result", {})
    except (AttributeError, TypeError, ValueError):
        return None
    if not isinstance(result, dict) or result.get("__typename") != "UserUnavailable":
        return None
    message = str(result.get("message") or "User is unavailable")
    reason = str(result.get("reason") or "Unavailable")
    return message, reason


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


def parse_by(value: str | None) -> str:
    """标识符类型：username（默认）或 id。

    爬虫侧存的是数字 id，用户名会变，按 id 查才稳定。
    """
    if value is None:
        return "username"
    normalized = value.lower()
    if normalized in {"username", "name", "login"}:
        return "username"
    if normalized in {"id", "uid", "user_id"}:
        return "id"
    raise ValueError("by must be username or id")


def parse_uid(value: str) -> int:
    try:
        uid = int(value)
    except ValueError as error:
        raise ValueError("user id must be an integer") from error
    if uid <= 0:
        raise ValueError("user id must be positive")
    return uid


def parse_bool(value: str | None, default: bool = False, name: str = "include_replies") -> bool:
    if value is None:
        return default
    normalized = value.lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise ValueError(f"{name} must be true or false")


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

    async def _user(self, ident: str, by: str = "username") -> User:
        username = ident
        if by == "id":
            rep = await self.api.user_by_id_raw(parse_uid(ident))
        else:
            rep = await self.api.user_by_login_raw(ident)
        if rep is None:
            raise XApiNotFoundError(f'User "{username}" not found')
        unavailable = _unavailable_user(rep)
        if unavailable is not None:
            message, reason = unavailable
            if reason.casefold() == "suspended":
                raise XApiUnavailableError(f'User "{username}" is suspended', reason)
            raise XApiUnavailableError(f'User "{username}" is unavailable: {message}', reason)
        user = parse_user(rep)
        if user is None:
            raise XApiNotFoundError(f'User "{username}" not found')
        return user

    async def user(self, ident: str, by: str = "username") -> dict[str, Any]:
        user = await self._user(ident, by)
        return user_to_dict(user)

    async def user_tweets(
        self, ident: str, limit: int, include_replies: bool, by: str = "username"
    ) -> dict[str, Any]:
        user = await self._user(ident, by)
        source = (
            self.api.user_tweets_and_replies(user.id, limit=limit)
            if include_replies
            else self.api.user_tweets(user.id, limit=limit)
        )
        tweets = await _collect(source, limit)
        return {"user": user_to_dict(user), "tweets": tweets, "count": len(tweets)}

    async def followers(
        self, ident: str, limit: int, by: str = "username", skip_user: bool = False
    ) -> dict[str, Any]:
        return await self._social_graph(ident, limit, "followers", by, skip_user)

    async def following(
        self, ident: str, limit: int, by: str = "username", skip_user: bool = False
    ) -> dict[str, Any]:
        return await self._social_graph(ident, limit, "following", by, skip_user)

    async def following_batch(
        self, ids: list[int], limit: int, skip_user: bool = True
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for uid in ids:
            ident = str(uid)
            try:
                item = await self._social_graph(ident, limit, "following", "id", skip_user)
                results.append(
                    {
                        "id": ident,
                        "ok": True,
                        "users": item["users"],
                        "count": item["count"],
                    }
                )
            except XApiNotFoundError as error:
                results.append({"id": ident, "ok": False, "error": str(error), "status": 404})
            except XApiUnavailableError as error:
                results.append(
                    {
                        "id": ident,
                        "ok": False,
                        "error": str(error),
                        "status": 403,
                        "reason": error.reason.casefold(),
                    }
                )
            except ValueError as error:
                results.append({"id": ident, "ok": False, "error": str(error), "status": 400})
        return {"results": results}

    async def _social_graph(
        self,
        ident: str,
        limit: int,
        kind: str,
        by: str = "username",
        skip_user: bool = False,
    ) -> dict[str, Any]:
        # 按 id 调用时已经有 uid，skip_user 可以省掉一次 user 查询——
        # 轮询几百个账号时这一半的请求量很实在。
        if by == "id" and skip_user:
            uid = parse_uid(ident)
            user = None
        else:
            user = await self._user(ident, by)
            uid = user.id
        source = (
            self.api.followers(uid, limit=limit)
            if kind == "followers"
            else self.api.following(uid, limit=limit)
        )
        users = await _collect_users(source, limit)
        return {
            "kind": kind,
            "user": user_to_dict(user) if user is not None else None,
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
