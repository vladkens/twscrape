import json
import os
from typing import Any

import httpx

from .accounts_pool import Account, AccountsPool
from .logger import logger
from .utils import utc

ReqParams = dict[str, str | int] | None
TMP_TS = utc.now().isoformat().split(".")[0].replace("T", "_").replace(":", "-")[0:16]


class Ctx:
    def __init__(self, acc: Account, clt: httpx.AsyncClient):
        self.acc = acc
        self.clt = clt
        self.req_count = 0


class RateLimitError(Exception):
    pass


class BannedError(Exception):
    pass


class AbortReqError(Exception):
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

    async def _check_rep(self, rep: httpx.Response) -> None:
        """
        This function can raise Exception and request will be retried or aborted
        Or if None is returned, response will passed to api parser as is
        """

        if self.debug:
            dump_rep(rep)

        try:
            res = rep.json()
        except json.JSONDecodeError:
            res: Any = {"_raw": rep.text}

        err_msg = "OK"
        if "errors" in res:
            err_msg = set([f'({x.get("code", -1)}) {x["message"]}' for x in res["errors"]])
            err_msg = "; ".join(list(err_msg))

        if self.debug:
            fn = logger.debug if rep.status_code == 200 else logger.warning
            fn(f"{rep.status_code:3d} - {req_id(rep)} - {err_msg}")

        # need to add some features in api.py
        if err_msg.startswith("The following features cannot be null"):
            logger.error(f"Invalid request: {err_msg}")
            exit(1)

        # general api rate limit
        if int(rep.headers.get("x-rate-limit-remaining", -1)) == 0:
            await self._close_ctx(int(rep.headers.get("x-rate-limit-reset", -1)))
            raise RateLimitError(err_msg)

        # possible new limits for tweets view per account
        if err_msg.startswith("(88) Rate limit exceeded") or rep.status_code == 429:
            await self._close_ctx(utc.ts() + 60 * 60 * 4)  # lock for 4 hours
            raise RateLimitError(err_msg)

        if err_msg.startswith("(326) Authorization: Denied by access control"):
            await self._close_ctx(-1, banned=True, msg=err_msg)
            raise BannedError(err_msg)

        # Something from twitter side, abort request so it doesn't hang
        # https://github.com/vladkens/twscrape/pull/80
        if err_msg.startswith("(131) Dependency: Internal error."):
            logger.warning(f"Dependency error (request skipped): {err_msg}")
            raise AbortReqError()

        # possible banned by old api flow
        if rep.status_code in (401, 403):
            await self._close_ctx(utc.ts() + 60 * 60 * 12)  # lock for 12 hours
            raise RateLimitError(err_msg)

        # content not found
        if rep.status_code == 200 and "_Missing: No status found with that ID." in err_msg:
            return  # ignore this error

        # Something from twitter side, just ignore it
        # https://github.com/vladkens/twscrape/pull/95
        if rep.status_code == 200 and "Authorization" in err_msg:
            logger.warning(f"Unknown authorization error: {err_msg}")
            return

        if err_msg != "OK":
            logger.warning(f"Unknown API error: {err_msg}")
            return  # ignore any other unknown errors

        rep.raise_for_status()

    async def get(self, url: str, params: ReqParams = None):
        return await self.req("GET", url, params=params)

    async def req(self, method: str, url: str, params: ReqParams = None) -> httpx.Response | None:
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
            except AbortReqError:
                return
            except (httpx.ReadTimeout, httpx.ProxyError):
                # http transport failed, just retry
                continue
            except Exception as e:
                retry_count += 1
                if retry_count >= 3:
                    logger.warning(f"Unknown error {type(e)}: {e}")
                    await self._close_ctx(utc.ts() + 60 * 15)  # 15 minutes
