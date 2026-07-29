import asyncio
import json
import os
from typing import Any
from urllib.parse import urlparse

from . import telemetry
from .account import Account, has_required_cookies
from .accounts_pool import AccountsPool
from .http import (
    ConnectError,
    HttpClient,
    HttpMethod,
    HttpStatusError,
    NetworkError,
    Response,
    format_error,
)
from .logger import logger
from .utils import utc
from .xclid import XClIdAccountError, XClIdGen, XClIdParseError

ReqParams = dict[str, str | int] | None
TMP_TS = utc.now().isoformat().split(".")[0].replace("T", "_").replace(":", "-")[0:16]


class HandledError(Exception): ...


class AbortReqError(Exception): ...


class XClIdGenStore:
    items: dict[str, XClIdGen] = {}

    @classmethod
    async def get(
        cls,
        username: str,
        proxy: str | None = None,
        cookies: dict[str, str] | None = None,
        fresh=False,
    ) -> XClIdGen:
        if username in cls.items and not fresh:
            return cls.items[username]

        clid_gen = await XClIdGen.create(proxy=proxy, cookies=cookies)
        cls.items[username] = clid_gen
        return clid_gen


class Ctx:
    def __init__(self, acc: Account, clt: HttpClient, proxy: str | None = None):
        self.req_count = 0
        self.acc = acc
        self.clt = clt
        self.proxy = proxy

    async def aclose(self):
        await self.clt.aclose()

    async def req(self, method: HttpMethod, url: str, params: ReqParams = None) -> Response:
        # if code 404 on first try then generate new x-client-transaction-id and retry
        # https://github.com/vladkens/twscrape/issues/248
        path = urlparse(url).path or "/"

        tries = 0
        while tries < 3:
            gen = await XClIdGenStore.get(
                self.acc.username,
                proxy=self.proxy,
                cookies=self.acc.cookies,
                fresh=tries > 0,
            )
            hdr = {"x-client-transaction-id": gen.calc(method, path)}
            rep = await self.clt.request(method, url, params=params, headers=hdr)
            if rep.status_code != 404:
                return rep

            tries += 1
            logger.debug(f"Retrying request with new x-client-transaction-id: {url}")
            await asyncio.sleep(1)

        raise AbortReqError(
            "Faield to get XClIdGen. See: https://github.com/vladkens/twscrape/issues/248"
        )


def req_id(rep: Response):
    lr = str(rep.headers.get("x-rate-limit-remaining", -1))
    ll = str(rep.headers.get("x-rate-limit-limit", -1))
    sz = max(len(lr), len(ll))
    lr, ll = lr.rjust(sz), ll.rjust(sz)

    username = getattr(rep, "__username", "<UNKNOWN>")
    return f"{lr}/{ll} - {username}"


def dump_rep(rep: Response):
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
    def __init__(self, pool: AccountsPool, queue: str, debug=False, proxy: str | None = None):
        self.pool = pool
        self.queue = queue
        self.debug = debug
        self.ctx: Ctx | None = None
        self.proxy = proxy

    async def __aenter__(self):
        await self._get_ctx()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._close_ctx()

    async def _close_ctx(self, reset_at=-1, inactive=False, msg: str | None = None):
        if self.ctx is None:
            return

        ctx, self.ctx, self.req_count = self.ctx, None, 0
        username = ctx.acc.username
        await ctx.aclose()

        if inactive:
            await self.pool.mark_inactive(username, msg)
            return

        if reset_at > 0:
            await self.pool.lock_until(ctx.acc.username, self.queue, reset_at, ctx.req_count)
            return

        await self.pool.unlock(ctx.acc.username, self.queue, ctx.req_count)

    async def _get_ctx(self):
        if self.ctx:
            return self.ctx

        acc = await self.pool.get_for_queue_or_wait(self.queue)
        if acc is None:
            return None

        clt = acc.make_client(proxy=self.proxy)
        self.ctx = Ctx(acc, clt, proxy=acc.resolve_proxy(self.proxy))
        return self.ctx

    def _format_ctx_error(self, ctx: Ctx, error: Exception | str) -> str:
        message = format_error(error) if isinstance(error, Exception) else error
        return (
            f"{message}; username={ctx.acc.username}; queue={self.queue}; "
            f"backend={getattr(ctx.clt, 'backend', 'unknown')}; proxy={bool(ctx.proxy)}"
        )

    async def _check_rep(self, rep: Response) -> None:
        """
        This function can raise Exception and request will be retried or aborted
        Or if None is returned, response will passed to api parser as is
        """

        if self.debug:
            dump_rep(rep)

        if "text/html" in rep.headers.get("content-type", "") and rep.status_code >= 400:
            src = "Cloudflare" if "cf-ray" in rep.headers else "HTML"
            logger.warning(f"Blocked by {src}: {rep.status_code} - {req_id(rep)}")
            raise AbortReqError()

        try:
            res = rep.json()
        except json.JSONDecodeError:
            res: Any = {"_raw": rep.text}

        limit_remaining = int(rep.headers.get("x-rate-limit-remaining", -1))
        limit_reset = int(rep.headers.get("x-rate-limit-reset", -1))
        # limit_max = int(rep.headers.get("x-rate-limit-limit", -1))

        err_msg = "OK"
        if "errors" in res:
            err_msg = {f"({x.get('code', -1)}) {x['message']}" for x in res["errors"]}
            err_msg = "; ".join(list(err_msg))

        log_msg = f"{rep.status_code:3d} - {req_id(rep)} - {err_msg}"
        logger.trace(log_msg)

        # for dev: need to add some features in api.py
        if err_msg.startswith("(336) The following features cannot be null"):
            logger.error(f"[DEV] Update required: {err_msg}")
            exit(1)

        # general api rate limit
        if limit_remaining == 0 and limit_reset > 0:
            logger.debug(f"Rate limited: {log_msg}")
            await self._close_ctx(limit_reset)
            raise HandledError()

        # no way to check is account banned in direct way, but this check should work
        if err_msg.startswith("(88) Rate limit exceeded") and limit_remaining > 0:
            logger.warning(f"Ban detected: {log_msg}")
            await self._close_ctx(-1, inactive=True, msg=err_msg)
            raise HandledError()

        if err_msg.startswith("(326) Authorization: Denied by access control"):
            logger.warning(f"Ban detected: {log_msg}")
            await self._close_ctx(-1, inactive=True, msg=err_msg)
            raise HandledError()

        if err_msg.startswith("(32) Could not authenticate you"):
            logger.warning(f"Session expired or banned: {log_msg}")
            await self._close_ctx(-1, inactive=True, msg=err_msg)
            raise HandledError()

        if err_msg == "OK" and rep.status_code == 403:
            logger.warning(f"Session expired or banned: {log_msg}")
            await self._close_ctx(-1, inactive=True, msg=None)
            raise HandledError()

        # something from twitter side - abort all queries, see: https://github.com/vladkens/twscrape/pull/80
        if err_msg.startswith("(131) Dependency: Internal error"):
            # looks like when data exists, we can ignore this error
            # https://github.com/vladkens/twscrape/issues/166
            if rep.status_code == 200 and "data" in res and "user" in res["data"]:
                err_msg = "OK"
            else:
                logger.warning(f"Dependency error (request skipped): {err_msg}")
                raise AbortReqError()

        # content not found
        if rep.status_code == 200 and "_Missing: No status found with that ID" in err_msg:
            return  # ignore this error

        # something from twitter side - just ignore it, see: https://github.com/vladkens/twscrape/pull/95
        if rep.status_code == 200 and "Authorization" in err_msg:
            logger.warning(f"Authorization unknown error: {log_msg}")
            return

        if err_msg != "OK":
            logger.warning(f"API unknown error: {log_msg}")
            return  # ignore any other unknown errors

        try:
            rep.raise_for_status()
        except HttpStatusError:
            logger.error(f"Unhandled API response code: {log_msg}")
            await self._close_ctx(utc.ts() + 60 * 15)  # 15 minutes
            raise HandledError()

    async def get(self, url: str, params: ReqParams = None) -> Response | None:
        return await self.req("GET", url, params=params)

    async def req(self, method: HttpMethod, url: str, params: ReqParams = None) -> Response | None:
        unknown_retry, connection_retry, network_retry = 0, 0, 0
        network_retry_username: str | None = None

        while True:
            ctx = await self._get_ctx()  # not need to close client, class implements __aexit__
            if ctx is None:
                return None

            if ctx.acc.username != network_retry_username:
                network_retry_username = ctx.acc.username
                network_retry = 0

            if not has_required_cookies(ctx.acc.cookies):
                msg = "Missing authentication cookies"
                logger.warning(self._format_ctx_error(ctx, msg))
                await self._close_ctx(inactive=True, msg=msg)
                continue

            try:
                source = telemetry.current_source()
                telemetry.capture(
                    "gql_request",
                    {
                        "operation": self.queue,
                        "http_method": method,
                        "http_backend": getattr(ctx.clt, "backend", "unknown"),
                        "source": source,
                        "$current_url": f"{source}://twscrape/gql/{self.queue}",
                    },
                )
                rep = await ctx.req(method, url, params=params)
                setattr(rep, "__username", ctx.acc.username)
                await self._check_rep(rep)

                ctx.req_count += 1  # count only successful
                unknown_retry, connection_retry = 0, 0
                return rep
            except AbortReqError:
                # abort all queries
                return
            except HandledError:
                # retry with new account
                continue
            except XClIdAccountError as e:
                logger.warning(self._format_ctx_error(ctx, e))
                await self._close_ctx(utc.ts() + 60 * 15)
                continue
            except XClIdParseError as e:
                logger.error(
                    f"{self._format_ctx_error(ctx, e)}; "
                    "Report: https://github.com/vladkens/twscrape/issues"
                )
                await self._close_ctx()
                return None
            except NetworkError as e:
                # http transport failed, retry same account with backoff, up to 3 tries
                network_retry += 1
                if network_retry < 3:
                    await asyncio.sleep(2**network_retry)
                    continue

                # transport keeps failing, short lock (transport problem, not a rate limit) and rotate to the next account
                logger.warning(self._format_ctx_error(ctx, e))
                await self._close_ctx(utc.ts() + 60)
                continue
            except ConnectError as e:
                # if proxy misconfigured or host unreachable
                connection_retry += 1
                if connection_retry >= 3:
                    raise e
            except Exception as e:
                unknown_retry += 1
                if unknown_retry >= 3:
                    msg = [
                        "Unknown error. Account timeouted for 15 minutes.",
                        "Create issue please: https://github.com/vladkens/twscrape/issues",
                        "If it mistake, you can unlock accounts with `twscrape reset_locks`. "
                        f"Err: {self._format_ctx_error(ctx, e)}",
                    ]

                    logger.warning(" ".join(msg))
                    await self._close_ctx(utc.ts() + 60 * 15)  # 15 minutes
