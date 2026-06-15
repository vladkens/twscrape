import functools
import os
import sys
import threading
import uuid
from collections import defaultdict
from contextvars import ContextVar
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Literal

import httpx
import machineid

APP_NAME = "twscrape"
POSTHOG_KEY = "phc_giRHYHo4460O5UPxySajdO9L4KDRsjSmNQACA7uG9px"
POSTHOG_BATCH_URL = "https://app.posthog.com/batch/"
_lock = threading.Lock()
_events: defaultdict[tuple[str, tuple[tuple[str, Any], ...]], int] = defaultdict(int)
_source: ContextVar[str] = ContextVar("telemetry_source", default="lib")
_session_id = str(uuid.uuid4())


def _app_version() -> str:
    try:
        return version(APP_NAME)
    except PackageNotFoundError:
        return "0.0.0"


@functools.cache
def _distinct_id() -> str:
    return machineid.hashed_id(APP_NAME)[:16]


def _properties(properties: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "$lib": APP_NAME,
        "$process_person_profile": False,
        "$session_id": _session_id,
        "app_version": _app_version(),
        "distinct_id": _distinct_id(),
        "platform": sys.platform,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        **(properties or {}),
    }


def _aggregate_properties(properties: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in properties.items() if k not in {"$session_id", "distinct_id"}}


def set_source(source: Literal["lib", "cli"]) -> None:
    _source.set(source)


def current_source() -> str:
    return _source.get()


def _is_disabled() -> bool:
    return os.getenv("TWS_TELEMETRY") == "0" or os.getenv("DO_NOT_TRACK") == "1"


def capture(event: str, properties: dict[str, Any] | None = None) -> None:
    if _is_disabled():
        return

    try:
        props = _properties(properties)
        key = (event, tuple(sorted(_aggregate_properties(props).items())))
        with _lock:
            _events[key] += 1
    except Exception:
        pass


def snapshot() -> list[dict[str, Any]]:
    with _lock:
        return [
            {"event": event, "properties": _properties(dict(properties)), "count": count}
            for (event, properties), count in _events.items()
        ]


async def flush() -> None:
    try:
        await _flush()
    except Exception:
        pass


async def _flush() -> None:
    if _is_disabled() or not POSTHOG_KEY:
        reset()
        return

    events = snapshot()
    if not events:
        return

    reset()

    ts = datetime.now(timezone.utc).isoformat()
    batch = [
        {
            "event": item["event"],
            "distinct_id": item["properties"]["distinct_id"],
            "timestamp": ts,
            "properties": {**item["properties"], "count": item["count"]},
        }
        for item in events
    ]

    async with httpx.AsyncClient() as client:
        await client.post(
            POSTHOG_BATCH_URL,
            json={"api_key": POSTHOG_KEY, "batch": batch},
            timeout=5,
        )


def reset() -> None:
    _source.set("lib")
    with _lock:
        _events.clear()
