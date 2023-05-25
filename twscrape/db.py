import asyncio
import sqlite3
from collections import defaultdict

import aiosqlite

MIN_SQLITE_VERSION = "3.34"


def lock_retry(max_retries=5, delay=1):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            for i in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    if i == max_retries - 1 or "database is locked" not in str(e):
                        raise e

                    # print(f"Retrying in {delay} second(s) ({i+1}/{max_retries})")
                    await asyncio.sleep(delay)

        return wrapper

    return decorator


async def check_version(db: aiosqlite.Connection):
    async with db.execute("SELECT SQLITE_VERSION()") as cur:
        rs = await cur.fetchone()
        rs = rs[0] if rs else "3.0.0"
        rs = ".".join(rs.split(".")[:2])

        if rs < MIN_SQLITE_VERSION:
            msg = f"SQLite version '{rs}' is too old, please upgrade to {MIN_SQLITE_VERSION}+"
            raise SystemError(msg)


class DB:
    _init_queries: defaultdict[str, list[str]] = defaultdict(list)
    _init_once: defaultdict[str, bool] = defaultdict(bool)

    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = None

    async def __aenter__(self):
        db = await aiosqlite.connect(self.db_path)
        db.row_factory = aiosqlite.Row
        await check_version(db)

        if not self._init_once[self.db_path]:
            for qs in self._init_queries[self.db_path]:
                await db.execute(qs)

            await db.commit()  # required here because of _init_once
            self._init_once[self.db_path] = True

        self.conn = db
        return db

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            await self.conn.commit()
            await self.conn.close()


def add_init_query(db_path: str, qs: str):
    DB._init_queries[db_path].append(qs)


@lock_retry()
async def execute(db_path: str, qs: str, params: dict | None = None):
    async with DB(db_path) as db:
        await db.execute(qs, params)


@lock_retry()
async def fetchone(db_path: str, qs: str, params: dict | None = None):
    async with DB(db_path) as db:
        async with db.execute(qs, params) as cur:
            row = await cur.fetchone()
            return row


@lock_retry()
async def fetchall(db_path: str, qs: str, params: dict | None = None):
    async with DB(db_path) as db:
        async with db.execute(qs, params) as cur:
            rows = await cur.fetchall()
            return rows


@lock_retry()
async def executemany(db_path: str, qs: str, params: list[dict]):
    async with DB(db_path) as db:
        await db.executemany(qs, params)
