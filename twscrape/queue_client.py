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

    async def _close_ctx(self, reset_at=-1):
        if self.ctx is None:
            return

        ctx, self.ctx, self.req_count = self.ctx, None, 0
        await ctx.clt.aclose()

        if reset_at <= 0:
            await self.pool.unlock(ctx.acc.username, self.queue, ctx.req_count)
        else:
            await self.pool.lock_until(ctx.acc.username, self.queue, reset_at, ctx.req_count)

    async def _get_ctx(self) -> Ctx:
        if self.ctx:
            return self.ctx

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
        retry_count = 0
        while True:
            ctx = await self._get_ctx()

            try:
                rep = await ctx.clt.request(method, url, params=params)
                setattr(rep, "__username", ctx.acc.username)
                self._push_history(rep)
                rep.raise_for_status()
                ctx.req_count += 1  # count only successful
                retry_count = 0
                return rep
            except httpx.HTTPStatusError as e:
                rep = e.response
                log_id = f"{req_id(rep)} on queue={self.queue}"

                reset_ts, known_code = -1, True

                if rep.status_code == 429:
                    # rate limit
                    reset_ts = int(rep.headers.get("x-rate-limit-reset", 0))
                    logger.debug(f"Rate limit for {log_id}")

                elif rep.status_code == 400:
                    # api can return different types of cursors that not transfers between accounts
                    # just take the next account, the current cursor can work in it
                    logger.debug(f"Cursor not valid for {log_id}")

                elif rep.status_code in (401, 403):
                    # account is locked or banned
                    reset_ts = utc_ts() + 60 * 60  # + 1 hour
                    logger.warning(f"Code {rep.status_code} for {log_id} – frozen for 1h")

                else:
                    known_code = False
                    logger.debug(f"HTTP Error {rep.status_code} {e.request.url}\n{rep.text}")

                await self._close_ctx(reset_ts)
                if not known_code:
                    raise e
            except Exception as e:
                logger.warning(f"Unknown error, retrying. Err ({type(e)}): {str(e)}")
                retry_count += 1
                if retry_count > 3:
                    await self._close_ctx(utc_ts() + 60 * 15)  # 15 minutes

    async def get(self, url: str, params: ReqParams = None):
        try:
            return await self.req("GET", url, params=params)
        except httpx.HTTPStatusError as e:
            self._dump_history(f"GET {url} {json.dumps(params)}")
            raise e
