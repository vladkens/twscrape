import json
import os
import time
from typing import Any, Dict, Optional

import httpx
from httpx import AsyncClient, Response

from .accounts_pool import Account, AccountsPool
from .logger import logger
from .utils import utc

ReqParams = Optional[Dict[str, str | int]]
TMP_TS = utc.now().isoformat().split(".")[0].replace("T", "_").replace(":", "-")[0:16]


class Context:
    def __init__(self, account: Account, client: AsyncClient):
        self.account = account
        self.client = client
        self.request_count = 0


class HandledError(Exception):
    pass


class AbortRequestError(Exception):
    pass


def request_id(response: Response) -> str:
    limit_remaining = int(response.headers.get("x-rate-limit-remaining", -1))
    limit_reset = int(response.headers.get("x-rate-limit-reset", -1))
    size = max(len(str(limit_remaining)), len(str(limit_reset)))
    limit_remaining, limit_reset = str(limit_remaining).rjust(size), str(limit_reset).rjust(size)

    username = getattr(response, "__username", "<UNKNOWN>")
    return f"{limit_remaining}/{limit_reset} - {username}"


def dump_response(response: Response):
    count = getattr(dump_response, "__count", -1) + 1
    setattr(dump_response, "__count", count)

    account = getattr(response, "__username", "<unknown>")
    output_file = f"{count:05d}_{response.status_code}_{account}.txt"
    output_file = f"/tmp/twscrape-{TMP_TS}/{output_file}"
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    message = []
    message.append(f"{count:,d} - {request_id(response)}")
    message.append(f"{response.status_code} {response.request.method} {response.request.url}")
    message.append("\n")
    message.append("\n".join([str(x) for x in list(response.request.headers.items())]))
    message.append("\n")

    try:
        message.append(json.dumps(response.json(), indent=2))
    except json.JSONDecodeError:
        message.append(response.text)

    text = "\n".join(message)
    with open(output_file, "w") as f:
        f.write(text)


class QueueClient:
    def __init__(self, pool: AccountsPool, queue: str, debug: bool = False, proxy: str | None = None):
        self.pool = pool
        self.queue = queue
        self.debug = debug
        self.context: Context | None = None
        self.proxy = proxy

    async def __aenter__(self):
        await self._get_context()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._close_context()

    async def _close_context(self, reset_at: int = -1, inactive: bool = False, msg: str | None = None):
        if self.context is None:
            return

        context, self.context, self.context.request_count = self.context, None, 0
        account = context.account
        await context.client.aclose()

        if inactive:
            await self.pool.mark_inactive(account.username, msg)
            return

        if reset_at > 0:
            await self.pool.lock_until(account.username, self.queue, reset_at, context.request_count)
            return

        await self.pool.unlock(account.username, self.queue, context.request_count)

    async def _get_context(self):
        if self.context:
            return self.context

        account = self.pool.get_for_queue_or_wait(self.queue)
        if account is None:
            return None

        client = account.make_client(proxy=self.proxy)
        self.context = Context(account, client)
        return self.context

    async def _check_response(self, response: Response) -> None:
        """
        This function can raise Exception and request will be retried or aborted
        Or if None is returned, response will passed to api parser as is
        """

        if self.debug:
            dump_response(response)

        try:
            data = response.json()
        except json.JSONDecodeError:
            data: Any = {"_raw": response.text}

        limit_remaining = int(response.headers.get("x-rate-limit-remaining", -1))
        limit_reset = int(response.headers.get("x-rate-limit-reset", -1))

        error_msg = "OK"
        if "errors" in data:
            error_msg = set([f"({x.get('code', -1)}) {x['message']}" for x in data["errors"]])
            error_msg = "; ".join(list(error_msg))

        log_msg = f"{response.status_code:3d} - {request_id(response)} - {error_msg}"
        logger.trace(log_msg)

        if error_msg.startswith("(336) The following features cannot be null"):
            logger.error(f"[DEV] Update required: {error_msg}")
            exit(1)

        if limit_remaining == 0 and limit_reset > 0:
            logger.debug(f"Rate limited: {log_msg}")
            await self._close_context(limit_reset)
            raise HandledError()

        if error_msg.startswith("(88) Rate limit exceeded") and limit_remaining > 0:
            logger.warning(f"Ban detected: {log_msg}")
            await self._close_context(-1, inactive=True, msg=error_msg)
            raise HandledError()

        if error_msg.startswith("(326) Authorization: Denied by access control"):
            logger.warning(f"Ban detected: {log_msg}")
            await self._close_context(-1, inactive=True, msg=error_msg)
            raise HandledError()

        if error_msg.startswith("(64) Your account is suspended"):
            logger.warning(f"Ban detected: {log_msg}")
            await self._close_context(-1, inactive=True, msg=error_msg)
            raise HandledError()

        if error_msg.startswith("(32) Could not authenticate you"):
            logger.warning(f"Session expired or banned: {log_msg}")
            await self._close_context(-1, inactive=True, msg=error_msg)
            raise HandledError()

        if error_msg.startswith("(29) Timeout: Unspecified"):
            logger.warning(f"Timeout: {log_msg}")
            await self._close_context(-1, inactive=False, msg=error_msg)
            raise HandledError()

        if error_msg == "OK" and response.status_code == 403:
            logger.warning(f"Session expired or banned: {log_msg}")
            await self._close_context(-1, inactive=True, msg=None)
            raise HandledError()

        if error_msg.startswith("(131) Dependency: Internal error"):
            if response.status_code == 200 and "data" in data and "user" in data["data"]:
                error_msg = "OK"
            else:
                logger.warning(f"Dependency error (request skipped): {error_msg}")
                raise AbortRequestError()

        if response.status_code == 200 and "_Missing: No status found with that ID" in error_msg:
            return  # ignore this error

        if response.status_code == 200 and "Authorization" in error_msg:
            logger.warning(f"Authorization unknown error: {log_msg}")
            return

        if error_msg != "OK":
            logger.warning(f"API unknown error: {log_msg}")
            return  # ignore any other unknown errors

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            logger.error(f"Unhandled API response code: {log_msg}")
            await self._close_context(int(time.time()) + 60 * 15)  # 15 minutes
            raise HandledError()

    async def get(self, url: str, params: ReqParams = None):
        return await self.request("GET", url, params=params)

    async def request(self, method: str, url: str, params: ReqParams = None) -> Response | None:
        unknown_retry, connection_retry = 0, 0

        while True:
            context = await self._get_context()  # no need to close client, class implements __aexit__
            if context is None:
                return None

            try:
                response = await context.client.request(method, url, params=params)
                setattr(response, "__username", context.account.username)
                await self._check_response(response)

                context.request_count += 1  # count only successful
                unknown_retry, connection_retry = 0, 0
                return response
            except AbortRequestError:
                # abort all queries
                return
            except HandledError:
                # retry with new account
                continue
            except (httpx.ReadTimeout, httpx.ProxyError):
                # http transport failed, just retry with same account
                continue
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                # if proxy misconfigured or ???
                connection_retry += 1
                if connection_retry >= 3:
                    raise e
            except httpx.RequestError as e:
                unknown_retry += 1
                if unknown_retry >= 3:
                    msg = [
                        "Unknown error. Account timeouted for 15 minutes.",
                        "Create issue please: https://github.com/vladkens/twscrape/issues",
                        f"If it mistake, you can unlock account now with `twscrape reset_locks`. Err: {type(e)}: {e}",
                    ]

                    logger.warning(" ".join(msg))
                    await self._close_context(int(time.time()) + 60 * 15)  # 15 minutes
