import asyncio

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
