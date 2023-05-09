import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime

from httpx import AsyncClient, AsyncHTTPTransport

from .constants import TOKEN
from .utils import from_utciso


@dataclass
class Account:
    username: str
    password: str
    email: str
    email_password: str
    user_agent: str
    active: bool
    locks: dict[str, datetime]
    headers: dict[str, str] | None = None
    cookies: dict[str, str] | None = None
    proxy: str | None = None
    error_msg: str | None = None

    @staticmethod
    def create_sql():
        return """
        CREATE TABLE IF NOT EXISTS accounts (
            username TEXT PRIMARY KEY NOT NULL COLLATE NOCASE,
            password TEXT NOT NULL,
            email TEXT NOT NULL COLLATE NOCASE,
            email_password TEXT NOT NULL,
            user_agent TEXT NOT NULL,
            active BOOLEAN DEFAULT FALSE NOT NULL,
            locks TEXT DEFAULT '{}' NOT NULL,
            headers TEXT DEFAULT '{}' NOT NULL,
            cookies TEXT DEFAULT '{}' NOT NULL,
            proxy TEXT DEFAULT NULL,
            error_msg TEXT DEFAULT NULL
        );
        """

    @staticmethod
    def from_rs(rs: sqlite3.Row):
        doc = dict(rs)
        doc["locks"] = {k: from_utciso(v) for k, v in json.loads(doc["locks"]).items()}
        doc["headers"] = json.loads(doc["headers"])
        doc["cookies"] = json.loads(doc["cookies"])
        doc["active"] = bool(doc["active"])
        return Account(**doc)

    def to_rs(self):
        rs = asdict(self)
        rs["locks"] = json.dumps(rs["locks"], default=lambda x: x.isoformat())
        rs["headers"] = json.dumps(rs["headers"])
        rs["cookies"] = json.dumps(rs["cookies"])
        return rs

    def make_client(self) -> AsyncClient:
        transport = AsyncHTTPTransport(retries=2)
        client = AsyncClient(proxies=self.proxy, follow_redirects=True, transport=transport)

        # saved from previous usage
        client.cookies.update(self.cookies)
        client.headers.update(self.headers)

        # default settings
        client.headers["user-agent"] = self.user_agent
        client.headers["content-type"] = "application/json"
        client.headers["authorization"] = TOKEN
        client.headers["x-twitter-active-user"] = "yes"
        client.headers["x-twitter-client-language"] = "en"

        return client
