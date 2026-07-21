from contextlib import aclosing
from typing import Literal

from .accounts_pool import AccountsPool
from .http import Response
from .logger import logger, set_log_level
from .models import (
    AccountAbout,
    Community,
    Tweet,
    User,
    parse_about,
    parse_community,
    parse_trends,
    parse_tweet,
    parse_tweets,
    parse_user,
    parse_users,
)
from .queue_client import QueueClient
from .utils import encode_params, find_obj, get_by_path

# GraphQL operation IDs used by this module.
# If you add a new endpoint, add it here manually.
# Update this block with: `uv run scripts/update_gql_ops.py`
# This script rewrites the whole block automatically.

# GQL_OPS_CODEGEN
OP_AboutAccountQuery = "TzOG2twZEfhr9KmClvVVqA/AboutAccountQuery"
OP_BlueVerifiedFollowers = "zhpogrf30JrKmTss81AY8w/BlueVerifiedFollowers"
OP_Bookmarks = "tUVliYsHyxrQIT4HXUWNdA/Bookmarks"
OP_CommunityQuery = "-ElI1vg3dYbttVMhBhGdLw/CommunityQuery"
OP_CommunityTweetsTimeline = "cW_FuuYQWRl5R6U5UhS7yA/CommunityTweetsTimeline"
OP_Followers = "4yeuNabfz3qFlfncCAy8Yw/Followers"
OP_Following = "eNoXdfXv5rU75RBzlmfuPA/Following"
OP_GenericTimelineById = "VrAHfTlEBd6qq1IJlOvBqQ/GenericTimelineById"
OP_ListLatestTweetsTimeline = "Iql5aRVyFxNZ-ORcDV_TwQ/ListLatestTweetsTimeline"
OP_ListMembers = "kcsJubZ1BIwpdKrYfiNRtg/ListMembers"
OP_Retweeters = "gClaCb5tCk0z2iwAis8CwA/Retweeters"
OP_SearchTimeline = "Bcw3RzK-PatNAmbnw54hFw/SearchTimeline"
OP_TweetDetail = "jd3V43oDY9cY7obs1YMfbQ/TweetDetail"
OP_UserByRestId = "DaeC_2LfMgwCujE03HSZtw/UserByRestId"
OP_UserByScreenName = "2qvSHpkWTMS9i0zJAwDNiA/UserByScreenName"
OP_UserCreatorSubscriptions = "jAbD4h4pLuogg19mnAeZ4w/UserCreatorSubscriptions"
OP_UserMedia = "DpzwOu8Idtlbfqh-Hf718Q/UserMedia"
OP_UserTweets = "hr4gzZONlq23okjU8fIe_A/UserTweets"
OP_UserTweetsAndReplies = "FIFgycIi-CNJcV0R-135Uw/UserTweetsAndReplies"
OP_membersSliceTimeline_Query = "WSbJGJjZaVasSj9bnqSZSA/membersSliceTimeline_Query"
OP_moderatorsSliceTimeline_Query = "GBMT3GOWy5dYsYC4XJfvow/moderatorsSliceTimeline_Query"
# GQL_OPS_CODEGEN

GQL_URL = "https://x.com/i/api/graphql"
GQL_FEATURES = {  # search values here (view source) https://x.com/
    "articles_preview_enabled": False,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "communities_web_enable_tweet_community_results_fetch": True,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_grok_community_note_auto_translation_is_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_grok_imagine_annotation_enabled": False,
    "responsive_web_media_download_video_enabled": False,
    "responsive_web_profile_redirect_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_awards_web_tipping_enabled": False,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "tweet_with_visibility_results_prefer_gql_media_interstitial_enabled": False,
    "tweetypie_unmention_optimization_enabled": True,
    "verified_phone_label_enabled": False,
    "view_counts_everywhere_api_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "premium_content_api_read_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": False,
    "responsive_web_grok_share_attachment_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": False,
    "responsive_web_grok_image_annotation_enabled": False,
    "responsive_web_grok_analysis_button_from_backend": False,
    "responsive_web_jetfuel_frame": False,
    "rweb_video_screen_enabled": True,
    "responsive_web_grok_show_grok_translated_post": True,
}

KV = dict | None
TrendId = Literal["trending", "news", "sport", "entertainment"] | str


class API:
    # Note: kv is variables, ft is features from original GQL request
    pool: AccountsPool

    def __init__(
        self,
        pool: AccountsPool | str | None = None,
        debug=False,
        proxy: str | None = None,
        raise_when_no_account=False,
        wait_timeout: float | None = None,
        wait_interval: float = 5.0,
    ):
        if isinstance(pool, AccountsPool):
            self.pool = pool
        elif isinstance(pool, str):
            self.pool = AccountsPool(
                db_file=pool,
                raise_when_no_account=raise_when_no_account,
                wait_timeout=wait_timeout,
                wait_interval=wait_interval,
            )
        else:
            self.pool = AccountsPool(
                raise_when_no_account=raise_when_no_account,
                wait_timeout=wait_timeout,
                wait_interval=wait_interval,
            )

        self.proxy = proxy
        self.debug = debug
        if self.debug:
            set_log_level("DEBUG")

    # general helpers

    def _is_end(self, rep: Response, q: str, res: list, cur: str | None, cnt: int, lim: int):
        new_count = len(res)
        new_total = cnt + new_count

        is_res = new_count > 0
        is_cur = cur is not None
        is_lim = lim > 0 and new_total >= lim

        return rep if is_res else None, new_total, is_cur and not is_lim

    def _get_cursor(self, obj: dict, cursor_type="Bottom") -> str | None:
        # standard timeline cursor: {cursorType: "Bottom", value: "..."}
        # fallback: community endpoints use slice_info.next_cursor (plain string)
        if cur := find_obj(obj, lambda x: x.get("cursorType") == cursor_type):
            return cur.get("value")
        return get_by_path(obj, "next_cursor")

    def _gql_entries(self, obj: dict) -> list:
        # standard timelines put items in "entries"; community endpoints use "items_results"
        els = get_by_path(obj, "entries") or get_by_path(obj, "items_results") or []
        if els and "entryId" in (els[0] or {}):
            # filter out pagination cursors and non-content module entries
            els = [
                x
                for x in els
                if not x["entryId"].startswith(
                    ("cursor-", "messageprompt-", "module-", "who-to-follow-")
                )
            ]
        return els

    # gql helpers

    async def _gql_items(
        self, op: str, kv: dict, ft: dict | None = None, limit=-1, cursor_type="Bottom"
    ):
        queue, cur, cnt, active = op.split("/")[-1], None, 0, True
        kv, ft = {**kv}, {**GQL_FEATURES, **(ft or {})}
        empty_pages = 0

        async with QueueClient(self.pool, queue, self.debug, proxy=self.proxy) as client:
            while active:
                params = {"variables": kv, "features": ft}
                if cur is not None:
                    params["variables"]["cursor"] = cur
                if queue in ("SearchTimeline", "ListLatestTweetsTimeline"):
                    params["fieldToggles"] = {"withArticleRichContentState": False}
                if queue in ("UserMedia",):
                    params["fieldToggles"] = {"withArticlePlainText": False}

                rep = await client.get(f"{GQL_URL}/{op}", params=encode_params(params))
                if rep is None:
                    return

                obj = rep.json()
                els = self._gql_entries(obj)
                cur = self._get_cursor(obj, cursor_type)

                rep, cnt, active = self._is_end(rep, queue, els, cur, cnt, limit)
                if rep is None:
                    # cursor exists → data may follow after empty/filtered pages (e.g. promo)
                    if cur is not None:
                        empty_pages += 1
                        if empty_pages >= 3:
                            logger.debug(f"{queue} – {empty_pages} empty pages in a row, stopping")
                            return
                        continue
                    return

                empty_pages = 0
                yield rep

    async def _gql_item(self, op: str, kv: dict, ft: dict | None = None):
        ft = ft or {}
        queue = op.split("/")[-1]
        async with QueueClient(self.pool, queue, self.debug, proxy=self.proxy) as client:
            params = {"variables": {**kv}, "features": {**GQL_FEATURES, **ft}}
            return await client.get(f"{GQL_URL}/{op}", params=encode_params(params))

    # search

    async def search_raw(self, q: str, limit=-1, kv: KV = None):
        op = OP_SearchTimeline
        kv = {
            "rawQuery": q,
            "count": 20,
            "product": "Latest",
            "querySource": "typed_query",
            **(kv or {}),
        }
        async with aclosing(self._gql_items(op, kv, limit=limit)) as gen:
            async for x in gen:
                yield x

    async def search(self, q: str, limit=-1, kv: KV = None):
        async with aclosing(self.search_raw(q, limit=limit, kv=kv)) as gen:
            async for rep in gen:
                for x in parse_tweets(rep.json(), limit):
                    yield x

    async def search_user(self, q: str, limit=-1, kv: KV = None):
        kv = {"product": "People", **(kv or {})}
        async with aclosing(self.search_raw(q, limit=limit, kv=kv)) as gen:
            async for rep in gen:
                for x in parse_users(rep.json(), limit):
                    yield x

    # user_by_login

    async def user_by_login_raw(self, login: str, kv: KV = None):
        op = OP_UserByScreenName
        kv = {"screen_name": login, "withSafetyModeUserFields": True, **(kv or {})}
        ft = {
            "highlights_tweets_tab_ui_enabled": True,
            "hidden_profile_likes_enabled": True,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "hidden_profile_subscriptions_enabled": True,
            "subscriptions_verification_info_verified_since_enabled": True,
            "subscriptions_verification_info_is_identity_verified_enabled": False,
            "responsive_web_twitter_article_notes_tab_enabled": False,
            "subscriptions_feature_can_gift_premium": False,
            "profile_label_improvements_pcf_label_in_post_enabled": False,
        }
        return await self._gql_item(op, kv, ft)

    async def user_by_login(self, login: str, kv: KV = None) -> User | None:
        rep = await self.user_by_login_raw(login, kv=kv)
        return parse_user(rep) if rep else None

    async def user_about_raw(self, username: str, kv: KV = None):
        op = OP_AboutAccountQuery
        kv = {"screenName": username, **(kv or {})}
        ft = {"responsive_web_graphql_timeline_navigation_enabled": True}
        return await self._gql_item(op, kv, ft)

    async def user_about(self, username: str, kv: KV = None) -> AccountAbout | None:
        rep = await self.user_about_raw(username, kv=kv)
        return parse_about(rep) if rep else None

    # tweet_details

    async def tweet_details_raw(self, twid: int, kv: KV = None):
        op = OP_TweetDetail
        kv = {
            "focalTweetId": str(twid),
            "with_rux_injections": True,
            "includePromotedContent": True,
            "withCommunity": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withBirdwatchNotes": True,
            "withVoice": True,
            "withV2Timeline": True,
            **(kv or {}),
        }
        return await self._gql_item(op, kv)

    async def tweet_details(self, twid: int, kv: KV = None) -> Tweet | None:
        rep = await self.tweet_details_raw(twid, kv=kv)
        return parse_tweet(rep, twid) if rep else None

    # tweet_replies
    # note: uses same op as tweet_details, see: https://github.com/vladkens/twscrape/issues/104

    async def tweet_replies_raw(self, twid: int, limit=-1, kv: KV = None):
        op = OP_TweetDetail
        kv = {
            "focalTweetId": str(twid),
            "referrer": "tweet",
            "with_rux_injections": True,
            "includePromotedContent": True,
            "withCommunity": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withBirdwatchNotes": True,
            "withVoice": True,
            "withV2Timeline": True,
            **(kv or {}),
        }
        async with aclosing(
            self._gql_items(op, kv, limit=limit, cursor_type="ShowMoreThreads")
        ) as gen:
            async for x in gen:
                yield x

    async def tweet_replies(self, twid: int, limit=-1, kv: KV = None):
        async with aclosing(self.tweet_replies_raw(twid, limit=limit, kv=kv)) as gen:
            async for rep in gen:
                for x in parse_tweets(rep.json(), limit):
                    if x.inReplyToTweetId == twid:
                        yield x

    # tweet_thread
    # Same TweetDetail family as tweet_replies, but configured to return the
    # full thread timeline and then filtered by conversationId instead of
    # only direct replies via inReplyToTweetId.

    async def tweet_thread_raw(self, twid: int, limit=-1, kv: KV = None):
        op = OP_TweetDetail
        kv = {
            "focalTweetId": str(twid),
            "referrer": "profile",
            "with_rux_injections": False,
            "includePromotedContent": True,
            "withCommunity": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withBirdwatchNotes": True,
            "withVoice": True,
            "withV2Timeline": True,
            **(kv or {}),
        }
        ft = {
            "rweb_video_screen_enabled": False,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "verified_phone_label_enabled": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "premium_content_api_read_enabled": False,
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
            "responsive_web_grok_analyze_post_followups_enabled": True,
            "responsive_web_jetfuel_frame": False,
            "responsive_web_grok_share_attachment_enabled": True,
            "articles_preview_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "responsive_web_grok_show_grok_translated_post": False,
            "responsive_web_grok_analysis_button_from_backend": True,
            "creator_subscriptions_quote_tweet_preview_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "responsive_web_grok_image_annotation_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
        }
        async with aclosing(self._gql_items(op, kv, ft=ft, limit=limit)) as gen:
            async for x in gen:
                yield x

    async def tweet_thread(self, twid: int, limit=-1, kv: KV = None):
        async with aclosing(self.tweet_thread_raw(twid, limit=limit, kv=kv)) as gen:
            async for rep in gen:
                for x in parse_tweets(rep.json(), limit):
                    if x.conversationId == twid:
                        yield x

    # followers

    async def followers_raw(self, uid: int, limit=-1, kv: KV = None):
        op = OP_Followers
        kv = {"userId": str(uid), "count": 20, "includePromotedContent": False, **(kv or {})}
        ft = {"responsive_web_twitter_article_notes_tab_enabled": False}
        async with aclosing(self._gql_items(op, kv, limit=limit, ft=ft)) as gen:
            async for x in gen:
                yield x

    async def followers(self, uid: int, limit=-1, kv: KV = None):
        async with aclosing(self.followers_raw(uid, limit=limit, kv=kv)) as gen:
            async for rep in gen:
                for x in parse_users(rep.json(), limit):
                    yield x

    # verified_followers

    async def verified_followers_raw(self, uid: int, limit=-1, kv: KV = None):
        op = OP_BlueVerifiedFollowers
        kv = {"userId": str(uid), "count": 20, "includePromotedContent": False, **(kv or {})}
        ft = {
            "responsive_web_twitter_article_notes_tab_enabled": True,
        }
        async with aclosing(self._gql_items(op, kv, limit=limit, ft=ft)) as gen:
            async for x in gen:
                yield x

    async def verified_followers(self, uid: int, limit=-1, kv: KV = None):
        async with aclosing(self.verified_followers_raw(uid, limit=limit, kv=kv)) as gen:
            async for rep in gen:
                for x in parse_users(rep.json(), limit):
                    yield x

    # following

    async def following_raw(self, uid: int, limit=-1, kv: KV = None):
        op = OP_Following
        kv = {"userId": str(uid), "count": 20, "includePromotedContent": False, **(kv or {})}
        async with aclosing(self._gql_items(op, kv, limit=limit)) as gen:
            async for x in gen:
                yield x

    async def following(self, uid: int, limit=-1, kv: KV = None):
        async with aclosing(self.following_raw(uid, limit=limit, kv=kv)) as gen:
            async for rep in gen:
                for x in parse_users(rep.json(), limit):
                    yield x

    # subscriptions

    async def subscriptions_raw(self, uid: int, limit=-1, kv: KV = None):
        op = OP_UserCreatorSubscriptions
        kv = {"userId": str(uid), "count": 20, "includePromotedContent": False, **(kv or {})}
        async with aclosing(self._gql_items(op, kv, limit=limit)) as gen:
            async for x in gen:
                yield x

    async def subscriptions(self, uid: int, limit=-1, kv: KV = None):
        async with aclosing(self.subscriptions_raw(uid, limit=limit, kv=kv)) as gen:
            async for rep in gen:
                for x in parse_users(rep.json(), limit):
                    yield x

    # retweeters

    async def retweeters_raw(self, twid: int, limit=-1, kv: KV = None):
        op = OP_Retweeters
        kv = {"tweetId": str(twid), "count": 20, "includePromotedContent": True, **(kv or {})}
        async with aclosing(self._gql_items(op, kv, limit=limit)) as gen:
            async for x in gen:
                yield x

    async def retweeters(self, twid: int, limit=-1, kv: KV = None):
        async with aclosing(self.retweeters_raw(twid, limit=limit, kv=kv)) as gen:
            async for rep in gen:
                for x in parse_users(rep.json(), limit):
                    yield x

    # user_tweets

    async def user_tweets_raw(self, uid: int, limit=-1, kv: KV = None):
        op = OP_UserTweets
        kv = {
            "userId": str(uid),
            "count": 40,
            "includePromotedContent": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice": True,
            "withV2Timeline": True,
            **(kv or {}),
        }
        async with aclosing(self._gql_items(op, kv, limit=limit)) as gen:
            async for x in gen:
                yield x

    async def user_tweets(self, uid: int, limit=-1, kv: KV = None):
        async with aclosing(self.user_tweets_raw(uid, limit=limit, kv=kv)) as gen:
            async for rep in gen:
                for x in parse_tweets(rep.json(), limit):
                    yield x

    # user_tweets_and_replies

    async def user_tweets_and_replies_raw(self, uid: int, limit=-1, kv: KV = None):
        op = OP_UserTweetsAndReplies
        kv = {
            "userId": str(uid),
            "count": 40,
            "includePromotedContent": True,
            "withCommunity": True,
            "withVoice": True,
            "withV2Timeline": True,
            **(kv or {}),
        }
        async with aclosing(self._gql_items(op, kv, limit=limit)) as gen:
            async for x in gen:
                yield x

    async def user_tweets_and_replies(self, uid: int, limit=-1, kv: KV = None):
        async with aclosing(self.user_tweets_and_replies_raw(uid, limit=limit, kv=kv)) as gen:
            async for rep in gen:
                for x in parse_tweets(rep.json(), limit):
                    yield x

    # user_media

    async def user_media_raw(self, uid: int, limit=-1, kv: KV = None):
        op = OP_UserMedia
        kv = {
            "userId": str(uid),
            "count": 40,
            "includePromotedContent": False,
            "withClientEventToken": False,
            "withBirdwatchNotes": False,
            "withVoice": True,
            "withV2Timeline": True,
            **(kv or {}),
        }

        async with aclosing(self._gql_items(op, kv, limit=limit)) as gen:
            async for x in gen:
                yield x

    async def user_media(self, uid: int, limit=-1, kv: KV = None):
        async with aclosing(self.user_media_raw(uid, limit=limit, kv=kv)) as gen:
            async for rep in gen:
                for x in parse_tweets(rep, limit):
                    # sometimes some tweets without media, so skip them
                    media_count = (
                        len(x.media.photos) + len(x.media.videos) + len(x.media.animated)
                        if x.media
                        else 0
                    )

                    if media_count > 0:
                        yield x

    # list_timeline

    async def list_timeline_raw(self, list_id: int, limit=-1, kv: KV = None):
        op = OP_ListLatestTweetsTimeline
        kv = {"listId": str(list_id), "count": 20, **(kv or {})}
        async with aclosing(self._gql_items(op, kv, limit=limit)) as gen:
            async for x in gen:
                yield x

    async def list_timeline(self, list_id: int, limit=-1, kv: KV = None):
        async with aclosing(self.list_timeline_raw(list_id, limit=limit, kv=kv)) as gen:
            async for rep in gen:
                for x in parse_tweets(rep, limit):
                    yield x

    # trends

    async def trends_raw(self, trend_id: TrendId, limit=-1, kv: KV = None):
        map = {
            "trending": "VGltZWxpbmU6DAC2CwABAAAACHRyZW5kaW5nAAA",
            "news": "VGltZWxpbmU6DAC2CwABAAAABG5ld3MAAA",
            "sport": "VGltZWxpbmU6DAC2CwABAAAABnNwb3J0cwAA",
            "entertainment": "VGltZWxpbmU6DAC2CwABAAAADWVudGVydGFpbm1lbnQAAA",
        }
        trend_id = map.get(trend_id, trend_id)

        op = OP_GenericTimelineById
        kv = {
            "timelineId": trend_id,
            "count": 20,
            "withQuickPromoteEligibilityTweetFields": True,
            **(kv or {}),
        }
        async with aclosing(self._gql_items(op, kv, limit=limit)) as gen:
            async for x in gen:
                yield x

    async def trends(self, trend_id: TrendId, limit=-1, kv: KV = None):
        async with aclosing(self.trends_raw(trend_id, limit=limit, kv=kv)) as gen:
            async for rep in gen:
                for x in parse_trends(rep, limit):
                    yield x

    async def search_trend(self, q: str, limit=-1, kv: KV = None):
        kv = {
            "querySource": "trend_click",
            **(kv or {}),
        }
        async with aclosing(self.search_raw(q, limit=limit, kv=kv)) as gen:
            async for rep in gen:
                for x in parse_tweets(rep.json(), limit):
                    yield x

    # Get current user bookmarks

    async def bookmarks_raw(self, limit=-1, kv: KV = None):
        op = OP_Bookmarks
        kv = {
            "count": 20,
            "includePromotedContent": False,
            "withClientEventToken": False,
            "withBirdwatchNotes": False,
            "withVoice": True,
            "withV2Timeline": True,
            **(kv or {}),
        }
        ft = {
            "graphql_timeline_v2_bookmark_timeline": True,
        }
        async with aclosing(self._gql_items(op, kv, ft, limit=limit)) as gen:
            async for x in gen:
                yield x

    async def bookmarks(self, limit=-1, kv: KV = None):
        async with aclosing(self.bookmarks_raw(limit=limit, kv=kv)) as gen:
            async for rep in gen:
                for x in parse_tweets(rep.json(), limit):
                    yield x

    # list members of a List

    async def list_members_raw(self, list_id: int, limit: int = -1, kv: KV = None):
        op = OP_ListMembers
        kv = {"listId": str(list_id), "count": 20, **(kv or {})}
        async with aclosing(self._gql_items(op, kv, limit=limit)) as gen:
            async for page in gen:
                yield page

    async def list_members(self, list_id: int, limit: int = -1, kv: KV = None):
        async with aclosing(self.list_members_raw(list_id, limit=limit, kv=kv)) as gen:
            async for page in gen:
                for user in parse_users(page.json(), limit):
                    yield user

    # Community members

    async def community_members_raw(self, community_id: int, limit=-1, kv: KV = None):
        op = OP_membersSliceTimeline_Query
        kv = {
            "communityId": str(community_id),
            "count": 20,
            "includePromotedContent": False,
            **(kv or {}),
        }
        async with aclosing(self._gql_items(op, kv, limit=limit)) as gen:
            async for x in gen:
                yield x

    async def community_members(self, community_id: int, limit=-1, kv: KV = None):
        async with aclosing(self.community_members_raw(community_id, limit=limit, kv=kv)) as gen:
            async for rep in gen:
                for x in parse_users(rep, limit):
                    yield x

    # Community moderators

    async def community_moderators_raw(self, community_id: int, limit=-1, kv: KV = None):
        op = OP_moderatorsSliceTimeline_Query
        kv = {
            "communityId": str(community_id),
            "count": 20,
            "includePromotedContent": False,
            **(kv or {}),
        }
        async with aclosing(self._gql_items(op, kv, limit=limit)) as gen:
            async for x in gen:
                yield x

    async def community_moderators(self, community_id: int, limit=-1, kv: KV = None):
        async with aclosing(
            self.community_moderators_raw(community_id, limit=limit, kv=kv)
        ) as gen:
            async for rep in gen:
                for x in parse_users(rep, limit):
                    yield x

    # Community tweets timeline

    async def community_tweets_raw(self, community_id: int, limit=-1, kv: KV = None):
        op = OP_CommunityTweetsTimeline
        kv = {
            "communityId": str(community_id),
            "count": 40,
            "displayLocation": "Community",
            "rankingMode": "Relevance",
            "withCommunity": True,
            "includePromotedContent": False,
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice": True,
            "withV2Timeline": True,
            **(kv or {}),
        }
        async with aclosing(self._gql_items(op, kv, limit=limit)) as gen:
            async for x in gen:
                yield x

    async def community_tweets(self, community_id: int, limit=-1, kv: KV = None):
        async with aclosing(self.community_tweets_raw(community_id, limit=limit, kv=kv)) as gen:
            async for rep in gen:
                for x in parse_tweets(rep, limit):
                    yield x

    async def community_info_raw(self, community_id: int, kv: KV = None):
        op = OP_CommunityQuery
        kv = {"communityId": str(community_id), **(kv or {})}
        ft = {
            "c9s_list_members_action_api_enabled": False,
            "c9s_superc9s_indication_enabled": False,
        }
        return await self._gql_item(op, kv, ft)

    async def community_info(self, community_id: int, kv: KV = None) -> Community | None:
        rep = await self.community_info_raw(community_id, kv=kv)
        return parse_community(rep) if rep else None
