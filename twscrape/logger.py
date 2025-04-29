import os
import sys
from typing import Literal, cast

from loguru import logger

_TLOGLEVEL = Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def _load_from_env() -> _TLOGLEVEL:
    env = os.getenv("TWS_LOG_LEVEL", "INFO").upper()
    if env not in ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        logger.warning(f"Invalid log level '{env}' in TWS_LOG_LEVEL. Defaulting to INFO.")
        return "INFO"

    return cast(_TLOGLEVEL, env)


_LOG_LEVEL: _TLOGLEVEL = _load_from_env()


def set_log_level(level: _TLOGLEVEL):
    global _LOG_LEVEL
    _LOG_LEVEL = level


def _filter(r):
    return r["level"].no >= logger.level(_LOG_LEVEL).no


logger.remove()
logger.add(sys.stderr, filter=_filter)
