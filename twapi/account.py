import json
import os
from datetime import datetime, timedelta, timezone
from enum import Enum

from fake_useragent import UserAgent
from httpx import AsyncClient, HTTPStatusError, Response
from loguru import logger

from .constants import LOGIN_URL, TOKEN
from .imap import get_email_code
from .utils import raise_for_status


class Status(str, Enum):
    NEW = "new"
    ACTIVE = "active"
    LOGIN_ERROR = "login_error"


class Account:
    BASE_DIR = "accounts"

    @classmethod
    def load(cls, filepath: str):
        try:
            with open(filepath) as f:
                data = json.load(f)
            return cls(**data)
        except Exception as e:
            logger.error(f"Failed to load account {filepath}: {e}")
            return None

    def __init__(
        self,
        username: str,
        password: str,
        email: str,
        email_password: str,
        user_agent: str | None = None,
        proxy: str | None = None,
        headers={},
        cookies={},
        limits={},
        status=Status.NEW,
    ):
        self.username = username
        self.password = password
        self.email = email
        self.email_password = email_password
        self.user_agent = user_agent or UserAgent().safari
        self.proxy = proxy or None

        self.client = AsyncClient(proxies=self.proxy)
        self.client.cookies.update(cookies)
        self.client.headers.update(headers)

        self.client.headers["user-agent"] = self.user_agent
        self.client.headers["content-type"] = "application/json"
        self.client.headers["authorization"] = TOKEN
        self.client.headers["x-twitter-active-user"] = "yes"
        self.client.headers["x-twitter-client-language"] = "en"

        self.status: Status = status
        self.locked: dict[str, bool] = {}
        self.limits: dict[str, datetime] = {
            k: datetime.fromisoformat(v) for k, v in limits.items()
        }

    def dump(self):
        return {
            "username": self.username,
            "password": self.password,
            "email": self.email,
            "email_password": self.email_password,
            "user_agent": self.user_agent,
            "proxy": self.proxy,
            "cookies": {k: v for k, v in self.client.cookies.items()},
            "headers": {k: v for k, v in self.client.headers.items()},
            "limits": {k: v.isoformat() for k, v in self.limits.items()},
            "status": self.status,
        }

    def save(self):
        os.makedirs(self.BASE_DIR, exist_ok=True)
        data = self.dump()
        with open(f"{self.BASE_DIR}/{self.username}.json", "w") as f:
            json.dump(data, f, indent=2)

    def update_limit(self, queue: str, reset_ts: int):
        self.limits[queue] = datetime.fromtimestamp(reset_ts, tz=timezone.utc)
        self.save()

    def can_use(self, queue: str):
        if self.locked.get(queue, False) or self.status != Status.ACTIVE:
            return False

        limit = self.limits.get(queue)
        return not limit or limit <= datetime.now(timezone.utc)

    def lock(self, queue: str):
        self.locked[queue] = True

    def unlock(self, queue: str):
        self.locked[queue] = False

    async def login(self, fresh=False):
        log_id = f"{self.username} - {self.email}"
        if self.status != "new" and not fresh:
            logger.debug(f"logged in already {log_id}")
            return

        logger.debug(f"logging in {log_id}")

        guest_token = await self.get_guest_token()
        self.client.headers["x-guest-token"] = guest_token

        rep = await self.login_initiate()
        while True:
            try:
                if rep:
                    rep = await self.next_login_task(rep)
                else:
                    break
            except HTTPStatusError as e:
                if e.response.status_code == 403:
                    logger.error(f"403 error {log_id}")
                    self.status = Status.LOGIN_ERROR
                    self.save()
                    return

        self.client.headers["x-csrf-token"] = self.client.cookies["ct0"]
        self.client.headers["x-twitter-auth-type"] = "OAuth2Session"

        logger.info(f"logged in success {log_id}")
        self.status = Status.ACTIVE
        self.save()

    async def get_guest_token(self):
        rep = await self.client.post("https://api.twitter.com/1.1/guest/activate.json")
        raise_for_status(rep, "guest_token")
        return rep.json()["guest_token"]

    async def login_initiate(self) -> Response:
        payload = {
            "input_flow_data": {
                "flow_context": {"debug_overrides": {}, "start_location": {"location": "unknown"}}
            },
            "subtask_versions": {},
        }

        rep = await self.client.post(LOGIN_URL, params={"flow_name": "login"}, json=payload)
        raise_for_status(rep, "login_initiate")
        return rep

    async def next_login_task(self, rep: Response):
        ct0 = self.client.cookies.get("ct0", None)
        if ct0:
            self.client.headers["x-csrf-token"] = ct0
            self.client.headers["x-twitter-auth-type"] = "OAuth2Session"

        data = rep.json()
        assert "flow_token" in data, f"flow_token not in {rep.text}"
        # logger.debug(f"login tasks: {[x['subtask_id'] for x in data['subtasks']]}")

        for x in data["subtasks"]:
            task_id = x["subtask_id"]

            try:
                if task_id == "LoginSuccessSubtask":
                    return await self.login_success(data)
                if task_id == "LoginAcid":
                    is_code = x["enter_text"]["hint_text"].lower() == "confirmation code"
                    # logger.debug(f"is login code: {is_code}")
                    fn = self.login_confirm_email_code if is_code else self.login_confirm_email
                    return await fn(data)
                if task_id == "AccountDuplicationCheck":
                    return await self.login_duplication_check(data)
                if task_id == "LoginEnterPassword":
                    return await self.login_enter_password(data)
                if task_id == "LoginEnterUserIdentifierSSO":
                    return await self.login_enter_username(data)
                if task_id == "LoginJsInstrumentationSubtask":
                    return await self.login_instrumentation(data)
            except Exception as e:
                logger.error(f"Error in {task_id}: {e}")
                logger.error(e)

        return None

    async def login_instrumentation(self, prev: dict) -> Response:
        payload = {
            "flow_token": prev["flow_token"],
            "subtask_inputs": [
                {
                    "subtask_id": "LoginJsInstrumentationSubtask",
                    "js_instrumentation": {"response": "{}", "link": "next_link"},
                }
            ],
        }

        rep = await self.client.post(LOGIN_URL, json=payload)
        raise_for_status(rep, "login_instrumentation")
        return rep

    async def login_enter_username(self, prev: dict) -> Response:
        payload = {
            "flow_token": prev["flow_token"],
            "subtask_inputs": [
                {
                    "subtask_id": "LoginEnterUserIdentifierSSO",
                    "settings_list": {
                        "setting_responses": [
                            {
                                "key": "user_identifier",
                                "response_data": {"text_data": {"result": self.username}},
                            }
                        ],
                        "link": "next_link",
                    },
                }
            ],
        }

        rep = await self.client.post(LOGIN_URL, json=payload)
        raise_for_status(rep, "login_username")
        return rep

    async def login_enter_password(self, prev: dict) -> Response:
        payload = {
            "flow_token": prev["flow_token"],
            "subtask_inputs": [
                {
                    "subtask_id": "LoginEnterPassword",
                    "enter_password": {"password": self.password, "link": "next_link"},
                }
            ],
        }

        rep = await self.client.post(LOGIN_URL, json=payload)
        raise_for_status(rep, "login_password")
        return rep

    async def login_duplication_check(self, prev: dict) -> Response:
        payload = {
            "flow_token": prev["flow_token"],
            "subtask_inputs": [
                {
                    "subtask_id": "AccountDuplicationCheck",
                    "check_logged_in_account": {"link": "AccountDuplicationCheck_false"},
                }
            ],
        }

        rep = await self.client.post(LOGIN_URL, json=payload)
        raise_for_status(rep, "login_duplication_check")
        return rep

    async def login_confirm_email(self, prev: dict) -> Response:
        payload = {
            "flow_token": prev["flow_token"],
            "subtask_inputs": [
                {
                    "subtask_id": "LoginAcid",
                    "enter_text": {"text": self.email, "link": "next_link"},
                }
            ],
        }

        rep = await self.client.post(LOGIN_URL, json=payload)
        raise_for_status(rep, "login_confirm_email")
        return rep

    async def login_confirm_email_code(self, prev: dict):
        now_time = datetime.now(timezone.utc) - timedelta(seconds=30)
        value = await get_email_code(self.email, self.email_password, now_time)

        payload = {
            "flow_token": prev["flow_token"],
            "subtask_inputs": [
                {
                    "subtask_id": "LoginAcid",
                    "enter_text": {"text": value, "link": "next_link"},
                }
            ],
        }

        rep = await self.client.post(LOGIN_URL, json=payload)
        raise_for_status(rep, "login_confirm_email")
        return rep

    async def login_success(self, prev: dict) -> Response:
        payload = {
            "flow_token": prev["flow_token"],
            "subtask_inputs": [],
        }

        rep = await self.client.post(LOGIN_URL, json=payload)
        raise_for_status(rep, "login_success")
        return rep
