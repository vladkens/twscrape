import asyncio
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fake_useragent import UserAgent
from httpx import HTTPStatusError

from .account import Account, AccountRS
from .db import (
    connect,
    execute,
    fetchall,
    fetchone,
    insert,
    json_extract,
    json_object,
    json_remove,
    json_set,
    update,
)
from .logger import logger
from .login import LoginConfig, login
from .utils import get_env_bool, parse_cookies, utc


class NoAccountError(Exception):
    pass


class AccountsPool:
    """A pool of accounts for rate limiting."""

    def __init__(
        self,
        db_file: str = "accounts.db",
        login_config: Optional[LoginConfig] = None,
        raise_when_no_account: bool = False,
    ):
        """Initialize the AccountsPool.

        Args:
            db_file (str, optional): The path to the SQLite database file. Defaults to "accounts.db".
            login_config (LoginConfig, optional): The login configuration. Defaults to None.
            raise_when_no_account (bool, optional): Whether to raise an exception when no account is available. Defaults to False.
        """
        self.db_file = db_file
        self.login_config = login_config or LoginConfig()
        self.raise_when_no_account = raise_when_no_account

    async def load_from_file(self, filepath: str, line_format: str):
        """Load accounts from a file.

        Args:
            filepath (str): The path to the file.
            line_format (str): The format of the lines in the file.
        """
        line_delim = self.guess_delim(line_format)
        tokens = line_format.split(line_delim)

        required = {"username", "password", "email", "email_password"}
        if required.issubset(tokens) is False:
            raise ValueError(f"Invalid line format: {line_format}")

        accounts = []
        with open(filepath, "r") as f:
            lines = f.read().split("\n")
            lines = [x.strip() for x in lines if x.strip()]

            for line in lines:
                data = [x.strip() for x in line.split(line_delim)]
                if len(data) < len(tokens):
                    raise ValueError(f"Invalid line: {line}")

                data = data[: len(tokens)]
                vals = {k: v for k, v in zip(tokens, data) if k != "_"}
                accounts.append(vals)

        for x in accounts:
            await self.add_account(**x)

    @staticmethod
    def guess_delim(line: str) -> str:
        """Guess the delimiter of a line.

        Args:
            line (str): The line to guess the delimiter of.

        Returns:
            str: The delimiter.
        """
        lp, rp = tuple([x.strip() for x in line.split("username")])
        return rp[0] if not lp else lp[-1]

    async def add_account(
        self,
        username: str,
        password: str,
        email: str,
        email_password: str,
        user_agent: Optional[str] = None,
        proxy: Optional[str] = None,
        cookies: Optional[str] = None,
        mfa_code: Optional[str] = None,
    ):
        """Add an account to the pool.

        Args:
            username (str): The username of the account.
            password (str): The password of the account.
            email (str): The email of the account.
            email_password (str): The email password of the account.
            user_agent (str, optional): The user agent of the account. Defaults to None.
            proxy (str, optional): The proxy of the account. Defaults to None.
            cookies (str, optional): The cookies of the account. Defaults to None.
            mfa_code (str, optional): The MFA code of the account. Defaults to None.
        """
        qs = "SELECT * FROM accounts WHERE username = :username"
        rs = await fetchone(self.db_file, qs, {"username": username})
        if rs:
            logger.warning(f"Account {username} already exists")
            return

        account = Account(
            username=username,
            password=password,
            email=email,
            email_password=email_password,
            user_agent=user_agent or UserAgent().safari,
            active=False,
            locks={},
            stats={},
            headers={},
            cookies=parse_cookies(cookies) if cookies else {},
            proxy=proxy,
            mfa_code=mfa_code,
        )

        if "ct0" in account.cookies:
            account.active = True

        await self.save(account)
        logger.info(f"Account {username} added successfully (active={account.active})")

    async def delete_accounts(self, usernames: str | List[str]):
        """Delete accounts from the pool.

        Args:
            usernames (str | List[str]): The usernames of the accounts to delete.
        """
        usernames = usernames if isinstance(usernames, list) else [usernames]
        usernames = list(set(usernames))
        if not usernames:
            logger.warning("No usernames provided")
            return

        qs = f"""DELETE FROM accounts WHERE username IN ({",".join([f'"{x}"' for x in usernames])})"""
        await execute(self.db_file, qs)

    async def delete_inactive(self):
        """Delete inactive accounts from the pool."""
        qs = "DELETE FROM accounts WHERE active = false"
        await execute(self.db_file, qs)

    async def get(self, username: str):
        """Get an account from the pool.

        Args:
            username (str): The username of the account.

        Returns:
            Account: The account.

        Raises:
            ValueError: If the account is not found.
        """
        qs = "SELECT * FROM accounts WHERE username = :username"
        rs = await fetchone(self.db_file, qs, {"username": username})
        if not rs:
            raise ValueError(f"Account {username} not found")
        return Account.from_rs(rs)

    async def get_all(self):
        """Get all accounts from the pool.

        Returns:
            List[Account]: The accounts.
        """
        qs = "SELECT * FROM accounts"
        rs = await fetchall(self.db_file, qs)
        return [Account.from_rs(x) for x in rs]

    async def get_account(self, username: str):
        """Get an account from the pool.

        Args:
            username (str): The username of the account.

        Returns:
            Account | None: The account or None if not found.
        """
        qs = "SELECT * FROM accounts WHERE username = :username"
        rs = await fetchone(self.db_file, qs, {"username": username})
        if not rs:
            return None
        return Account.from_rs(rs)

    async def save(self, account: Account):
        """Save an account to the pool.

        Args:
            account (Account): The account.
        """
        data = account.to_rs()
        cols = list(data.keys())

        qs = f"""
        INSERT INTO accounts ({",".join(cols)}) VALUES ({",".join([f":{x}" for x in cols])})
        ON CONFLICT(username) DO UPDATE SET {",".join([f"{x}=excluded.{x}" for x in cols])}
        """
        await insert(self.db_file, qs, data)

    async def login(self, account: Account):
        """Login to an account.

        Args:
            account (Account): The account.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            await login(account, cfg=self.login_config)
            logger.info(f"Logged in to {account.username} successfully")
            return True
        except HTTPStatusError as e:
            rep = e.response
            logger.error(
                f"Failed to login '{account.username}': {rep.status_code} - {rep.text}"
            )
            return False
        except Exception as e:
            logger.error(f"Failed to login '{account.username}': {e}")
            return False
        finally:
            await self.save(account)

    async def login_all(self, usernames: List[str] | None = None):
        """Login to all accounts.

        Args:
            usernames (List[str] | None, optional): The usernames of the accounts to login. Defaults to None.

        Returns:
            Dict[str, int]: A dictionary with the number of successful and failed logins.
        """
        if usernames is None:
            qs = "SELECT * FROM accounts WHERE active = false AND error_msg IS NULL"
        else:
            us = ",".join([f'"{x}"' for x in usernames])
            qs = f"SELECT * FROM accounts WHERE username IN ({us})"

        rs = await fetchall(self.db_file, qs)
        accounts = [Account.from_rs(rs) for rs in rs]

        counter = {
            "total": len(accounts),
            "success": 0,
            "failed": 0,
        }
        for i, x in enumerate(accounts, start=1):
            logger.info(f"[{i}/{len(accounts)}] Logging in {x.username} - {x.email}")
            status = await self.login(x)
            if status:
                counter["success"] += 1
            else:
                counter["failed"] += 1
        return counter

    async def relogin(self, usernames: str | List[str]):
        """Relogin to accounts.

        Args:
            usernames (str | List[str]): The usernames of the accounts to relogin.
        """
        usernames = usernames if isinstance(usernames, list) else [usernames]
        usernames = list(set(usernames))
        if not usernames:
            logger.warning("No usernames provided")
            return

        qs = f"""
        UPDATE accounts SET
            active = false,
            locks = json_object(),
            last_used = NULL,
            error_msg = NULL,
            headers = json_object(),
            cookies = json_object(),
            user_agent = "{UserAgent().safari}"
        WHERE username IN ({','.join([f'"{x}"' for x in usernames])})
        """

        await execute(self.db_file, qs)
        await self.login_all(usernames)

    async def relogin_failed(self):
        """Relogin to failed accounts."""
        qs = "SELECT username FROM accounts WHERE active = false AND error_msg IS NOT NULL"
        rs = await fetchall(self.db_file, qs)
        await self.relogin([x["username"] for x in rs])

    async def reset_locks(self):
        """Reset locks for all accounts."""
        qs = "UPDATE accounts SET locks = json_object()"
        await execute(self.db_file, qs)

    async def set_active(self, username: str, active: bool):
        """Set an account as active.

        Args:
            username (str): The username of the account.
            active (bool): Whether the account is active or not.
        """
        qs = "UPDATE accounts SET active = :active WHERE username = :username"
        await execute(self.db_file, qs, {"username": username, "active": active})

    async def lock_until(
        self, username: str, queue: str, unlock_at: int, req_count: int = 0
    ):
        """Lock an account until a certain time.

        Args:
            username (str): The username of the account.
            queue (str): The queue to lock the account for.
            unlock_at (int): The time to unlock the account.
            req_count (int, optional): The number of requests. Defaults to 0.
        """
        qs = f"""
        UPDATE accounts SET
            locks = json_set(locks, '$.{queue}', datetime({unlock_at}, 'unixepoch')),
            stats = json_set(stats, '$.{queue}', COALESCE(json_extract(stats, '$.{queue}'), 0) + {req_count}),
            last_used = datetime({utc.ts()}, 'unixepoch')
        WHERE username = :username
        """
        await execute(self.db_file, qs, {"username": username})

    async def unlock(self, username: str, queue: str, req_count: int = 0):
        """Unlock an account.

        Args:
            username (str): The username of the account.
            queue (str): The queue to unlock the account for.
            req_count (int, optional): The number of requests. Defaults to 0.
        """
        qs = f"""
        UPDATE accounts SET
            locks = json_remove(locks, '$.{queue}'),
            stats = json_set(stats, '$.{queue}', COALESCE(json_extract(stats, '$.{queue}'), 0) + {req_count}),
            last_used = datetime({utc.ts()}, 'unixepoch')
        WHERE username = :username
        """
        await execute(self.db_file, qs, {"username": username})

    async def _get_and_lock(self, queue: str, condition: str):
        """Get and lock an account.

        Args:
            queue (str): The queue to lock the account for.
            condition (str): The condition to select the account.

        Returns:
            Account | None: The account or None if not found.
        """
        # if space in condition, it's a subquery, otherwise it's username
        condition = f"({condition})" if " " in condition else f"'{condition}'"

        if int(sqlite3.sqlite_version_info[1]) >= 35:
            qs = f"""
            UPDATE accounts SET
                locks = json_set(locks, '$.{queue}', datetime('now', '+15 minutes')),
                last_used = datetime({utc.ts()}, 'unixepoch')
            WHERE username = {condition}
            RETURNING *
            """
            rs = await fetchone(self.db_file, qs)
        else:
            tx = uuid.uuid4().hex
            qs = f"""
            UPDATE accounts SET
                locks = json_set(locks, '$.{queue}', datetime('now', '+15 minutes')),
                last_used = datetime({utc.ts()}, 'unixepoch'),
                _tx = '{tx}'
            WHERE username = {condition}
            """
            await execute(self.db_file, qs)

            qs = f"SELECT * FROM accounts WHERE _tx = '{tx}'"
            rs = await fetchone(self.db_file, qs)

        return Account.from_rs(rs) if rs else None

    async def get_for_queue(self, queue: str):
        """Get an account for a queue.

        Args:
            queue (str): The queue to get the account for.

        Returns:
            Account | None: The account or None if not found.
        """
        q = f"""
        SELECT username FROM accounts
        WHERE active = true AND (
            locks IS NULL
            OR json_extract(locks, '$.{queue}') IS NULL
            OR json_extract(locks, '$.{queue}') < datetime('now')
        )
        ORDER BY {self._order_by}
        LIMIT 1
        """

        return await self._get_and_lock(queue, q)

    async def get_for_queue_or_wait(self, queue: str) -> Account | None:
        """Get an account for a queue or wait.

        Args:
            queue (str): The queue to get the account for.

        Returns:
            Account | None: The account or None if not found.
        """
        msg_shown = False
        while True:
            account = await self.get_for_queue(queue)
            if not account:
                if self.raise_when_no_account or get_env_bool("TWS_RAISE_WHEN_NO_ACCOUNT"):
                    raise NoAccountError(f"No account available for queue {queue}")

                if not msg_shown:
                    nat = await self.next_available_at(queue)
                    if not nat:
                        logger.warning("No active accounts. Stopping...")
                        return None

                    msg = f'No account available for queue "{queue}". Next available at {nat}'
                    logger.info(msg)
                    msg_shown = True

                await asyncio.sleep(5)
                continue
            else:
                if msg_shown:
                    logger.info(f"Continuing with account {account.username} on queue {queue}")

            return account

    async def next_available_at(self, queue: str):
        """Get the next available time for a queue.

        Args:
            queue (str): The queue to get the next available time for.

        Returns:
            str | None: The next available time or None if not found.
        """
        qs = f"""
        SELECT json_extract(locks, '$."{queue}"') as lock_until
        FROM accounts
        WHERE active = true AND json_extract(locks, '$."{queue}"') IS NOT NULL
        ORDER BY lock_until ASC
        LIMIT 1
        """
        rs = await fetchone(self.db_file, qs)
        if rs:
            now, trg = utc.now(), utc.from_iso(rs[0])
            if trg < now:
                return "now"

            at_local = datetime.now() + (trg - now)
            return at_local.strftime("%H:%M:%S")

        return None

    async def mark_inactive(self, username: str, error_msg: str | None):
        """Mark an account as inactive.

        Args:
            username (str): The username of the account.
            error_msg (str | None): The error message.
        """
        qs = """
        UPDATE accounts SET active = false, error_msg = :error_msg
        WHERE username = :username
        """
        await update(self.db_file, qs, {"username": username, "error_msg": error_msg})

    async def stats(self) -> Dict[str, Any]:
        """Get the stats for the pool.

        Returns:
            Dict[str, Any]: The stats.
        """
        def locks_count(queue: str):
            return f"""
            SELECT COUNT(*) FROM accounts
            WHERE json_extract(locks, '$.{queue}') IS NOT NULL
                AND json_extract(locks, '$.{queue}') > datetime('now')
            """

        qs = f"SELECT DISTINCT(f.key) as k from accounts, json_each(locks) f"
        rs = await fetchall(self.db_file, qs)
        gql_ops = [x["k"] for x in rs]

        config = [
            ("total", "SELECT COUNT(*) FROM accounts"),
            ("active", "SELECT COUNT(*) FROM accounts WHERE active = true"),
            ("inactive", "SELECT COUNT(*) FROM accounts WHERE active = false"),
            *[(f"locked_{x}", locks_count(x)) for x in gql_ops],
        ]

        qs = f"SELECT {','.join([f'({q}) as {k}' for k, q in config])}"
        rs = await fetchone(self.db_file, qs)
        return dict(rs) if rs else {}

    async def accounts_info(self) -> List[Dict[str, Any]]:
        """Get the info for all accounts.

        Returns:
            List[Dict[str, Any]]: The account info.
        """
        accounts = await self.get_all()

        items: List[Dict[str, Any]] = []
        for x in accounts:
            item = {
                "username": x.username,
                "logged_in": (x.headers or {}).get("authorization", "") != "",
                "active": x.active,
                "last_used": x.last_used,
                "total_req": sum(x.stats.values()),
                "error_msg": str(x.error_msg)[0:60],
            }
            items.append(item)

        old_time = datetime(1970, 1, 1).replace(tzinfo=timezone.utc)
        items = sorted(items, key=lambda x: x["username"].lower())
        items = sorted(
            items,
            key=lambda x: x["last_used"] or old_time if x["total_req"] > 0 else old_time,
            reverse=True,
        )
        items = sorted(items, key=lambda x: x["active"], reverse=True)
        # items = sorted(items, key=lambda x: x["total_req"], reverse=True)
        return items
