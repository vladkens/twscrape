import asyncio
import email as emaillib
import imaplib
import time
from datetime import datetime

from .logger import logger

MAX_WAIT_SEC = 30


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

                msg_time = datetime.strptime(msg.get("Date", ""), "%a, %d %b %Y %H:%M:%S %z")
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
        start_time, was_count = time.time(), 0
        while True:
            _, rep = imap.select("INBOX")
            now_count = int(rep[0].decode("utf-8")) if len(rep) > 0 and rep[0] is not None else 0
            if now_count > was_count:
                code = _wait_email_code(imap, now_count, min_t)
                if code is not None:
                    return code

            logger.info(f"Waiting for confirmation code for {email}, msg_count: {now_count}")
            if MAX_WAIT_SEC < time.time() - start_time:
                logger.info(f"Timeout waiting for confirmation code for {email}")
                raise EmailCodeTimeoutError()
            await asyncio.sleep(5)
    except Exception as e:
        imap.select("INBOX")
        imap.close()
        logger.error(f"Error getting confirmation code for {email}: {e}")
        raise e


async def imap_login(email: str, password: str):
    domain = _get_imap_domain(email)
    imap = imaplib.IMAP4_SSL(domain)

    try:
        imap.login(email, password)
    except imaplib.IMAP4.error as e:
        logger.error(f"Error logging into {email} on {domain}: {e}")
        imap.select("INBOX")
        imap.close()
        raise EmailLoginError() from e

    return imap
