import json
from time import time
from typing import Awaitable, Callable

from httpx import AsyncClient, HTTPStatusError, Response
from loguru import logger

from .models import Tweet, User
from .pool import AccountsPool
from .utils import encode_params, find_item, to_old_obj, to_search_like

BASIC_SEARCH_PARAMS = """
include_profile_interstitial_type=1
include_blocking=1
include_blocked_by=1
include_followed_by=1
include_want_retweets=1
include_mute_edge=1
include_can_dm=1
include_can_media_tag=1
include_ext_has_nft_avatar=1
include_ext_is_blue_verified=1
include_ext_verified_type=1
include_ext_profile_image_shape=1
skip_status=1
cards_platform=Web-12
include_cards=1
include_ext_alt_text=true
include_ext_limited_action_results=false
include_quote_count=true
include_reply_count=1
tweet_mode=extended
include_ext_views=true
include_entities=true
include_user_entities=true
include_ext_media_color=true
include_ext_media_availability=true
include_ext_sensitive_media_warning=true
include_ext_trusted_friends_metadata=true
send_error_codes=true
simple_quoted_tweet=true
tweet_search_mode=live
query_source=recent_search_click
pc=1
spelling_corrections=1
include_ext_edit_control=true
ext=mediaStats%2ChighlightedLabel%2ChasNftAvatar%2CvoiceInfo%2CbirdwatchPivot%2Cenrichments%2CsuperFollowMetadata%2CunmentionInfo%2CeditControl%2Cvibe
"""

BASE_FEATURES = {
    "blue_business_profile_image_shape_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    #
    "tweetypie_unmention_optimization_enabled": True,
    "vibe_api_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": False,
    "interactive_text_enabled": True,
    "responsive_web_text_conversations_enabled": False,
    "longform_notetweets_rich_text_read_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

SEARCH_URL = "https://api.twitter.com/2/search/adaptive.json"
SEARCH_PARAMS = dict(x.split("=") for x in BASIC_SEARCH_PARAMS.splitlines() if x)
GRAPHQL_URL = "https://twitter.com/i/api/graphql/"


def filter_null(obj: dict):
    try:
        return {k: v for k, v in obj.items() if v is not None}
    except AttributeError:
        return obj


def json_params(obj: dict):
    return {k: json.dumps(filter_null(v), separators=(",", ":")) for k, v in obj.items()}


def get_ql_entries(obj: dict) -> list[dict]:
    entries = find_item(obj, "entries")
    return entries or []


class Search:
    def __init__(self, pool: AccountsPool):
        self.pool = pool

        # http helpers

    def _limit_msg(self, rep: Response):
        lr = rep.headers.get("x-rate-limit-remaining", -1)
        ll = rep.headers.get("x-rate-limit-limit", -1)
        return f"{lr}/{ll}"

    def _is_end(self, rep: Response, q: str, res: list, cur: str | None, cnt: int, lim: int):
        new_count = len(res)
        new_total = cnt + new_count

        is_res = new_count > 0
        is_cur = cur is not None
        is_lim = lim > 0 and new_total >= lim

        stats = f"{q} {new_total:,d} (+{new_count:,d})"
        flags = f"res={int(is_res)} cur={int(is_cur)} lim={int(is_lim)}"
        logger.debug(" ".join([stats, flags, self._limit_msg(rep)]))

        return new_total, not is_res, not is_cur or is_lim

    async def _inf_req(self, queue: str, cb: Callable[[AsyncClient], Awaitable[Response]]):
        while True:
            account = await self.pool.get_account_or_wait(queue)

            try:
                while True:
                    rep = await cb(account.client)
                    rep.raise_for_status()
                    yield rep
            except HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.debug(f"Rate limit for account={account.username} on queue={queue}")
                    reset_ts = int(e.response.headers.get("x-rate-limit-reset", 0))
                    account.update_limit(queue, reset_ts)
                    continue

                if e.response.status_code == 403:
                    logger.debug(f"Account={account.username} is banned on queue={queue}")
                    reset_ts = int(time.time() + 60 * 60)  # 1 hour
                    account.update_limit(queue, reset_ts)
                    continue

                logger.error(f"[{e.response.status_code}] {e.request.url}\n{e.response.text}")
                raise e
            finally:
                account.unlock(queue)

    def _get_search_cursor(self, res: dict) -> str | None:
        try:
            for x in res["timeline"]["instructions"]:
                entry = x.get("replaceEntry", None)
                if entry is not None and entry["entryIdToReplace"] == "sq-cursor-bottom":
                    return entry["entry"]["content"]["operation"]["cursor"]["value"]

                for entry in x.get("addEntries", {}).get("entries", []):
                    if entry["entryId"] == "sq-cursor-bottom":
                        return entry["content"]["operation"]["cursor"]["value"]
        except Exception as e:
            logger.debug(e)
            return None

    def get_ql_entries(self, obj: dict) -> list[dict]:
        entries = find_item(obj, "entries")
        return entries or []

    def _get_ql_cursor(self, obj: dict) -> str | None:
        try:
            for entry in self.get_ql_entries(obj):
                if entry["entryId"].startswith("cursor-bottom-"):
                    return entry["content"]["value"]
            return None
        except Exception:
            return None

    async def _ql_items(self, op: str, kv: dict, ft: dict = {}, limit=-1):
        queue, cursor, count = op.split("/")[-1], None, 0

        async def _get(client: AsyncClient):
            params = {"variables": {**kv, "cursor": cursor}, "features": BASE_FEATURES}
            return await client.get(f"{GRAPHQL_URL}/{op}", params=encode_params(params))

        async for rep in self._inf_req(queue, _get):
            obj = rep.json()

            # cursor-top / cursor-bottom always present
            entries = self.get_ql_entries(obj)
            entries = [x for x in entries if not x["entryId"].startswith("cursor-")]
            cursor = self._get_ql_cursor(obj)

            check = self._is_end(rep, queue, entries, cursor, count, limit)
            count, end_before, end_after = check

            if end_before:
                return

            yield rep

            if end_after:
                return

    async def _ql_item(self, op: str, kv: dict, ft: dict = {}):
        variables, features = {**kv}, {**BASE_FEATURES, **ft}
        params = {"variables": variables, "features": features}

        async def _get(client: AsyncClient):
            return await client.get(f"{GRAPHQL_URL}/{op}", params=encode_params(params))

        queue = op.split("/")[-1]
        async for rep in self._inf_req(queue, _get):
            logger.debug(f"{queue} {self._limit_msg(rep)}")
            return rep

        raise Exception("No response")  # todo

    # search

    async def search_raw(self, q: str, limit=-1):
        queue, cursor, count = "search", None, 0

        async def _get(client: AsyncClient):
            params = {**SEARCH_PARAMS, "q": q, "count": 20}
            params["cursor" if cursor else "requestContext"] = cursor if cursor else "launch"
            return await client.get(SEARCH_URL, params=params)

        async for rep in self._inf_req(queue, _get):
            data = rep.json()

            cursor = self._get_search_cursor(data)
            tweets = data.get("globalObjects", {}).get("tweets", [])

            check = self._is_end(rep, q, tweets, cursor, count, limit)
            count, end_before, end_after = check

            if end_before:
                return

            yield rep

            if end_after:
                return

    async def search(self, q: str, limit=-1):
        async for rep in self.search_raw(q, limit=limit):
            res = rep.json()
            obj = res.get("globalObjects", {})
            for x in list(obj.get("tweets", {}).values()):
                yield Tweet.parse(x, obj)

    # user_by_id

    async def user_by_id_raw(self, uid: int):
        op = "GazOglcBvgLigl3ywt6b3Q/UserByRestId"
        kv = {"userId": str(uid), "withSafetyModeUserFields": True}
        return await self._ql_item(op, kv)

    async def user_by_id(self, uid: int):
        rep = await self.user_by_id_raw(uid)
        res = rep.json()
        return User.parse(to_old_obj(res["data"]["user"]["result"]))

    # user_by_login

    async def user_by_login_raw(self, login: str):
        op = "sLVLhk0bGj3MVFEKTdax1w/UserByScreenName"
        kv = {"screen_name": login, "withSafetyModeUserFields": True}
        return await self._ql_item(op, kv)

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
        return await self._ql_item(op, kv, ft)

    async def tweet_details(self, twid: int):
        rep = await self.tweet_details_raw(twid)
        obj = to_search_like(rep.json())
        return Tweet.parse(obj["tweets"][str(twid)], obj)

    # followers

    async def followers_raw(self, uid: int, limit=-1):
        op = "djdTXDIk2qhd4OStqlUFeQ/Followers"
        kv = {"userId": str(uid), "count": 20, "includePromotedContent": False}
        async for x in self._ql_items(op, kv, limit=limit):
            yield x

    async def followers(self, uid: int, limit=-1):
        async for rep in self.followers_raw(uid, limit=limit):
            obj = to_search_like(rep.json())
            for _, v in obj["users"].items():
                yield User.parse(v)

    # following

    async def following_raw(self, uid: int, limit=-1):
        op = "IWP6Zt14sARO29lJT35bBw/Following"
        kv = {"userId": str(uid), "count": 20, "includePromotedContent": False}
        async for x in self._ql_items(op, kv, limit=limit):
            yield x

    async def following(self, uid: int, limit=-1):
        async for rep in self.following_raw(uid, limit=limit):
            obj = to_search_like(rep.json())
            for _, v in obj["users"].items():
                yield User.parse(v)

    # retweeters

    async def retweeters_raw(self, twid: int, limit=-1):
        op = "U5f_jm0CiLmSfI1d4rGleQ/Retweeters"
        kv = {"tweetId": str(twid), "count": 20, "includePromotedContent": True}
        async for x in self._ql_items(op, kv, limit=limit):
            yield x

    async def retweeters(self, twid: int, limit=-1):
        async for rep in self.retweeters_raw(twid, limit=limit):
            obj = to_search_like(rep.json())
            for _, v in obj["users"].items():
                yield User.parse(v)

    # favoriters

    async def favoriters_raw(self, twid: int, limit=-1):
        op = "vcTrPlh9ovFDQejz22q9vg/Favoriters"
        kv = {"tweetId": str(twid), "count": 20, "includePromotedContent": True}
        async for x in self._ql_items(op, kv, limit=limit):
            yield x

    async def favoriters(self, twid: int, limit=-1):
        async for rep in self.favoriters_raw(twid, limit=limit):
            obj = to_search_like(rep.json())
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
        async for x in self._ql_items(op, kv, limit=limit):
            yield x

    async def user_tweets(self, uid: int, limit=-1):
        async for rep in self.user_tweets_raw(uid, limit=limit):
            obj = to_search_like(rep.json())
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
        async for x in self._ql_items(op, kv, limit=limit):
            yield x

    async def user_tweets_and_replies(self, uid: int, limit=-1):
        async for rep in self.user_tweets_and_replies_raw(uid, limit=limit):
            obj = to_search_like(rep.json())
            for _, v in obj["tweets"].items():
                yield Tweet.parse(v, obj)
