from httpx import Response

from .accounts_pool import AccountsPool
from .constants import GQL_FEATURES, GQL_URL, SEARCH_PARAMS, SEARCH_URL
from .logger import logger
from .models import Tweet, User
from .queue_client import QueueClient, req_id
from .utils import encode_params, find_obj, get_by_path, to_old_obj, to_old_rep


class API:
    def __init__(self, pool: AccountsPool, debug=False):
        self.pool = pool
        self.debug = debug

    # http helpers

    def _is_end(self, rep: Response, q: str, res: list, cur: str | None, cnt: int, lim: int):
        new_count = len(res)
        new_total = cnt + new_count

        is_res = new_count > 0
        is_cur = cur is not None
        is_lim = lim > 0 and new_total >= lim

        stats = f"{q} {new_total:,d} (+{new_count:,d})"
        flags = f"res={int(is_res)} cur={int(is_cur)} lim={int(is_lim)}"
        logger.debug(" ".join([stats, flags, req_id(rep)]))

        return rep if is_res else None, new_total, is_cur and not is_lim

    def _get_cursor(self, obj: dict):
        if cur := find_obj(obj, lambda x: x.get("cursorType") == "Bottom"):
            return cur.get("value")
        return None

    # search

    async def search_raw(self, q: str, limit=-1):
        queue, cursor, count, active = "search", None, 0, True

        async with QueueClient(self.pool, queue, self.debug) as client:
            while active:
                params = {**SEARCH_PARAMS, "q": q, "count": 20}
                params["cursor" if cursor else "requestContext"] = cursor if cursor else "launch"

                rep = await client.get(SEARCH_URL, params=params)
                obj = rep.json()

                tweets = obj.get("globalObjects", {}).get("tweets", [])
                cursor = self._get_cursor(obj)

                rep, count, active = self._is_end(rep, q, tweets, cursor, count, limit)
                if rep is None:
                    return

                yield rep

    async def search(self, q: str, limit=-1):
        twids = set()
        async for rep in self.search_raw(q, limit=limit):
            res = rep.json()
            obj = res.get("globalObjects", {})
            for x in list(obj.get("tweets", {}).values()):
                if x["id_str"] not in twids:
                    twids.add(x["id_str"])
                    yield Tweet.parse(x, obj)

    # gql helpers

    async def _gql_items(self, op: str, kv: dict, limit=-1):
        queue, cursor, count, active = op.split("/")[-1], None, 0, True

        async with QueueClient(self.pool, queue, self.debug) as client:
            while active:
                params = {"variables": {**kv, "cursor": cursor}, "features": GQL_FEATURES}

                rep = await client.get(f"{GQL_URL}/{op}", params=encode_params(params))
                obj = rep.json()

                entries = get_by_path(obj, "entries") or []
                entries = [x for x in entries if not x["entryId"].startswith("cursor-")]
                cursor = self._get_cursor(obj)

                rep, count, active = self._is_end(rep, queue, entries, cursor, count, limit)
                if rep is None:
                    return

                yield rep

    async def _gql_item(self, op: str, kv: dict, ft: dict | None = None):
        ft = ft or {}
        queue = op.split("/")[-1]
        async with QueueClient(self.pool, queue, self.debug) as client:
            params = {"variables": {**kv}, "features": {**GQL_FEATURES, **ft}}
            return await client.get(f"{GQL_URL}/{op}", params=encode_params(params))

    # user_by_id

    async def user_by_id_raw(self, uid: int):
        op = "GazOglcBvgLigl3ywt6b3Q/UserByRestId"
        kv = {"userId": str(uid), "withSafetyModeUserFields": True}
        return await self._gql_item(op, kv)

    async def user_by_id(self, uid: int):
        rep = await self.user_by_id_raw(uid)
        res = rep.json()
        return User.parse(to_old_obj(res["data"]["user"]["result"]))

    # user_by_login

    async def user_by_login_raw(self, login: str):
        op = "sLVLhk0bGj3MVFEKTdax1w/UserByScreenName"
        kv = {"screen_name": login, "withSafetyModeUserFields": True}
        return await self._gql_item(op, kv)

    async def user_by_login(self, login: str):
        rep = await self.user_by_login_raw(login)
        res = rep.json()
        return User.parse(to_old_obj(res["data"]["user"]["result"]))

    # tweet_details

    async def tweet_details_raw(self, twid: int):
        op = "zXaXQgfyR4GxE21uwYQSyA/TweetDetail"
        kv = {
            "focalTweetId": str(twid),
            "referrer": "tweet",  # tweet, profile
            "with_rux_injections": False,
            "includePromotedContent": True,
            "withCommunity": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withBirdwatchNotes": True,
            "withVoice": True,
            "withV2Timeline": True,
            "withDownvotePerspective": False,
            "withReactionsMetadata": False,
            "withReactionsPerspective": False,
            "withSuperFollowsTweetFields": False,
            "withSuperFollowsUserFields": False,
        }
        ft = {
            "responsive_web_twitter_blue_verified_badge_is_enabled": True,
            "longform_notetweets_richtext_consumption_enabled": True,
        }
        return await self._gql_item(op, kv, ft)

    async def tweet_details(self, twid: int):
        rep = await self.tweet_details_raw(twid)
        obj = to_old_rep(rep.json())
        return Tweet.parse(obj["tweets"][str(twid)], obj)

    # followers

    async def followers_raw(self, uid: int, limit=-1):
        op = "djdTXDIk2qhd4OStqlUFeQ/Followers"
        kv = {"userId": str(uid), "count": 20, "includePromotedContent": False}
        async for x in self._gql_items(op, kv, limit=limit):
            yield x

    async def followers(self, uid: int, limit=-1):
        async for rep in self.followers_raw(uid, limit=limit):
            obj = to_old_rep(rep.json())
            for _, v in obj["users"].items():
                yield User.parse(v)

    # following

    async def following_raw(self, uid: int, limit=-1):
        op = "IWP6Zt14sARO29lJT35bBw/Following"
        kv = {"userId": str(uid), "count": 20, "includePromotedContent": False}
        async for x in self._gql_items(op, kv, limit=limit):
            yield x

    async def following(self, uid: int, limit=-1):
        async for rep in self.following_raw(uid, limit=limit):
            obj = to_old_rep(rep.json())
            for _, v in obj["users"].items():
                yield User.parse(v)

    # retweeters

    async def retweeters_raw(self, twid: int, limit=-1):
        op = "U5f_jm0CiLmSfI1d4rGleQ/Retweeters"
        kv = {"tweetId": str(twid), "count": 20, "includePromotedContent": True}
        async for x in self._gql_items(op, kv, limit=limit):
            yield x

    async def retweeters(self, twid: int, limit=-1):
        async for rep in self.retweeters_raw(twid, limit=limit):
            obj = to_old_rep(rep.json())
            for _, v in obj["users"].items():
                yield User.parse(v)

    # favoriters

    async def favoriters_raw(self, twid: int, limit=-1):
        op = "vcTrPlh9ovFDQejz22q9vg/Favoriters"
        kv = {"tweetId": str(twid), "count": 20, "includePromotedContent": True}
        async for x in self._gql_items(op, kv, limit=limit):
            yield x

    async def favoriters(self, twid: int, limit=-1):
        async for rep in self.favoriters_raw(twid, limit=limit):
            obj = to_old_rep(rep.json())
            for _, v in obj["users"].items():
                yield User.parse(v)

    # user_tweets

    async def user_tweets_raw(self, uid: int, limit=-1):
        op = "CdG2Vuc1v6F5JyEngGpxVw/UserTweets"
        kv = {
            "userId": str(uid),
            "count": 40,
            "includePromotedContent": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice": True,
            "withV2Timeline": True,
        }
        async for x in self._gql_items(op, kv, limit=limit):
            yield x

    async def user_tweets(self, uid: int, limit=-1):
        async for rep in self.user_tweets_raw(uid, limit=limit):
            obj = to_old_rep(rep.json())
            for _, v in obj["tweets"].items():
                yield Tweet.parse(v, obj)

    # user_tweets_and_replies

    async def user_tweets_and_replies_raw(self, uid: int, limit=-1):
        op = "zQxfEr5IFxQ2QZ-XMJlKew/UserTweetsAndReplies"
        kv = {
            "userId": str(uid),
            "count": 40,
            "includePromotedContent": True,
            "withCommunity": True,
            "withVoice": True,
            "withV2Timeline": True,
        }
        async for x in self._gql_items(op, kv, limit=limit):
            yield x

    async def user_tweets_and_replies(self, uid: int, limit=-1):
        async for rep in self.user_tweets_and_replies_raw(uid, limit=limit):
            obj = to_old_rep(rep.json())
            for _, v in obj["tweets"].items():
                yield Tweet.parse(v, obj)
