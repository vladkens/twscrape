import json
from typing import Awaitable, Callable

from httpx import AsyncClient, HTTPStatusError, Response
from loguru import logger

from .models import Tweet
from .pool import AccountsPool
from .utils import find_item

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

    async def _inf_req(self, queue: str, cb: Callable[[AsyncClient], Awaitable[Response]]):
        while True:
            account = await self.pool.get_account_or_wait(queue)
            client = account.make_client()

            try:
                while True:
                    rep = await cb(client)
                    rep.raise_for_status()
                    yield rep
            except HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.debug(f"Rate limit for account={account.username} on queue={queue}")
                    account.update_limit(queue, e.response)
                    continue
                else:
                    logger.error(f"[{e.response.status_code}] {e.request.url}\n{e.response.text}")
                    raise e
            finally:
                account.unlock(queue)

    def _check_stop(self, rep: Response, txt: str, cnt: int, res: list, cur: str | None, lim: int):
        els = len(res)
        is_res, is_cur, is_lim = els > 0, cur is not None, lim > 0 and cnt >= lim

        msg = [
            f"{txt} {cnt:,d} (+{els:,d}) res={int(is_res)} cur={int(is_cur)} lim={int(is_lim)}",
            f"[{rep.headers['x-rate-limit-remaining']}/{rep.headers['x-rate-limit-limit']}]",
        ]
        logger.debug(" ".join(msg))

        end_before = not is_res
        end_after = not is_cur or is_lim
        return cnt + els, end_before, end_after

    # search

    def get_search_cursor(self, res: dict) -> str | None:
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

    async def search_raw(self, q: str, limit=-1):
        queue, cursor, all_count = "search", None, 0

        async def _get(client: AsyncClient):
            params = {**SEARCH_PARAMS, "q": q, "count": 20}
            params["cursor" if cursor else "requestContext"] = cursor if cursor else "launch"
            return await client.get(SEARCH_URL, params=params)

        async for rep in self._inf_req(queue, _get):
            data = rep.json()

            cursor = self.get_search_cursor(data)
            tweets = data.get("globalObjects", {}).get("tweets", [])

            check = self._check_stop(rep, q, all_count, tweets, cursor, limit)
            all_count, end_before, end_after = check

            if end_before:
                return

            yield rep

            if end_after:
                return

    async def search(self, q: str, limit=-1):
        async for rep in self.search_raw(q, limit=limit):
            data = rep.json()
            items = list(data.get("globalObjects", {}).get("tweets", {}).values())
            for x in items:
                yield Tweet.parse(x, data)

    # graphql

    def get_ql_cursor(self, obj: dict) -> str | None:
        try:
            for entry in get_ql_entries(obj):
                if entry["entryId"].startswith("cursor-bottom-"):
                    return entry["content"]["value"]
            return None
        except Exception:
            return None

    async def graphql_items(self, op: str, variables: dict, features: dict = {}, limit=-1):
        url = f"https://twitter.com/i/api/graphql/{op}"
        features = {**BASE_FEATURES, **features}

        queue, cursor, all_count = op.split("/")[-1], None, 0

        async def _get(client: AsyncClient):
            params = {"variables": {**variables, "cursor": cursor}, "features": features}
            return await client.get(url, params=json_params(params))

        async for rep in self._inf_req(queue, _get):
            data = rep.json()
            entries, cursor = get_ql_entries(data), self.get_ql_cursor(data)

            # cursor-top / cursor-bottom always present
            items = [x for x in entries if not x["entryId"].startswith("cursor-")]
            check = self._check_stop(rep, queue, all_count, items, cursor, limit)
            all_count, end_before, end_after = check

            if end_before:
                return

            yield rep

            if end_after:
                return

    async def graphql_item(self, op: str, variables: dict, features: dict = {}):
        url = f"https://twitter.com/i/api/graphql/{op}"
        features = {**BASE_FEATURES, **features}

        async def _get(client: AsyncClient):
            params = {"variables": {**variables}, "features": features}
            return await client.get(url, params=json_params(params))

        queue = op.split("/")[-1]
        async for rep in self._inf_req(queue, _get):
            msg = [
                f"{queue}",
                f"[{rep.headers['x-rate-limit-remaining']}/{rep.headers['x-rate-limit-limit']}]",
            ]
            logger.debug(" ".join(msg))

            return rep

    async def user_by_login(self, login: str):
        op = "sLVLhk0bGj3MVFEKTdax1w/UserByScreenName"
        kv = {"screen_name": login, "withSafetyModeUserFields": True}
        return await self.graphql_item(op, kv)

    async def user_by_id(self, uid: int):
        op = "GazOglcBvgLigl3ywt6b3Q/UserByRestId"
        kv = {"userId": str(uid), "withSafetyModeUserFields": True}
        return await self.graphql_item(op, kv)

    async def retweeters(self, twid: int, limit=-1):
        op = "U5f_jm0CiLmSfI1d4rGleQ/Retweeters"
        kv = {"tweetId": str(twid), "count": 20, "includePromotedContent": True}
        async for x in self.graphql_items(op, kv, limit=limit):
            yield x

    async def favoriters(self, twid: int, limit=-1):
        op = "vcTrPlh9ovFDQejz22q9vg/Favoriters"
        kv = {"tweetId": str(twid), "count": 20, "includePromotedContent": True}
        async for x in self.graphql_items(op, kv, limit=limit):
            yield x
