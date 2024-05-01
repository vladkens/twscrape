import asyncio
import email as emaillib
import imaplib
import os
import time
from datetime import datetime

from .logger import logger

TWS_WAIT_EMAIL_CODE = [os.getenv("TWS_WAIT_EMAIL_CODE"), os.getenv("LOGIN_CODE_TIMEOUT"), 30]
TWS_WAIT_EMAIL_CODE = [int(x) for x in TWS_WAIT_EMAIL_CODE if x is not None][0]


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


def _wait_latest_email_code(imap: imaplib.IMAP4_SSL, count: int) -> str | None:
    for i in range(count, 0, -1):
        _, rep = imap.fetch(str(i), "(RFC822)")
        for x in rep:
            if isinstance(x, tuple):
                msg = emaillib.message_from_bytes(x[1])

                msg_from = str(msg.get("From", "")).lower()
                msg_subj = str(msg.get("Subject", "")).lower()
                logger.info(f"({i} of {count}) {msg_from} - {msg_subj}")

                if "info@x.com" in msg_from and "confirmation code is" in msg_subj:
                    return msg_subj.split()[-1].strip()

    return None


async def imap_get_email_code(imap: imaplib.IMAP4_SSL, email: str) -> str:
    try:
        logger.info(f"Waiting for confirmation code for {email}...")
        start_time = time.time()
        
        while True:
            _, rep = imap.select("INBOX")
            msg_count = int(rep[0].decode("utf-8")) if len(rep) > 0 and rep[0] is not None else 0
            code = _wait_latest_email_code(imap, msg_count)
            
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
