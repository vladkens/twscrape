import asyncio
import email as emaillib
import imaplib
import os
import time
from datetime import datetime

from .logger import logger


def env_int(key: str | list[str], default: int) -> int:
    key = [key] if isinstance(key, str) else key
    val = [os.getenv(k) for k in key]
    val = [int(x) for x in val if x is not None]
    return val[0] if val else default


TWS_WAIT_EMAIL_CODE = env_int(["TWS_WAIT_EMAIL_CODE", "LOGIN_CODE_TIMEOUT"], 30)


class EmailLoginError(Exception):
    def __init__(self, message="Email login error"):
        self.message = message
        super().__init__(self.message)


class EmailCodeTimeoutError(Exception):
    def __init__(self, message="Email code timeout"):
        self.message = message
        super().__init__(self.message)


IMAP_MAPPING: dict[str, str] = {
    "yahoo.com": "imap.mail.yahoo.com",
    "icloud.com": "imap.mail.me.com",
    "outlook.com": "imap-mail.outlook.com",
    "hotmail.com": "imap-mail.outlook.com",
}


def add_imap_mapping(email_domain: str, imap_domain: str):
    IMAP_MAPPING[email_domain] = imap_domain


def _get_imap_domain(email: str) -> str:
    email_domain = email.split("@")[1]
    if email_domain in IMAP_MAPPING:
        return IMAP_MAPPING[email_domain]
    return f"imap.{email_domain}"


def _wait_email_code(imap: imaplib.IMAP4_SSL, count: int, min_t: datetime | None) -> str | None:
    for i in range(count, 0, -1):
        _, rep = imap.fetch(str(i), "(RFC822)")
        for x in rep:
            if isinstance(x, tuple):
                msg = emaillib.message_from_bytes(x[1])

                # https://www.ietf.org/rfc/rfc9051.html#section-6.3.12-13
                msg_time = msg.get("Date", "").split("(")[0].strip()
                msg_time = datetime.strptime(msg_time, "%a, %d %b %Y %H:%M:%S %z")

                msg_from = str(msg.get("From", "")).lower()
                msg_subj = str(msg.get("Subject", "")).lower()
                logger.info(f"({i} of {count}) {msg_from} - {msg_time} - {msg_subj}")

                if min_t is not None and msg_time < min_t:
                    return None

                if "info@x.com" in msg_from and "confirmation code is" in msg_subj:
                    # eg. Your Twitter confirmation code is XXX
                    return msg_subj.split(" ")[-1].strip()

    return None


async def imap_get_email_code(
    imap: imaplib.IMAP4_SSL, email: str, min_t: datetime | None = None
) -> str:
    try:
        logger.info(f"Waiting for confirmation code for {email}...")
        start_time = time.time()
        while True:
            _, rep = imap.select("INBOX")
            msg_count = int(rep[0].decode("utf-8")) if len(rep) > 0 and rep[0] is not None else 0
            code = _wait_email_code(imap, msg_count, min_t)
            if code is not None:
                return code

            if TWS_WAIT_EMAIL_CODE < time.time() - start_time:
                raise EmailCodeTimeoutError(f"Email code timeout ({TWS_WAIT_EMAIL_CODE} sec)")

            await asyncio.sleep(5)
    except Exception as e:
        imap.select("INBOX")
        imap.close()
        raise e


async def imap_login(email: str, password: str):
    domain = _get_imap_domain(email)
    imap = imaplib.IMAP4_SSL(domain)

    try:
        imap.login(email, password)
        imap.select("INBOX", readonly=True)
    except imaplib.IMAP4.error as e:
        logger.error(f"Error logging into {email} on {domain}: {e}")
        raise EmailLoginError() from e

    return imap
