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

SEARCH_URL = "https://api.twitter.com/2/search/adaptive.json"
SEARCH_PARAMS = dict(x.split("=") for x in BASIC_SEARCH_PARAMS.splitlines() if x)


def rep_info(rep: Response) -> str:
    return f"[{rep.headers['x-rate-limit-remaining']}/{rep.headers['x-rate-limit-limit']}]"


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

    async def get(self, client: AsyncClient, q: str, cursor: str | None):
        while True:
            params = {**SEARCH_PARAMS, "q": q, "count": 20}
            params["cursor" if cursor else "requestContext"] = cursor if cursor else "launch"

            rep = await client.get(SEARCH_URL, params=params)
            rep.raise_for_status()

            data = rep.json()
            cursor = self.get_next_cursor(data)
            tweets = data.get("globalObjects", {}).get("tweets", [])
            if not tweets or not cursor:
                is_tweets = len(tweets) > 0
                is_cursor = cursor is not None
                logger.debug(f"{q} - no more results [res: {is_tweets}, cur: {is_cursor}]")
                return

            yield rep, data, cursor

    async def query(self, q: str):
        total_count = 0
        async for x in self.pool.execute("search", lambda c, cur: self.get(c, q, cur)):
            rep, data, cursor = x

            tweets = data.get("globalObjects", {}).get("tweets", [])
            total_count += len(tweets)
            logger.debug(f"{q} - {total_count:,d} (+{len(tweets):,d}) {rep_info(rep)}")

            yield rep
