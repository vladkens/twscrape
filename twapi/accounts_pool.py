import asyncio
import os

from .account import Account, Status
from .logger import logger


class AccountsPool:
    BASE_DIR = "accounts"

    def __init__(self):
        self.accounts: list[Account] = []

    def load_from_dir(self, folder: str | None = None):
        folder = folder or self.BASE_DIR

        files = os.listdir(folder)
        files = [x for x in files if x.endswith(".json")]
        files = [os.path.join(folder, x) for x in files]

        for file in files:
            account = Account.load(file)
            if account:
                self.accounts.append(account)

    def add_account(
        self,
        login: str,
        password: str,
        email: str,
        email_password: str,
        proxy: str | None = None,
        user_agent: str | None = None,
    ):
        filepath = os.path.join(self.BASE_DIR, f"{login}.json")
        account = Account.load(filepath)
        if account:
            self.accounts.append(account)
            return

        account = Account(login, password, email, email_password, user_agent, proxy)
        self.accounts.append(account)

    async def login(self):
        for x in self.accounts:
            try:
                if x.status == Status.NEW:
                    await x.login()
            except Exception as e:
                logger.error(f"Error logging in to {x.username}: {e}")
                pass

    def get_username_by_token(self, auth_token: str) -> str:
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
