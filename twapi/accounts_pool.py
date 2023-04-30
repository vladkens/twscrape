import asyncio
import json
import os

from .account import Account, Status
from .logger import logger
from .utils import shuffle


class AccountsPool:
    def __init__(self, base_dir: str | None = None):
        self.accounts: list[Account] = []
        self.base_dir = base_dir or "accounts"

    def restore(self):
        files = [os.path.join(self.base_dir, x) for x in os.listdir(self.base_dir)]
        files = [x for x in files if x.endswith(".json")]
        for file in files:
            self._load_account_from_file(file)

    def _load_account_from_file(self, filepath: str):
        account = Account.load_from_file(filepath)
        if account:
            username = set(x.username for x in self.accounts)
            if account.username in username:
                raise ValueError(f"Duplicate username {account.username}")
            self.accounts.append(account)
        return account

    def _get_filename(self, username: str):
        return f"{self.base_dir}/{username}.json"

    def add_account(
        self,
        login: str,
        password: str,
        email: str,
        email_password: str,
        proxy: str | None = None,
        user_agent: str | None = None,
    ):
        account = self._load_account_from_file(self._get_filename(login))
        if account:
            return

        account = Account(
            login,
            password,
            email,
            email_password,
            proxy=proxy,
            user_agent=user_agent,
        )
        self.save_account(account)
        self._load_account_from_file(self._get_filename(login))

    async def login(self):
        for x in self.accounts:
            try:
                if x.status == Status.NEW:
                    await x.login()
            except Exception as e:
                logger.error(f"Error logging in to {x.username}: {e}")
            finally:
                self.save_account(x)

    def get_username_by_token(self, auth_token: str) -> str:
        for x in self.accounts:
            if x.client.cookies.get("auth_token") == auth_token:
                return x.username
        return "UNKNOWN"

    def get_account(self, queue: str) -> Account | None:
        accounts = shuffle(self.accounts)  # make random order each time
        for x in accounts:
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

    def save_account(self, account: Account):
        filename = self._get_filename(account.username)
        data = account.dump()

        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, "w") as f:
            json.dump(data, f, indent=2)

    def update_limit(self, account: Account, queue: str, reset_ts: int):
        account.update_limit(queue, reset_ts)
        self.save_account(account)
