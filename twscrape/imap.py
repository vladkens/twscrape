import asyncio
import email as emaillib
import imaplib
import os
import time
from datetime import datetime

from .logger import logger

EMAIL_CODE_TIMEOUT = int(os.getenv("TWS_WAIT_EMAIL_CODE")) or 30
LOGIN_CODE_TIMEOUT = int(os.getenv("LOGIN_CODE_TIMEOUT")) or 10

class EmailLoginError(Exception):
    def __init__(self, message="Email login error"):
        self.message = message
        super().__init__(self.message)

class EmailCodeTimeoutError(Exception):
    def __init__(self, message="Email code timeout"):
        self.message = message
        super().__init__(self.message)

EMAIL_TO_IMAP_MAPPING = {
    "yahoo.com": "imap.mail.yahoo.com",
    "icloud.com": "imap.mail.me.com",
    "outlook.com": "imap-mail.outlook.com",
    "hotmail.com": "imap-mail.outlook.com",
}

def add_imap_mapping(email_domain: str, imap_domain: str):
    EMAIL_TO_IMAP_MAPPING[email_domain] = imap_domain

def get_imap_domain(email: str) -> str:
    email_domain = email.split("@")[1]
    if email_domain in EMAIL_TO_IMAP_MAPPING:
        return EMAIL_TO_IMAP_MAPPING[email_domain]
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

async def _imap_get_email_code(imap: imaplib.IMAP4_SSL, email: str) -> str | None:
    try:
        logger.info(f"Waiting for confirmation code for {email}...")
        start_time = time.time()
        while True:
            _, rep = imap.select("INBOX")
            msg_count = int(rep[0].decode("utf-8")) if len(rep) > 0 and rep[0] is not None else 0
            code = _wait_latest_email_code(imap, msg_count)
            if code is not None:
                return code
            if EMAIL_CODE_TIMEOUT < time.time() - start_time:
                raise EmailCodeTimeoutError(f"Email code timeout ({EMAIL_CODE_TIMEOUT} sec)")
            await asyncio.sleep(5)
    except Exception as e:
        imap.select("INBOX")
        imap.close()
        raise e

async def imap_login(email: str, password: str):
    domain = get_imap_domain(email)
    imap = imaplib.IMAP4_SSL(domain)
    try:
        start_time = time.time()
        while True:
            try:
                imap.login(email, password)
                imap.select("INBOX", readonly=True)
                break
            except imaplib.IMAP4.error as e:
                if LOGIN_CODE_TIMEOUT < time.time() - start_time:
                    raise EmailLoginError(f"Login code timeout ({LOGIN_CODE_TIMEOUT} sec)")
                await asyncio.sleep(5)
    except imaplib.IMAP4.error as e:
        logger.error(f"Error logging into {email} on {domain}: {e}")
        raise EmailLoginError() from e
    return imap
