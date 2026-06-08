#!/usr/bin/env python3
"""
Usage:
  uv run scripts/update_mocked_data.py           # skip files updated within last 7 days
  uv run scripts/update_mocked_data.py --force   # update all regardless of age
"""

import asyncio
import inspect
import json
import os
import re
import sys
import time
from datetime import datetime
from typing import TypeAlias

from twscrape import API, AccountsPool
from twscrape import api as api_mod
from twscrape.logger import set_log_level

OUT = "tests/mocked-data"
META = f"{OUT}/__meta.json"
DEFAULT_TTL_DAYS = 7

MetaEntry: TypeAlias = tuple[int, str]  # (fetched_at_unix, gql_op_id)


def load_meta() -> dict[str, MetaEntry]:
    try:
        if not os.path.exists(META):
            return {}
        with open(META, encoding="utf-8") as fp:
            raw = json.load(fp)
        result: dict[str, MetaEntry] = {}
        for k, v in raw.items():
            if isinstance(v, list) and len(v) == 2:
                result[k] = (int(v[0]), str(v[1]))
        return result
    except Exception:
        return {}


def save_meta(meta: dict[str, MetaEntry]):
    with open(META, "w", encoding="utf-8") as fp:
        json.dump({k: list(v) for k, v in sorted(meta.items())}, fp, indent=2)


_UID = 2244994945  # https://x.com/xdevelopers
_TID = 1649191520250245121  # https://x.com/i/status/1649191520250245121
_CID = 1501272736215322629  # https://x.com/i/communities/1501272736215322629
_LID = 1494877848087187461  # https://x.com/i/lists/1494877848087187461


COMMANDS = [
    ("user_by_login", lambda api: api.user_by_login_raw("xdevelopers")),
    ("user_about", lambda api: api.user_about_raw("xdevelopers")),
    ("following", lambda api: _first(api.following_raw(_UID, limit=10))),
    ("followers", lambda api: _first(api.followers_raw(_UID, limit=10))),
    ("verified_followers", lambda api: _first(api.verified_followers_raw(_UID, limit=10))),
    ("subscriptions", lambda api: _first(api.subscriptions_raw(58579942, limit=10))),
    ("tweet_details", lambda api: api.tweet_details_raw(_TID)),
    ("tweet_replies", lambda api: _first(api.tweet_replies_raw(_TID, limit=1))),
    ("tweet_thread", lambda api: _first(api.tweet_thread_raw(_TID, limit=10))),
    ("retweeters", lambda api: _first(api.retweeters_raw(_TID, limit=10))),
    ("user_tweets", lambda api: _first(api.user_tweets_raw(_UID, limit=10))),
    (
        "user_tweets_and_replies",
        lambda api: _first(api.user_tweets_and_replies_raw(_UID, limit=10)),
    ),
    ("user_media", lambda api: _first(api.user_media_raw(_UID, limit=10))),
    ("search", lambda api: _first(api.search_raw("tesla lang:en", limit=5))),
    ("list_timeline", lambda api: _first(api.list_timeline_raw(_LID, limit=10))),
    ("list_members", lambda api: _first(api.list_members_raw(_LID, limit=10))),
    ("trends", lambda api: _first(api.trends_raw("sport"))),
    ("community_info", lambda api: api.community_info_raw(_CID)),
    ("community_members", lambda api: _first(api.community_members_raw(_CID, limit=10))),
    ("community_moderators", lambda api: _first(api.community_moderators_raw(_CID, limit=10))),
    ("community_tweets", lambda api: _first(api.community_tweets_raw(_CID, limit=10))),
]


async def _first(gen):
    async for x in gen:
        return x
    return None


def get_ops() -> dict[str, str]:
    # For each command, extract the GQL operation ID used by its *_raw method.
    # We do this by reading the method source and finding the single OP_* constant reference.
    # This lets us detect when an op ID changes in api.py and mark the cached file as stale.
    res = {}
    missing = []
    for name, _ in COMMANDS:
        method = f"{name}_raw"
        fn = getattr(API, method, None)
        if fn is None:
            missing.append(method)
            continue
        src = inspect.getsource(fn)
        names = set(re.findall(r"\bOP_\w+\b", src))
        if len(names) != 1:  # require exactly one OP_* per method
            missing.append(method)
            continue
        value = getattr(api_mod, names.pop(), None)
        if not isinstance(value, str):
            missing.append(method)
            continue
        res[method] = value

    if missing:
        names = ", ".join(missing)
        raise ValueError(f"Expected exactly one OP_* in: {names}")

    return res


def is_stale(name: str, op: str, meta: dict, ttl_days: int) -> bool:
    return get_state(name, op, meta, ttl_days) != "ok"


def get_state(name: str, op: str, meta: dict[str, MetaEntry], ttl_days: int) -> str:
    if not os.path.exists(f"{OUT}/raw_{name}.json"):
        return "missing"
    item = meta.get(name)
    if item is None:
        return "op"
    if item[1] != op:
        return "op"
    if (time.time() - item[0]) > ttl_days * 86400:
        return "ttl"
    return "ok"


def print_table(meta: dict[str, MetaEntry], ops: dict[str, str], ttl_days: int):
    print(f"{'name':<28}  {'updated at':>16}  {'next in':>12}  status")
    for name, _ in COMMANDS:
        op = ops[f"{name}_raw"]
        state = get_state(name, op, meta, ttl_days)
        item = meta.get(name)

        if state == "missing":
            print(f"{name:<28}  {'—':>16}  {'—':>12}  missing")
            continue

        if state == "op":
            updated_at = (
                datetime.fromtimestamp(item[0]).strftime("%Y-%m-%d %H:%M") if item else "—"
            )
            print(f"{name:<28}  {updated_at:>16}  {'op changed':>12}  stale")
            continue

        assert item is not None
        updated_at = datetime.fromtimestamp(item[0]).strftime("%Y-%m-%d %H:%M")
        due_days = ttl_days - (time.time() - item[0]) / 86400

        if due_days < 0:
            next_in, status = f"{abs(due_days):.1f}d overdue", "stale"
        elif due_days < 1:
            next_in, status = f"{due_days * 24:.0f}h", "soon"
        else:
            next_in, status = f"{due_days:.1f}d", "ok"

        print(f"{name:<28}  {updated_at:>16}  {next_in:>12}  {status}")


async def main() -> int:
    force = "--force" in sys.argv
    ttl = DEFAULT_TTL_DAYS

    set_log_level("WARNING")
    os.makedirs(OUT, exist_ok=True)
    meta = load_meta()
    ops = get_ops()

    print_table(meta, ops, ttl)

    to_update = [
        (n, f"{n}_raw", fn)
        for n, fn in COMMANDS
        if force or is_stale(n, ops[f"{n}_raw"], meta, ttl)
    ]
    if not to_update:
        print("\nAll files are up to date.")
        return 0

    print()
    pool = AccountsPool()
    api = API(pool, debug=True)

    ok, fail = 0, 0
    for name, method, fn in to_update:
        outfile = f"{OUT}/raw_{name}.json"
        try:
            rep = await fn(api)
            if rep is None:
                print(f"fail  {name}  (no response)")
                fail += 1
                continue
            with open(outfile, "w", encoding="utf-8") as fp:
                json.dump(rep.json(), fp, indent=2)
            meta[name] = (int(time.time()), ops[method])
            save_meta(meta)
            print(f"ok    {name}")
            ok += 1
        except Exception as e:
            print(f"fail  {name}  ({type(e).__name__}: {e})")
            fail += 1

    skipped = len(COMMANDS) - len(to_update)
    print(f"\n{ok} updated, {skipped} skipped, {fail} failed")

    return 1 if fail else 0


try:
    sys.exit(asyncio.run(main()))
except KeyboardInterrupt:
    print("\nInterrupted.")
    sys.exit(130)
