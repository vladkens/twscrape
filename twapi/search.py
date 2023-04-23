import json

from httpx import AsyncClient, Response
from loguru import logger

from .pool import AccountsPool

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


def json_params(params: dict):
    return {k: json.dumps(v, separators=(",", ":")) for k, v in params.items()}


def get_ql_entries(obj: dict) -> list[dict]:
    try:
        key = list(obj["data"].keys())[0]
        return obj["data"][key]["timeline"]["instructions"][0]["entries"]
    except Exception:
        return []


def get_ql_cursor(obj: dict) -> str | None:
    for entry in get_ql_entries(obj):
        if entry["entryId"].startswith("cursor-bottom-"):
            return entry["content"]["value"]
    return None


def rep_info(rep: Response) -> str:
    return f"[{rep.status_code} ~ {rep.headers['x-rate-limit-remaining']}/{rep.headers['x-rate-limit-limit']}]"


class Search:
    def __init__(self, pool: AccountsPool):
        self.pool = pool

    def get_next_cursor(self, res: dict) -> str | None:
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

    async def get_items(self, client: AsyncClient, q: str, cursor: str | None):
        while True:
            params = {**SEARCH_PARAMS, "q": q, "count": 20}
            params["cursor" if cursor else "requestContext"] = cursor if cursor else "launch"

            rep = await client.get(SEARCH_URL, params=params)
            rep.raise_for_status()

            data = rep.json()
            cursor = self.get_next_cursor(data)
            tweets = data.get("globalObjects", {}).get("tweets", [])
            if not tweets or not cursor:
                is_result = len(tweets) > 0
                is_cursor = cursor is not None
                logger.debug(f"{q} - no more items [res={is_result} cur={is_cursor}]")
                return

            yield rep, data, cursor

    async def search(self, q: str):
        total_count = 0
        async for x in self.pool.execute("search", lambda c, cur: self.get_items(c, q, cur)):
            rep, data, cursor = x

            tweets = data.get("globalObjects", {}).get("tweets", [])
            total_count += len(tweets)
            logger.debug(f"{q} - {total_count:,d} (+{len(tweets):,d}) {rep_info(rep)}")

            yield rep

    async def graphql_items(self, op: str, variables: dict, features: dict = {}, limit=-1):
        url = f"https://twitter.com/i/api/graphql/{op}"
        features = {**BASE_FEATURES, **features}

        cursor, all_count, queue = None, 0, op.split("/")[-1]
        while True:
            account = await self.pool.get_account_or_wait(queue)
            client = account.make_client()

            try:
                params = {"variables": {**variables, "cursor": cursor}, "features": features}
                rep = await client.get(url, params=json_params(params))
                logger.debug(f"{url} {rep_info(rep)}")
                rep.raise_for_status()

                data = rep.json()
                entries, cursor = get_ql_entries(data), get_ql_cursor(data)

                # cursor-top / cursor-bottom always present
                now_count = len([x for x in entries if not x["entryId"].startswith("cursor-")])
                all_count += now_count

                yield rep

                if not cursor or not now_count or (limit > 0 and all_count >= limit):
                    return
            finally:
                account.unlock(queue)

    async def graphql_item(self, op: str, variables: dict, features: dict = {}):
        res: list[Response] = []
        async for x in self.graphql_items(op, variables, features):
            res.append(x)
            break
        return res[0]

    async def user_by_login(self, login: str):
        v = {"screen_name": login, "withSafetyModeUserFields": True}
        return await self.graphql_item("sLVLhk0bGj3MVFEKTdax1w/UserByScreenName", v)

    async def user_by_id(self, uid: int):
        v = {"userId": str(uid), "withSafetyModeUserFields": True}
        return await self.graphql_item("GazOglcBvgLigl3ywt6b3Q/UserByRestId", v)

    async def retweeters(self, twid: int, limit=-1):
        v = {"tweetId": str(twid), "count": 20, "includePromotedContent": True}
        async for x in self.graphql_items("U5f_jm0CiLmSfI1d4rGleQ/Retweeters", v, limit=limit):
            yield x

    async def favoriters(self, twid: int, limit=-1):
        v = {"tweetId": str(twid), "count": 20, "includePromotedContent": True}
        async for x in self.graphql_items("vcTrPlh9ovFDQejz22q9vg/Favoriters", v, limit=limit):
            yield x
