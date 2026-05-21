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


def _merge_legacy(base: dict, legacy) -> dict:
    # top-level wins, missing keys filled from legacy if it is a dict
    out = dict(base)
    if isinstance(legacy, dict):
        for k, v in legacy.items():
            out.setdefault(k, v)
    return out


def _flatten_user_v2(obj: dict) -> dict:
    flat = _merge_legacy(obj, obj.get("legacy"))
    rest_id = obj.get("rest_id") or flat.get("rest_id") or flat.get("id_str")
    flat["rest_id"] = rest_id
    flat["id_str"] = str(rest_id) if rest_id is not None else flat.get("id_str", "")
    flat["id"] = int(rest_id) if rest_id is not None and str(rest_id).isdigit() else 0
    flat["legacy"] = None

    core = obj.get("core") or {}
    if isinstance(core, dict):
        for k in ("screen_name", "name", "created_at"):
            if k not in flat and k in core:
                flat[k] = core[k]

    if "profile_image_url_https" not in flat:
        avatar_url = (obj.get("avatar") or {}).get("image_url")
        if avatar_url:
            flat["profile_image_url_https"] = avatar_url

    if not isinstance(flat.get("location"), str):
        loc = (obj.get("location") or {}).get("location")
        if loc is not None:
            flat["location"] = loc

    if "protected" not in flat:
        prot = (obj.get("privacy") or {}).get("protected")
        if prot is not None:
            flat["protected"] = prot

    if "verified" not in flat:
        ver = (obj.get("verification") or {}).get("verified")
        if ver is not None:
            flat["verified"] = ver

    if "is_blue_verified" not in flat and "is_blue_verified" in obj:
        flat["is_blue_verified"] = obj["is_blue_verified"]

    if not flat.get("description"):
        bio = (obj.get("profile_bio") or {}).get("description")
        if bio is not None:
            flat["description"] = bio

    flat.setdefault("description", "")
    flat.setdefault("location", "")
    flat.setdefault("followers_count", 0)
    flat.setdefault("friends_count", 0)
    flat.setdefault("statuses_count", 0)
    flat.setdefault("favourites_count", 0)
    flat.setdefault("listed_count", 0)
    flat.setdefault("media_count", 0)
    flat.setdefault("profile_image_url_https", "")
    flat.setdefault("entities", {})
    flat.setdefault("pinned_tweet_ids_str", [])
    return flat


def _flatten_tweet_v2(obj: dict) -> dict:
    flat = _merge_legacy(obj, obj.get("legacy"))
    rest_id = obj.get("rest_id") or flat.get("rest_id") or flat.get("id_str")
    flat["rest_id"] = rest_id
    flat["id_str"] = str(rest_id) if rest_id is not None else flat.get("id_str", "")
    flat["id"] = int(rest_id) if rest_id is not None and str(rest_id).isdigit() else 0
    flat["legacy"] = None
    if "source" not in flat and "source" in obj:
        flat["source"] = obj["source"]
    flat.setdefault("full_text", "")
    flat.setdefault("lang", "")
    flat.setdefault("reply_count", 0)
    flat.setdefault("retweet_count", 0)
    flat.setdefault("favorite_count", 0)
    flat.setdefault("quote_count", 0)
    flat.setdefault("bookmark_count", 0)
    flat.setdefault("entities", {})
    flat.setdefault("conversation_id_str", flat["id_str"])
    return flat


def to_old_obj(obj: dict):
    # Since 2026-05 X serves Tweet/User with legacy=null. Tweet fields moved
    # to the top level; User fields are split between top-level and the
    # sub-objects core/avatar/location/privacy/verification/profile_bio.
    # Always rebuild a flat dict; works on the old schema too.
    if not isinstance(obj, dict):
        return obj
    if obj.get("__typename") == "User":
        return _flatten_user_v2(obj)
    return _flatten_tweet_v2(obj)


def to_old_rep(obj: dict) -> dict[str, dict]:
    tmp = get_typed_object(obj, defaultdict(list))

    # "legacy" in x still matches under the new schema: the key is present
    # with value None, so membership tests keep working.
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
            res = [x.strip() for x in val.split(";")]
            res = [x.split("=", 1) for x in res if "=" in x]
            if not res:
                raise ValueError(f"Invalid cookie value: {val}")
            return {x[0]: x[1] for x in res}
    except Exception:
        pass

    raise ValueError(f"Invalid cookie value: {val}")


def parse_proxy(proxy: str | None) -> str | None:
    if not proxy:
        return None
    if "://" in proxy:
        return proxy
    if "@" in proxy:
        # user:pass@host:port — missing scheme
        return f"http://{proxy}"
    parts = proxy.split(":")
    if len(parts) == 2:
        # host:port
        return f"http://{parts[0]}:{parts[1]}"
    if len(parts) == 4:
        # host:port:user:pass
        host, port, user, password = parts
        return f"http://{user}:{password}@{host}:{port}"
    return proxy


def get_env_bool(key: str, default_val: bool = False) -> bool:
    val = os.getenv(key)
    if val is None:
        return default_val
    return val.lower() in ("1", "true", "yes")
