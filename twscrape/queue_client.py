import json
from datetime import datetime

import httpx

from .accounts_pool import Account, AccountsPool
from .logger import logger
from .utils import utc_ts

ReqParams = dict[str, str | int] | None


def req_id(rep: httpx.Response):
    lr = rep.headers.get("x-rate-limit-remaining", -1)
    ll = rep.headers.get("x-rate-limit-limit", -1)

    username = getattr(rep, "__username", "<UNKNOWN>")
    return f"{username} {lr}/{ll}"


class Ctx:
    def __init__(self, acc: Account, clt: httpx.AsyncClient):
        self.acc = acc
        self.clt = clt
        self.req_count = 0


class QueueClient:
    def __init__(self, pool: AccountsPool, queue: str, debug=False):
        self.pool = pool
        self.queue = queue
        self.debug = debug
        self.history: list[httpx.Response] = []
        self.ctx: Ctx | None = None

    async def __aenter__(self):
        await self._get_ctx()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._close_ctx()
        return self

    async def _close_ctx(self):
        if self.ctx is not None:
            await self.ctx.clt.aclose()
            await self.pool.unlock(self.ctx.acc.username, self.queue, self.ctx.req_count)

    async def _get_ctx(self, fresh=False) -> Ctx:
        if self.ctx and not fresh:
            return self.ctx

        if self.ctx is not None:
            await self._close_ctx()

        acc = await self.pool.get_for_queue_or_wait(self.queue)
        clt = acc.make_client()
        self.ctx = Ctx(acc, clt)
        return self.ctx

    def _push_history(self, rep: httpx.Response):
        self.history.append(rep)
        if len(self.history) > 3:
            self.history.pop(0)

    def _dump_history(self, extra: str = ""):
        if not self.debug:
            return

        ts = str(datetime.now()).replace(":", "-").replace(" ", "_")
        filename = f"/tmp/api_dump_{ts}.txt"
        with open(filename, "w", encoding="utf-8") as fp:
            txt = f"{extra}\n"
            for rep in self.history:
                res = json.dumps(rep.json(), indent=2)
                hdr = "\n".join([str(x) for x in list(rep.request.headers.items())])
                div = "-" * 20

                msg = f"{div}\n{req_id(rep)}"
                msg = f"{msg}\n{rep.request.method} {rep.request.url}"
                msg = f"{msg}\n{rep.status_code}\n{div}"
                msg = f"{msg}\n{hdr}\n{div}\n{res}\n\n"
                txt += msg

            fp.write(txt)

        print(f"API dump ({len(self.history)}) dumped to {filename}")

    async def req(self, method: str, url: str, params: ReqParams = None):
        fresh = False  # do not get new account on first try
        while True:
            ctx = await self._get_ctx(fresh=fresh)
            fresh = True

            try:
                rep = await ctx.clt.request(method, url, params=params)
                setattr(rep, "__username", ctx.acc.username)
                self._push_history(rep)
                rep.raise_for_status()
                ctx.req_count += 1  # count only successful
                return rep
            except httpx.HTTPStatusError as e:
                rep = e.response
                log_id = f"{req_id(rep)} on queue={self.queue}"

                # rate limit
                if rep.status_code == 429:
                    logger.debug(f"Rate limit for {log_id}")
                    reset_ts = int(rep.headers.get("x-rate-limit-reset", 0))
                    await self.pool.lock_until(ctx.acc.username, self.queue, reset_ts)
                    continue

                # possible account banned
                if rep.status_code == 403:
                    logger.warning(f"403 for {log_id}")
                    reset_ts = utc_ts() + 60 * 60  # + 1 hour
                    await self.pool.lock_until(ctx.acc.username, self.queue, reset_ts)
                    continue

                # twitter can return different types of cursors that not transfers between accounts
                # just take the next account, the current cursor can work in it
                if rep.status_code == 400:
                    logger.debug(f"Cursor not valid for {log_id}")
                    continue

                logger.error(f"[{rep.status_code}] {e.request.url}\n{rep.text}")
                raise e
            except Exception as e:
                logger.warning(f"Unknown error, retrying. Err: {e}")

    async def get(self, url: str, params: ReqParams = None):
        try:
            return await self.req("GET", url, params=params)
        except httpx.HTTPStatusError as e:
            self._dump_history(f"GET {url} {json.dumps(params)}")
            raise e
