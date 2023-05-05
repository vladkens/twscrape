import asyncio
import email as emaillib
import imaplib
import time
from datetime import datetime

from .logger import logger

MAX_WAIT_SEC = 30


def get_imap_domain(email: str) -> str:
    return f"imap.{email.split('@')[1]}"


def search_email_code(imap: imaplib.IMAP4_SSL, count: int, min_t: datetime | None) -> str | None:
    for i in range(count, 0, -1):
        _, rep = imap.fetch(str(i), "(RFC822)")
        for x in rep:
            if isinstance(x, tuple):
                msg = emaillib.message_from_bytes(x[1])

                msg_time = datetime.strptime(msg.get("Date", ""), "%a, %d %b %Y %H:%M:%S %z")
                msg_from = str(msg.get("From", "")).lower()
                msg_subj = str(msg.get("Subject", "")).lower()
                logger.debug(f"({i} of {count}) {msg_from} - {msg_time} - {msg_subj}")

                if min_t is not None and msg_time < min_t:
                    return None

                if "info@twitter.com" in msg_from and "confirmation code is" in msg_subj:
                    # eg. Your Twitter confirmation code is XXX
                    return msg_subj.split(" ")[-1].strip()

    return None


async def get_email_code(email: str, password: str, min_t: datetime | None = None) -> str:
    domain = get_imap_domain(email)
    start_time = time.time()
    with imaplib.IMAP4_SSL(domain) as imap:
        imap.login(email, password)

        was_count = 0
        while True:
            _, rep = imap.select("INBOX")
            now_count = int(rep[0].decode("utf-8")) if len(rep) > 0 and rep[0] is not None else 0
            if now_count > was_count:
                code = search_email_code(imap, now_count, min_t)
                if code is not None:
                    return code

            logger.debug(f"Waiting for confirmation code for {email}, msg_count: {now_count}")
            if MAX_WAIT_SEC < time.time() - start_time:
                raise Exception(f"Timeout on getting confirmation code for {email}")
            await asyncio.sleep(5)
