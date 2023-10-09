import json
import os
from datetime import datetime
from typing import Any

import httpx

from .accounts_pool import Account, AccountsPool
from .logger import logger
from .utils import utc_ts

ReqParams = dict[str, str | int] | None
TMP_TS = datetime.utcnow().isoformat().split(".")[0].replace("T", "_").replace(":", "-")[0:16]


class Ctx:
    def __init__(self, acc: Account, clt: httpx.AsyncClient):
        self.acc = acc
        self.clt = clt
        self.req_count = 0


class ApiError(Exception):
    def __init__(self, rep: httpx.Response, res: dict):
        self.rep = rep
        self.res = res
        self.errors = [x["message"] for x in res["errors"]]
        self.acc = getattr(rep, "__username", "<UNKNOWN>")

    def __str__(self):
        msg = f"(code {self.rep.status_code}): {' ~ '.join(self.errors)}"
        return f"ApiError on {req_id(self.rep)} {msg}"


class RateLimitError(Exception):
    pass


class BannedError(Exception):
    pass

class DependencyError(Exception):
    pass


def req_id(rep: httpx.Response):
    lr = str(rep.headers.get("x-rate-limit-remaining", -1))
    ll = str(rep.headers.get("x-rate-limit-limit", -1))
    sz = max(len(lr), len(ll))
    lr, ll = lr.rjust(sz), ll.rjust(sz)

    username = getattr(rep, "__username", "<UNKNOWN>")
    return f"{lr}/{ll} - {username}"


def dump_rep(rep: httpx.Response):
    count = getattr(dump_rep, "__count", -1) + 1
    setattr(dump_rep, "__count", count)

    acc = getattr(rep, "__username", "<unknown>")
    outfile = f"{count:05d}_{rep.status_code}_{acc}.txt"
    outfile = f"/tmp/twscrape-{TMP_TS}/{outfile}"
    os.makedirs(os.path.dirname(outfile), exist_ok=True)

    msg = []
    msg.append(f"{count:,d} - {req_id(rep)}")
    msg.append(f"{rep.status_code} {rep.request.method} {rep.request.url}")
    msg.append("\n")
    # msg.append("\n".join([str(x) for x in list(rep.request.headers.items())]))
    msg.append("\n".join([str(x) for x in list(rep.headers.items())]))
    msg.append("\n")

    try:
        msg.append(json.dumps(rep.json(), indent=2))
    except json.JSONDecodeError:
        msg.append(rep.text)

    txt = "\n".join(msg)
    with open(outfile, "w") as f:
        f.write(txt)


class QueueClient:
    def __init__(self, pool: AccountsPool, queue: str, debug=False):
        self.pool = pool
        self.queue = queue
        self.debug = debug
        self.ctx: Ctx | None = None

    async def __aenter__(self):
        await self._get_ctx()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._close_ctx()

    async def _close_ctx(self, reset_at=-1, banned=False, msg=""):
        if self.ctx is None:
            return

        ctx, self.ctx, self.req_count = self.ctx, None, 0
        username = ctx.acc.username
        await ctx.clt.aclose()

        if banned:
            await self.pool.mark_banned(username, msg)
            return

        if reset_at > 0:
            await self.pool.lock_until(ctx.acc.username, self.queue, reset_at, ctx.req_count)
            return

        await self.pool.unlock(ctx.acc.username, self.queue, ctx.req_count)

    async def _get_ctx(self) -> Ctx:
        if self.ctx:
            return self.ctx

        acc = await self.pool.get_for_queue_or_wait(self.queue)
        clt = acc.make_client()
        self.ctx = Ctx(acc, clt)
        return self.ctx

    async def _check_rep(self, rep: httpx.Response):
        if self.debug:
            dump_rep(rep)

        try:
            res = rep.json()
        except json.JSONDecodeError:
            res: Any = {"_raw": rep.text}

        msg = "OK"
        if "errors" in res:
            msg = set([f'({x.get("code", -1)}) {x["message"]}' for x in res["errors"]])
            msg = "; ".join(list(msg))

        if self.debug:
            fn = logger.debug if rep.status_code == 200 else logger.warning
            fn(f"{rep.status_code:3d} - {req_id(rep)} - {msg}")

        # need to add some features in api.py
        if msg.startswith("The following features cannot be null"):
            logger.error(f"Invalid request: {msg}")
            exit(1)

        # general api rate limit
        if int(rep.headers.get("x-rate-limit-remaining", -1)) == 0:
            await self._close_ctx(int(rep.headers.get("x-rate-limit-reset", -1)))
            raise RateLimitError(msg)

        # possible new limits for tweets view per account
        if msg.startswith("(88) Rate limit exceeded") or rep.status_code == 429:
            await self._close_ctx(utc_ts() + 60 * 60 * 4)  # lock for 4 hours
            raise RateLimitError(msg)

        if msg.startswith("(326) Authorization: Denied by access control"):
            await self._close_ctx(-1, banned=True, msg=msg)
            raise BannedError(msg)

        if msg.startswith("(131) Dependency: Internal error."):
            raise DependencyError(msg)

        # possible banned by old api flow
        if rep.status_code in (401, 403):
            await self._close_ctx(utc_ts() + 60 * 60 * 12)  # lock for 12 hours
            raise RateLimitError(msg)

        # content not found
        if rep.status_code == 200 and "_Missing: No status found with that ID." in msg:
            return  # ignore this error

        # todo: (32) Could not authenticate you

        if msg != "OK":
            raise ApiError(rep, res)

        rep.raise_for_status()

    async def get(self, url: str, params: ReqParams = None):
        return await self.req("GET", url, params=params)

    async def req(self, method: str, url: str, params: ReqParams = None):
        retry_count = 0
        while True:
            ctx = await self._get_ctx()

            try:
                rep = await ctx.clt.request(method, url, params=params)
                setattr(rep, "__username", ctx.acc.username)
                await self._check_rep(rep)

                ctx.req_count += 1  # count only successful
                retry_count = 0
                return rep
            except (RateLimitError, BannedError):
                # already handled
                continue
            except (DependencyError):
                logger.error(f"Dependency error, returnning: {url}")
                return
            except (httpx.ReadTimeout, httpx.ProxyError):
                # http transport failed, just retry
                continue
            except Exception as e:
                retry_count += 1
                if retry_count >= 3:
                    logger.warning(f"Unknown error {type(e)}: {e}")
                    await self._close_ctx(utc_ts() + 60 * 15)  # 15 minutes
