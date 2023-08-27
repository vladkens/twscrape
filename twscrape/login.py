from datetime import datetime, timedelta, timezone

from httpx import AsyncClient, HTTPStatusError, Response

from .account import Account
from .constants import LOGIN_URL
from .imap import imap_get_email_code, imap_login
from .logger import logger
from .utils import raise_for_status


async def get_guest_token(client: AsyncClient):
    rep = await client.post("https://api.twitter.com/1.1/guest/activate.json")
    raise_for_status(rep, "guest_token")
    return rep.json()["guest_token"]


async def login_initiate(client: AsyncClient) -> Response:
    payload = {
        "input_flow_data": {
            "flow_context": {"debug_overrides": {}, "start_location": {"location": "unknown"}}
        },
        "subtask_versions": {},
    }

    rep = await client.post(LOGIN_URL, params={"flow_name": "login"}, json=payload)
    raise_for_status(rep, "login_initiate")
    return rep


async def login_instrumentation(client: AsyncClient, acc: Account, prev: dict) -> Response:
    payload = {
        "flow_token": prev["flow_token"],
        "subtask_inputs": [
            {
                "subtask_id": "LoginJsInstrumentationSubtask",
                "js_instrumentation": {"response": "{}", "link": "next_link"},
            }
        ],
    }

    rep = await client.post(LOGIN_URL, json=payload)
    raise_for_status(rep, "login_instrumentation")
    return rep


async def login_enter_username(client: AsyncClient, acc: Account, prev: dict) -> Response:
    payload = {
        "flow_token": prev["flow_token"],
        "subtask_inputs": [
            {
                "subtask_id": "LoginEnterUserIdentifierSSO",
                "settings_list": {
                    "setting_responses": [
                        {
                            "key": "user_identifier",
                            "response_data": {"text_data": {"result": acc.username}},
                        }
                    ],
                    "link": "next_link",
                },
            }
        ],
    }

    rep = await client.post(LOGIN_URL, json=payload)
    raise_for_status(rep, "login_username")
    return rep


async def login_enter_password(client: AsyncClient, acc: Account, prev: dict) -> Response:
    payload = {
        "flow_token": prev["flow_token"],
        "subtask_inputs": [
            {
                "subtask_id": "LoginEnterPassword",
                "enter_password": {"password": acc.password, "link": "next_link"},
            }
        ],
    }

    rep = await client.post(LOGIN_URL, json=payload)
    raise_for_status(rep, "login_password")
    return rep


async def login_duplication_check(client: AsyncClient, acc: Account, prev: dict) -> Response:
    payload = {
        "flow_token": prev["flow_token"],
        "subtask_inputs": [
            {
                "subtask_id": "AccountDuplicationCheck",
                "check_logged_in_account": {"link": "AccountDuplicationCheck_false"},
            }
        ],
    }

    rep = await client.post(LOGIN_URL, json=payload)
    raise_for_status(rep, "login_duplication_check")
    return rep


async def login_confirm_email(client: AsyncClient, acc: Account, prev: dict, imap) -> Response:
    payload = {
        "flow_token": prev["flow_token"],
        "subtask_inputs": [
            {
                "subtask_id": "LoginAcid",
                "enter_text": {"text": acc.email, "link": "next_link"},
            }
        ],
    }

    rep = await client.post(LOGIN_URL, json=payload)
    raise_for_status(rep, "login_confirm_email")
    return rep


async def login_confirm_email_code(client: AsyncClient, acc: Account, prev: dict, imap):
    if not imap:
        imap = await imap_login(acc.email, acc.email_password)

    now_time = datetime.now(timezone.utc) - timedelta(seconds=30)
    value = await imap_get_email_code(imap, acc.email, now_time)

    payload = {
        "flow_token": prev["flow_token"],
        "subtask_inputs": [
            {
                "subtask_id": "LoginAcid",
                "enter_text": {"text": value, "link": "next_link"},
            }
        ],
    }

    rep = await client.post(LOGIN_URL, json=payload)
    raise_for_status(rep, "login_confirm_email")
    return rep


async def login_success(client: AsyncClient, acc: Account, prev: dict) -> Response:
    payload = {
        "flow_token": prev["flow_token"],
        "subtask_inputs": [],
    }

    rep = await client.post(LOGIN_URL, json=payload)
    raise_for_status(rep, "login_success")
    return rep


async def next_login_task(client: AsyncClient, acc: Account, rep: Response, imap):
    ct0 = client.cookies.get("ct0", None)
    if ct0:
        client.headers["x-csrf-token"] = ct0
        client.headers["x-twitter-auth-type"] = "OAuth2Session"

    prev = rep.json()
    assert "flow_token" in prev, f"flow_token not in {rep.text}"

    for x in prev["subtasks"]:
        task_id = x["subtask_id"]

        try:
            if task_id == "LoginSuccessSubtask":
                return await login_success(client, acc, prev)
            if task_id == "LoginAcid":
                is_code = x["enter_text"]["hint_text"].lower() == "confirmation code"
                fn = login_confirm_email_code if is_code else login_confirm_email
                return await fn(client, acc, prev, imap)
            if task_id == "AccountDuplicationCheck":
                return await login_duplication_check(client, acc, prev)
            if task_id == "LoginEnterPassword":
                return await login_enter_password(client, acc, prev)
            if task_id == "LoginEnterUserIdentifierSSO":
                return await login_enter_username(client, acc, prev)
            if task_id == "LoginJsInstrumentationSubtask":
                return await login_instrumentation(client, acc, prev)
        except Exception as e:
            acc.error_msg = f"login_step={task_id} err={e}"
            logger.error(f"Error in {task_id}: {e}")
            raise e

    return None


async def login(acc: Account, email_first=False) -> Account:
    log_id = f"{acc.username} - {acc.email}"
    if acc.active:
        logger.info(f"account already active {log_id}")
        return acc

    if email_first:
        imap = await imap_login(acc.email, acc.email_password)
    else:
        imap = None

    client = acc.make_client()
    guest_token = await get_guest_token(client)
    client.headers["x-guest-token"] = guest_token

    rep = await login_initiate(client)
    while True:
        if not rep:
            break

        try:
            rep = await next_login_task(client, acc, rep, imap)
        except HTTPStatusError as e:
            if e.response.status_code == 403:
                logger.error(f"403 error {log_id}")
                return acc

    client.headers["x-csrf-token"] = client.cookies["ct0"]
    client.headers["x-twitter-auth-type"] = "OAuth2Session"

    acc.active = True
    acc.headers = {k: v for k, v in client.headers.items()}
    acc.cookies = {k: v for k, v in client.cookies.items()}
    return acc
