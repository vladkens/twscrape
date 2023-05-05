import json
import time
from datetime import datetime
from typing import Awaitable, Callable

from httpx import AsyncClient, HTTPStatusError, Response

from .accounts_pool import AccountsPool
from .constants import GQL_FEATURES, GQL_URL, SEARCH_PARAMS, SEARCH_URL
from .logger import logger
from .models import Tweet, User
from .utils import encode_params, find_obj, get_by_path, to_old_obj, to_search_like


class API:
    def __init__(self, pool: AccountsPool, debug=False):
        self.pool = pool
        self.debug = debug
        self._history: list[Response] = []

    # http helpers

    def _limit_msg(self, rep: Response):
        lr = rep.headers.get("x-rate-limit-remaining", -1)
        ll = rep.headers.get("x-rate-limit-limit", -1)

        username = getattr(rep, "__username", "<UNKNOWN>")
        return f"{username} {lr}/{ll}"

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

    def _push_history(self, rep: Response):
        self._history.append(rep)
        if len(self._history) > 3:
            self._history.pop(0)

    def _dump_history(self, extra: str = ""):
        if not self.debug:
            return

        ts = str(datetime.now()).replace(":", "-").replace(" ", "_")
        filename = f"/tmp/api_dump_{ts}.txt"
        with open(filename, "w") as fp:
            txt = f"{extra}\n"
            for rep in self._history:
                res = json.dumps(rep.json(), indent=2)
                hdr = "\n".join([str(x) for x in list(rep.request.headers.items())])
                div = "-" * 20

                msg = f"{div}\n{self._limit_msg(rep)}"
                msg = f"{msg}\n{rep.request.method} {rep.request.url}"
                msg = f"{msg}\n{rep.status_code}\n{div}"
                msg = f"{msg}\n{hdr}\n{div}\n{res}\n\n"
                txt += msg

            fp.write(txt)

        print(f"API dump ({len(self._history)}) dumped to {filename}")

    async def _inf_req(self, queue: str, cb: Callable[[AsyncClient], Awaitable[Response]]):
        while True:
            acc = await self.pool.get_for_queue_or_wait(queue)
            client = acc.make_client()

            try:
                while True:
                    rep = await cb(client)
                    setattr(rep, "__username", acc.username)
                    self._push_history(rep)
                    rep.raise_for_status()

                    yield rep
            except HTTPStatusError as e:
                rep = e.response
                log_id = f"{self._limit_msg(rep)} on queue={queue}"

                # rate limit
                if rep.status_code == 429:
                    logger.debug(f"Rate limit for {log_id}")
                    reset_ts = int(rep.headers.get("x-rate-limit-reset", 0))
                    await self.pool.lock_until(acc.username, queue, reset_ts)
                    continue

                # possible account banned
                if rep.status_code == 403:
                    logger.debug(f"Ban for {log_id}")
                    reset_ts = int(time.time() + 60 * 60)  # 1 hour
                    await self.pool.lock_until(acc.username, queue, reset_ts)
                    continue

                # twitter can return different types of cursors that not transfers between accounts
                # just take the next account, the current cursor can work in it
                if rep.status_code == 400:
                    logger.debug(f"Cursor not valid for {log_id}")
                    continue

                logger.error(f"[{rep.status_code}] {e.request.url}\n{rep.text}")
                raise e
            finally:
                await self.pool.unlock(acc.username, queue)
                await client.aclose()

    def _get_cursor(self, obj: dict):
        if cur := find_obj(obj, lambda x: x.get("cursorType") == "Bottom"):
            return cur.get("value")
        return None

    def _get_ql_entries(self, obj: dict) -> list[dict]:
        entries = get_by_path(obj, "entries")
        return entries or []

    async def _ql_items(self, op: str, kv: dict, limit=-1):
        queue, cursor, count = op.split("/")[-1], None, 0

        async def _get(client: AsyncClient):
            params = {"variables": {**kv, "cursor": cursor}, "features": GQL_FEATURES}
            return await client.get(f"{GQL_URL}/{op}", params=encode_params(params))

        async for rep in self._inf_req(queue, _get):
            obj = rep.json()

            # cursor-top / cursor-bottom always present
            entries = self._get_ql_entries(obj)
            entries = [x for x in entries if not x["entryId"].startswith("cursor-")]
            cursor = self._get_cursor(obj)

            check = self._is_end(rep, queue, entries, cursor, count, limit)
            count, end_before, end_after = check

            if end_before:
                return

            yield rep

            if end_after:
                return

    async def _ql_item(self, op: str, kv: dict, ft: dict = {}):
        async def _get(client: AsyncClient):
            params = {"variables": {**kv}, "features": {**GQL_FEATURES, **ft}}
            return await client.get(f"{GQL_URL}/{op}", params=encode_params(params))

        queue = op.split("/")[-1]
        async for rep in self._inf_req(queue, _get):
            return rep

        raise Exception("No response")  # todo

    # search

    async def search_raw(self, q: str, limit=-1):
        queue, cursor, count = "search", None, 0

        async def _get(client: AsyncClient):
            params = {**SEARCH_PARAMS, "q": q, "count": 20}
            params["cursor" if cursor else "requestContext"] = cursor if cursor else "launch"
            try:
                return await client.get(SEARCH_URL, params=params)
            except Exception as e:
                logger.error(f"Error requesting {q}: {e}")
                logger.error(f"Request: {SEARCH_URL}, {params}")
                raise e

        try:
            async for rep in self._inf_req(queue, _get):
                data = rep.json()

                tweets = data.get("globalObjects", {}).get("tweets", [])
                cursor = self._get_cursor(data)

                check = self._is_end(rep, q, tweets, cursor, count, limit)
                count, end_before, end_after = check

                if end_before:
                    return

                yield rep

                if end_after:
                    return
        except HTTPStatusError as e:
            self._dump_history(f"q={q}\ncount={count}\nwas_cur={cursor}\nnew_cur=None")
            raise e

    async def search(self, q: str, limit=-1):
        twids = set()
        async for rep in self.search_raw(q, limit=limit):
            res = rep.json()
            obj = res.get("globalObjects", {})
            for x in list(obj.get("tweets", {}).values()):
                if x["id_str"] not in twids:
                    twids.add(x["id_str"])
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
