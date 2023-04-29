import asyncio

from loguru import logger

from .account import Account


class AccountsPool:
    def __init__(self):
        self.accounts: list[Account] = []

    def add_account(self, account: Account):
        self.accounts.append(account)

    def get_login_by_token(self, auth_token: str) -> str:
        for x in self.accounts:
            if x.client.cookies.get("auth_token") == auth_token:
                return x.username
        return "UNKNOWN"

    def get_account(self, queue: str) -> Account | None:
        for x in self.accounts:
            if x.can_use(queue):
                return x
        return None

    async def get_account_or_wait(self, queue: str) -> Account:
        while True:
            account = self.get_account(queue)
            if account:
                logger.debug(f"Using account {account.username} for queue '{queue}'")
                account.lock(queue)
                return account
            else:
                logger.debug(f"No accounts available for queue '{queue}' (sleeping for 5 sec)")
                await asyncio.sleep(5)
