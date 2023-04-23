import asyncio
from typing import AsyncGenerator, Callable, Tuple

from httpx import AsyncClient, HTTPStatusError, Response
from loguru import logger

from .client import UserClient


class AccountsPool:
    def __init__(self):
        self.accounts: list[UserClient] = []

    def add_account(self, account: UserClient):
        self.accounts.append(account)

    def get_account(self, queue: str) -> UserClient | None:
        for x in self.accounts:
            if x.can_use(queue):
                return x
        return None

    async def get_account_or_wait(self, queue: str) -> UserClient:
        while True:
            account = self.get_account(queue)
            if account:
                logger.debug(f"Using account {account.username} for queue '{queue}'")
                account.lock(queue)
                return account
            else:
                logger.debug(f"No accounts available for queue '{queue}' (sleeping for 5 sec)")
                await asyncio.sleep(5)

    async def execute(
        self,
        queue: str,
        cb: Callable[
            [AsyncClient, str | None], AsyncGenerator[Tuple[Response, dict, str | None], None]
        ],
        cursor: str | None = None,
    ):
        while True:
            account = await self.get_account_or_wait(queue)

            try:
                client = account.make_client()
                async for x in cb(client, cursor):
                    rep, data, cursor = x
                    yield rep, data, cursor
                return  # exit if no more results
            except HTTPStatusError as e:
                if e.response.status_code == 429:
                    account.update_limit(queue, e.response)
                    logger.debug(f"Rate limit reached for account {account.username}")
                    continue
                else:
                    raise e
            finally:
                account.unlock(queue)
