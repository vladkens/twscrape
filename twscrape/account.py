import json
import os
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, Literal, Optional, TypedDict

import httpx
from httpx import AsyncClient, AsyncHTTPTransport, Timeout

from .models import JSONTrait
from .utils import utc

TOKEN: Literal["Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"] = "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"


class AccountAttributes(TypedDict):
    username: str
    password: str
    email: str
    email_password: str
    user_agent: str
    active: bool
    locks: Dict[str, str]
    stats: Dict[str, str]
    headers: Dict[str, str]
    cookies: Dict[str, str]
    mfa_code: Optional[str]
    proxy: Optional[str]
    error_msg: Optional[str]
    last_used: Optional[str]
    _tx: Optional[str]


@dataclass
class Account(JSONTrait):
    __slots__ = ()

    attributes: AccountAttributes

    @staticmethod
    def from_rs(rs: sqlite3.Row) -> "Account":
        return Account(attributes=AccountAttributes(**rs))

    def to_rs(self) -> Dict[str, Any]:
        rs = asdict(self, dict_factory=lambda x: x.attributes)
        rs["locks"] = json.dumps(rs["attributes"]["locks"], default=lambda x: x.isoformat())
        rs["stats"] = json.dumps(rs["attributes"]["stats"])
        rs["headers"] = json.dumps(rs["attributes"]["headers"])
        rs["cookies"] = json.dumps(rs["attributes"]["cookies"])
        rs["last_used"] = rs["attributes"]["last_used"].isoformat() if rs["attributes"]["last_used"] else None
        return rs

    @lru_cache()
    def make_client(self, proxy: Optional[str] = None) -> AsyncClient:
        proxies = [proxy, os.getenv("TWS_PROXY"), self.attributes["proxy"]]
        proxies = [x for x in proxies if x is not None]
        proxy = proxies[0] if proxies else None

        transport = AsyncHTTPTransport(retries=2)
        client = AsyncClient(
            proxy=proxy,
            follow_redirects=True,
            timeout=Timeout(5.0),
            transport=transport,
        )

        # saved from previous usage
        client.cookies.update(json.loads(self.attributes["cookies"]))
        client.headers.update(json.loads(self.attributes["headers"]))

        # default settings
        client.headers["user-agent"] = self.attributes["user-agent"]
        client.headers["content-type"] = "application/json"
        client.headers["authorization"] = TOKEN
        client.headers["x-twitter-active-user"] = "yes"
        client.headers["x-twitter-client-language"] = "en"

        if "ct0" in client.cookies:
            client.headers["x-csrf-token"] = client.cookies["ct0"]

        return client
