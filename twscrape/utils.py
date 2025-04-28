import base64
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, TypeVar

T = TypeVar("T")


class utc:
    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def from_iso(iso: str) -> datetime:
        return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)

    @staticmethod
    def ts() -> int:
        return int(utc.now().timestamp())


async def gather(gen: AsyncGenerator[T, None]) -> list[T]:
    items = []
    async for x in gen:
        items.append(x)
    return items


def encode_params(obj: dict):
    res = {}
    for k, v in obj.items():
        if isinstance(v, dict):
            v = {a: b for a, b in v.items() if b is not None}
            v = json.dumps(v, separators=(",", ":"))

        res[k] = str(v)

    return res


def get_or(obj: dict, key: str, default_value: T = None) -> Any | T:
    for part in key.split("."):
        if part not in obj:
            return default_value
        obj = obj[part]
    return obj


def int_or(obj: dict, key: str, default_value: int | None = None):
    try:
        val = get_or(obj, key)
        return int(val) if val is not None else default_value
    except Exception:
        return default_value


# https://stackoverflow.com/a/43184871
def get_by_path(obj: dict, key: str, default=None):
    stack = [iter(obj.items())]
    while stack:
        for k, v in stack[-1]:
            if k == key:
                return v
            elif isinstance(v, dict):
                stack.append(iter(v.items()))
                break
            elif isinstance(v, list):
                stack.append(iter(enumerate(v)))
                break
        else:
            stack.pop()
    return default


def find_item(lst: list[T], fn: Callable[[T], bool]) -> T | None:
    for item in lst:
        if fn(item):
            return item
    return None


def find_or_fail(lst: list[T], fn: Callable[[T], bool]) -> T:
    item = find_item(lst, fn)
    if item is None:
        raise ValueError()
    return item


def find_obj(obj: dict, fn: Callable[[dict], bool]) -> Any | None:
    if not isinstance(obj, dict):
        return None

    if fn(obj):
        return obj

    for _, v in obj.items():
        if isinstance(v, dict):
            if res := find_obj(v, fn):
                return res
        elif isinstance(v, list):
            for x in v:
                if res := find_obj(x, fn):
                    return res

    return None


def get_typed_object(obj: dict, res: defaultdict[str, list]):
    obj_type = obj.get("__typename", None)
    if obj_type is not None:
        res[obj_type].append(obj)

    for _, v in obj.items():
        if isinstance(v, dict):
            get_typed_object(v, res)
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, dict):
                    get_typed_object(x, res)

    return res


def to_old_obj(obj: dict):
    return {
        **obj,
        **obj["legacy"],
        "id_str": str(obj["rest_id"]),
        "id": int(obj["rest_id"]),
        "legacy": None,
    }


def to_old_rep(obj: dict) -> dict[str, dict]:
    tmp = get_typed_object(obj, defaultdict(list))

    tw1 = [x for x in tmp.get("Tweet", []) if "legacy" in x]
    tw1 = {str(x["rest_id"]): to_old_obj(x) for x in tw1}

    # https://github.com/vladkens/twscrape/issues/53
    tw2 = [x["tweet"] for x in tmp.get("TweetWithVisibilityResults", []) if "legacy" in x["tweet"]]
    tw2 = {str(x["rest_id"]): to_old_obj(x) for x in tw2}

    users = [x for x in tmp.get("User", []) if "legacy" in x and "id" in x]
    users = {str(x["rest_id"]): to_old_obj(x) for x in users}

    trends = [x for x in tmp.get("TimelineTrend", [])]
    trends = {x["name"]: x for x in trends}

    return {"tweets": {**tw1, **tw2}, "users": users, "trends": trends}


def print_table(rows: list[dict], hr_after=False):
    if not rows:
        return

    def prt(x):
        if isinstance(x, str):
            return x

        if isinstance(x, int):
            return f"{x:,}"

        if isinstance(x, datetime):
            return x.isoformat().split("+")[0].replace("T", " ")

        return str(x)

    keys = list(rows[0].keys())
    rows = [{k: k for k in keys}, *[{k: prt(x.get(k, "")) for k in keys} for x in rows]]
    colw = [max(len(x[k]) for x in rows) + 1 for k in keys]

    lines = []
    for row in rows:
        line = [f"{row[k]:<{colw[i]}}" for i, k in enumerate(keys)]
        lines.append(" ".join(line))

    max_len = max(len(x) for x in lines)
    # lines.insert(1, "─" * max_len)
    # lines.insert(0, "─" * max_len)
    print("\n".join(lines))
    if hr_after:
        print("-" * max_len)


def parse_cookies(val: str) -> dict[str, str]:
    try:
        val = base64.b64decode(val).decode()
    except Exception:
        pass

    try:
        try:
            res = json.loads(val)
            if isinstance(res, dict) and "cookies" in res:
                res = res["cookies"]

            if isinstance(res, list):
                return {x["name"]: x["value"] for x in res}
            if isinstance(res, dict):
                return res
        except json.JSONDecodeError:
            res = val.split("; ")
            res = [x.split("=") for x in res]
            return {x[0]: x[1] for x in res}
    except Exception:
        pass

    raise ValueError(f"Invalid cookie value: {val}")


def get_env_bool(key: str, default_val: bool = False) -> bool:
    val = os.getenv(key)
    if val is None:
        return default_val
    return val.lower() in ("1", "true", "yes")
