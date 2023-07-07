from httpx import Response

from .accounts_pool import AccountsPool
from .constants import GQL_FEATURES, GQL_URL
from .logger import logger
from .models import Tweet, User
from .queue_client import QueueClient, req_id
from .utils import encode_params, find_obj, get_by_path, to_old_obj, to_old_rep

SEARCH_FEATURES = {
    "rweb_lists_timeline_redesign_enabled": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": False,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "responsive_web_media_download_video_enabled": False,
    "longform_notetweets_inline_media_enabled": True,
}


class API:
    def __init__(self, pool: AccountsPool | None = None, debug=False):
        self.pool = pool if pool is not None else AccountsPool()
        self.debug = debug

    # general helpers

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

    # gql helpers

    async def _gql_items(self, op: str, kv: dict, ft: dict | None = None, limit=-1):
        queue, cursor, count, active = op.split("/")[-1], None, 0, True
        kv, ft = {**kv}, {**GQL_FEATURES, **(ft or {})}

        async with QueueClient(self.pool, queue, self.debug) as client:
            while active:
                params = {"variables": kv, "features": ft}
                if cursor is not None:
                    params["variables"]["cursor"] = cursor
                if queue in ("SearchTimeline", "ListLatestTweetsTimeline"):
                    params["fieldToggles"] = {"withArticleRichContentState": False}

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

    # search

    async def search_raw(self, q: str, limit=-1, kv=None):
        op = "nK1dw4oV3k4w5TdtcAdSww/SearchTimeline"
        kv = {
            "rawQuery": q,
            "count": 20,
            "product": "Latest",
            "querySource": "typed_query",
            **(kv or {}),
        }
        async for x in self._gql_items(op, kv, ft=SEARCH_FEATURES, limit=limit):
            yield x

    async def search(self, q: str, limit=-1, kv=None):
        twids = set()
        async for rep in self.search_raw(q, limit=limit, kv=kv):
            obj = to_old_rep(rep.json())
            for x in obj["tweets"].values():
                tmp = Tweet.parse(x, obj)
                if tmp.id not in twids:
                    twids.add(tmp.id)
                    yield tmp

    # user_by_id

    async def user_by_id_raw(self, uid: int, kv=None):
        op = "GazOglcBvgLigl3ywt6b3Q/UserByRestId"
        kv = {"userId": str(uid), "withSafetyModeUserFields": True, **(kv or {})}
        return await self._gql_item(op, kv)

    async def user_by_id(self, uid: int, kv=None):
        rep = await self.user_by_id_raw(uid, kv=kv)
        res = rep.json()
        return User.parse(to_old_obj(res["data"]["user"]["result"]))

    # user_by_login

    async def user_by_login_raw(self, login: str, kv=None):
        op = "sLVLhk0bGj3MVFEKTdax1w/UserByScreenName"
        kv = {"screen_name": login, "withSafetyModeUserFields": True, **(kv or {})}
        return await self._gql_item(op, kv)

    async def user_by_login(self, login: str, kv=None):
        rep = await self.user_by_login_raw(login, kv=kv)
        res = rep.json()
        return User.parse(to_old_obj(res["data"]["user"]["result"]))

    # tweet_details

    async def tweet_details_raw(self, twid: int, kv=None):
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
            **(kv or {}),
        }
        ft = {
            "responsive_web_twitter_blue_verified_badge_is_enabled": True,
            "longform_notetweets_richtext_consumption_enabled": True,
        }
        return await self._gql_item(op, kv, ft)

    async def tweet_details(self, twid: int, kv=None):
        rep = await self.tweet_details_raw(twid, kv=kv)
        obj = to_old_rep(rep.json())
        doc = obj["tweets"].get(str(twid), None)
        return Tweet.parse(doc, obj) if doc else None

    # followers

    async def followers_raw(self, uid: int, limit=-1, kv=None):
        op = "djdTXDIk2qhd4OStqlUFeQ/Followers"
        kv = {"userId": str(uid), "count": 20, "includePromotedContent": False, **(kv or {})}
        async for x in self._gql_items(op, kv, limit=limit):
            yield x

    async def followers(self, uid: int, limit=-1, kv=None):
        async for rep in self.followers_raw(uid, limit=limit, kv=kv):
            obj = to_old_rep(rep.json())
            for _, v in obj["users"].items():
                yield User.parse(v)

    # following

    async def following_raw(self, uid: int, limit=-1, kv=None):
        op = "IWP6Zt14sARO29lJT35bBw/Following"
        kv = {"userId": str(uid), "count": 20, "includePromotedContent": False, **(kv or {})}
        async for x in self._gql_items(op, kv, limit=limit):
            yield x

    async def following(self, uid: int, limit=-1, kv=None):
        async for rep in self.following_raw(uid, limit=limit, kv=kv):
            obj = to_old_rep(rep.json())
            for _, v in obj["users"].items():
                yield User.parse(v)

    # retweeters

    async def retweeters_raw(self, twid: int, limit=-1, kv=None):
        op = "U5f_jm0CiLmSfI1d4rGleQ/Retweeters"
        kv = {"tweetId": str(twid), "count": 20, "includePromotedContent": True, **(kv or {})}
        async for x in self._gql_items(op, kv, limit=limit):
            yield x

    async def retweeters(self, twid: int, limit=-1, kv=None):
        async for rep in self.retweeters_raw(twid, limit=limit, kv=kv):
            obj = to_old_rep(rep.json())
            for _, v in obj["users"].items():
                yield User.parse(v)

    # favoriters

    async def favoriters_raw(self, twid: int, limit=-1, kv=None):
        op = "vcTrPlh9ovFDQejz22q9vg/Favoriters"
        kv = {"tweetId": str(twid), "count": 20, "includePromotedContent": True, **(kv or {})}
        async for x in self._gql_items(op, kv, limit=limit):
            yield x

    async def favoriters(self, twid: int, limit=-1, kv=None):
        async for rep in self.favoriters_raw(twid, limit=limit, kv=kv):
            obj = to_old_rep(rep.json())
            for _, v in obj["users"].items():
                yield User.parse(v)

    # user_tweets

    async def user_tweets_raw(self, uid: int, limit=-1, kv=None):
        op = "CdG2Vuc1v6F5JyEngGpxVw/UserTweets"
        kv = {
            "userId": str(uid),
            "count": 40,
            "includePromotedContent": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice": True,
            "withV2Timeline": True,
            **(kv or {}),
        }
        async for x in self._gql_items(op, kv, limit=limit):
            yield x

    async def user_tweets(self, uid: int, limit=-1, kv=None):
        async for rep in self.user_tweets_raw(uid, limit=limit, kv=kv):
            obj = to_old_rep(rep.json())
            for _, v in obj["tweets"].items():
                yield Tweet.parse(v, obj)

    # user_tweets_and_replies

    async def user_tweets_and_replies_raw(self, uid: int, limit=-1, kv=None):
        op = "zQxfEr5IFxQ2QZ-XMJlKew/UserTweetsAndReplies"
        kv = {
            "userId": str(uid),
            "count": 40,
            "includePromotedContent": True,
            "withCommunity": True,
            "withVoice": True,
            "withV2Timeline": True,
            **(kv or {}),
        }
        async for x in self._gql_items(op, kv, limit=limit):
            yield x

    async def user_tweets_and_replies(self, uid: int, limit=-1, kv=None):
        async for rep in self.user_tweets_and_replies_raw(uid, limit=limit, kv=kv):
            obj = to_old_rep(rep.json())
            for _, v in obj["tweets"].items():
                yield Tweet.parse(v, obj)

    # list timeline

    async def list_timeline_raw(self, list_id: int, limit=-1, kv=None):
        op = "2Vjeyo_L0nizAUhHe3fKyA/ListLatestTweetsTimeline"
        kv = {
            "listId": str(list_id),
            "count": 20,
            **(kv or {}),
        }
        async for x in self._gql_items(op, kv, ft=SEARCH_FEATURES, limit=limit):
            yield x

    async def list_timeline(self, list_id: int, limit=-1, kv=None):
        async for rep in self.list_timeline_raw(list_id, limit=limit, kv=kv):
            obj = to_old_rep(rep.json())
            for x in obj["tweets"].values():
                yield Tweet.parse(x, obj)
