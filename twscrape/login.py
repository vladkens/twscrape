import asyncio
import imaplib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pyotp
from httpx import AsyncClient, Response

import httpx_oauth.oauth2 as oauth2
from .account import Account
from .imap import imap_get_email_code, imap_login
from .logger import logger
from .utils import utc

LOGIN_URL = "https://api.twitter.com/1.1/onboarding/task.json"


@dataclass
class LoginConfig:
    email_first: bool = False
    manual: bool = False


@dataclass
class TaskCtx:
    client: AsyncClient
    acc: Account
    cfg: LoginConfig
    prev: Any
    imap: None | imaplib.IMAP4_SSL


async def get_guest_token(client: AsyncClient) -> str:
    """Get a guest token from Twitter API."""
    rep = await client.post("https://api.twitter.com/1.1/guest/activate.json")
    rep.raise_for_status()
    return rep.json()["guest_token"]


# ... (other function definitions)

async def next_login_task(ctx: TaskCtx, rep: Response) -> Response | None:
    """Handle the next login task."""
    # ... (function body)


async def login(acc: Account, cfg: LoginConfig | None = None) -> Account:
    """Login to Twitter API with the given account."""
    log_id = f"{acc.username} - {acc.email}"
    if acc.active:
        logger.info(f"account already active {log_id}")
        return acc

    cfg, imap = cfg or LoginConfig(), None
    if cfg.email_first and not cfg.manual:
        imap = await imap_login(acc.email, acc.email_password)

    async with acc.make_client() as client:
        guest_token = await get_guest_token(client)
        client.headers["x-guest-token"] = guest_token

        rep = await login_initiate(client)
        ctx = TaskCtx(client, acc, cfg, None, imap)
        while True:
            try:
                rep = await next_login_task(ctx, rep)
                if not rep:
                    break
            except Exception as e:
                acc.error_msg = f"login_step={ctx.prev['subtask_id']} err={e}"
                break

        assert "ct0" in client.cookies, "ct0 not in cookies (most likely ip ban)"
        client.headers["x-csrf-token"] = client.cookies["ct0"]
        client.headers["x-twitter-auth-type"] = "OAuth2Session"

        acc.active = True
        acc.headers = {k: v for k, v in client.headers.items()}
        acc.cookies = {k: v for k, v in client.cookies.items()}
        return acc
