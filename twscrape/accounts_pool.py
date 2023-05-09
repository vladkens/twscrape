# ruff: noqa: E501
import asyncio

from fake_useragent import UserAgent

from .account import Account
from .db import add_init_query, execute, fetchall, fetchone
from .logger import logger
from .login import login


class AccountsPool:
    def __init__(self, db_file="accounts.db"):
        self._db_file = db_file
        add_init_query(db_file, Account.create_sql())

    async def add_account(
        self,
        username: str,
        password: str,
        email: str,
        email_password: str,
        user_agent: str | None = None,
        proxy: str | None = None,
    ):
        qs = "SELECT * FROM accounts WHERE username = :username"
        rs = await fetchone(self._db_file, qs, {"username": username})
        if rs:
            return

        account = Account(
            username=username,
            password=password,
            email=email,
            email_password=email_password,
            user_agent=user_agent or UserAgent().safari,
            active=False,
            locks={},
            headers={},
            cookies={},
            proxy=proxy,
        )
        await self.save(account)

    async def get(self, username: str):
        qs = "SELECT * FROM accounts WHERE username = :username"
        rs = await fetchone(self._db_file, qs, {"username": username})
        if not rs:
            raise ValueError(f"Account {username} not found")
        return Account.from_rs(rs)

    async def get_all(self):
        qs = "SELECT * FROM accounts"
        rs = await fetchall(self._db_file, qs)
        return [Account.from_rs(x) for x in rs]

    async def save(self, account: Account):
        data = account.to_rs()
        cols = list(data.keys())

        qs = f"""
        INSERT INTO accounts ({",".join(cols)}) VALUES ({",".join([f":{x}" for x in cols])})
        ON CONFLICT DO UPDATE SET {",".join([f"{x}=excluded.{x}" for x in cols])}
        """
        await execute(self._db_file, qs, data)

    async def login(self, account: Account):
        try:
            await login(account)
        except Exception as e:
            logger.error(f"Error logging in to {account.username}: {e}")
        finally:
            await self.save(account)

    async def login_all(self):
        qs = "SELECT * FROM accounts WHERE active = false AND error_msg IS NULL"
        rs = await fetchall(self._db_file, qs)

        accounts = [Account.from_rs(rs) for rs in rs]
        # await asyncio.gather(*[login(x) for x in self.accounts])

        for i, x in enumerate(accounts, start=1):
            logger.info(f"[{i}/{len(accounts)}] Logging in {x.username} - {x.email}")
            await self.login(x)

    async def set_active(self, username: str, active: bool):
        qs = "UPDATE accounts SET active = :active WHERE username = :username"
        await execute(self._db_file, qs, {"username": username, "active": active})

    async def lock_until(self, username: str, queue: str, unlock_at: int):
        qs = f"""
        UPDATE accounts SET locks = json_set(locks, '$.{queue}', datetime({unlock_at}, 'unixepoch'))
        WHERE username = :username
        """
        await execute(self._db_file, qs, {"username": username})

    async def unlock(self, username: str, queue: str):
        qs = f"""
        UPDATE accounts SET locks = json_remove(locks, '$.{queue}')
        WHERE username = :username
        """
        await execute(self._db_file, qs, {"username": username})

    async def get_for_queue(self, queue: str):
        q1 = f"""
        SELECT username FROM accounts
        WHERE active = true AND (
            locks IS NULL
            OR json_extract(locks, '$.{queue}') IS NULL
            OR json_extract(locks, '$.{queue}') < datetime('now')
        )
        ORDER BY RANDOM()
        LIMIT 1
        """

        q2 = f"""
        UPDATE accounts SET locks = json_set(locks, '$.{queue}', datetime('now', '+15 minutes'))
        WHERE username = ({q1})
        RETURNING *
        """

        rs = await fetchone(self._db_file, q2)
        return Account.from_rs(rs) if rs else None

    async def get_for_queue_or_wait(self, queue: str) -> Account:
        while True:
            account = await self.get_for_queue(queue)
            if not account:
                logger.debug(f"No accounts available for queue '{queue}' (sleeping for 5 sec)")
                await asyncio.sleep(5)
                continue

            logger.debug(f"Using account {account.username} for queue '{queue}'")
            return account

    async def stats(self):
        def by_queue(queue: str):
            return f"""
            SELECT COUNT(*) FROM accounts
            WHERE json_extract(locks, '$.{queue}') IS NOT NULL AND json_extract(locks, '$.{queue}') > datetime('now')
            """

        gql_ops = """
        UserByRestId UserByScreenName TweetDetail Followers Following
        Retweeters Favoriters UserTweets UserTweetsAndReplies
        """
        gql_ops = [x.strip() for x in gql_ops.split(" ") if x.strip()]

        config = [
            ("total", "SELECT COUNT(*) FROM accounts"),
            ("active", "SELECT COUNT(*) FROM accounts WHERE active = true"),
            ("inactive", "SELECT COUNT(*) FROM accounts WHERE active = false"),
            ("locked_search", by_queue("search")),
            *[(f"locked_{x}", by_queue(x)) for x in gql_ops],
        ]

        qs = f"SELECT {','.join([f'({q}) as {k}' for k, q in config])}"
        rs = await fetchone(self._db_file, qs)
        return dict(rs) if rs else {}
