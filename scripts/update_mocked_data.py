#!/usr/bin/env python3
"""
Usage:
  uv run scripts/update_mocked_data.py           # skip files updated within last 7 days
  uv run scripts/update_mocked_data.py --force   # update all regardless of age
  uv run scripts/update_mocked_data.py --ttl 1   # custom TTL in days
"""

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from twscrape import API, AccountsPool
from twscrape.logger import set_log_level

OUT = Path("tests/mocked-data")
META = OUT / ".meta.json"
DEFAULT_TTL_DAYS = 7


def load_meta() -> dict:
    if META.exists():
        return json.loads(META.read_text())
    return {}


def save_meta(meta: dict):
    META.write_text(json.dumps(meta, indent=2))


COMMANDS = [
    ("user_by_login", lambda api: api.user_by_login_raw("xdevelopers")),
    ("following", lambda api: _first(api.following_raw(2244994945, limit=10))),
    ("followers", lambda api: _first(api.followers_raw(2244994945, limit=10))),
    ("verified_followers", lambda api: _first(api.verified_followers_raw(2244994945, limit=10))),
    ("subscriptions", lambda api: _first(api.subscriptions_raw(58579942, limit=10))),
    ("tweet_details", lambda api: api.tweet_details_raw(1649191520250245121)),
    ("tweet_replies", lambda api: _first(api.tweet_replies_raw(1649191520250245121, limit=1))),
    ("retweeters", lambda api: _first(api.retweeters_raw(1649191520250245121, limit=10))),
    ("user_tweets", lambda api: _first(api.user_tweets_raw(2244994945, limit=10))),
    (
        "user_tweets_and_replies",
        lambda api: _first(api.user_tweets_and_replies_raw(2244994945, limit=10)),
    ),
    ("user_media", lambda api: _first(api.user_media_raw(2244994945, limit=10))),
    ("search", lambda api: _first(api.search_raw("tesla lang:en", limit=5))),
    ("list_timeline", lambda api: _first(api.list_timeline_raw(1494877848087187461, limit=10))),
    ("trends", lambda api: _first(api.trends_raw("sport"))),
]

console = Console()


async def _first(gen):
    async for x in gen:
        return x
    return None


def is_stale(name: str, meta: dict, ttl_days: int) -> bool:
    path = OUT / f"raw_{name}.json"
    if not path.exists() or name not in meta:
        return True
    return (time.time() - meta[name]) > ttl_days * 86400


def print_table(meta: dict, ttl_days: int):
    table = Table(show_lines=False, box=None, pad_edge=False)
    table.add_column("name", style="bold", min_width=26)
    table.add_column("updated at", justify="right", min_width=16)
    table.add_column("next update in", justify="right", min_width=14)
    table.add_column("", justify="center")

    for name, _ in COMMANDS:
        path = OUT / f"raw_{name}.json"
        if not path.exists() or name not in meta:
            table.add_row(name, "—", "—", "[red]missing[/red]")
            continue

        fetched_at = meta[name]
        updated_at = datetime.fromtimestamp(fetched_at).strftime("%Y-%m-%d %H:%M")
        due_days = ttl_days - (time.time() - fetched_at) / 86400

        if due_days < 0:
            next_in = f"{abs(due_days):.1f}d overdue"
            status = "[red]stale[/red]"
            next_style = "red"
        elif due_days < 1:
            next_in = f"{due_days * 24:.0f}h"
            status = "[yellow]soon[/yellow]"
            next_style = "yellow"
        else:
            next_in = f"{due_days:.1f}d"
            status = "[green]ok[/green]"
            next_style = "green"

        table.add_row(name, updated_at, f"[{next_style}]{next_in}[/{next_style}]", status)

    console.print(table)


async def main() -> int:
    force = "--force" in sys.argv
    ttl = DEFAULT_TTL_DAYS
    if "--ttl" in sys.argv:
        ttl = int(sys.argv[sys.argv.index("--ttl") + 1])

    set_log_level("WARNING")
    OUT.mkdir(parents=True, exist_ok=True)
    meta = load_meta()

    print_table(meta, ttl)

    to_update = [(n, fn) for n, fn in COMMANDS if force or is_stale(n, meta, ttl)]
    if not to_update:
        console.print("\n[green]All files are up to date.[/green]")
        return 0

    console.print()
    pool = AccountsPool()
    api = API(pool, debug=True)

    ok, fail = 0, 0
    for name, fn in to_update:
        outfile = OUT / f"raw_{name}.json"
        try:
            rep = await fn(api)
            if rep is None:
                console.print(f"[red]FAIL[/red]  {name}  (check logs above)")
                fail += 1
                continue
            with open(outfile, "w") as fp:
                json.dump(rep.json(), fp, indent=2)
            meta[name] = time.time()
            save_meta(meta)
            console.print(f"[green]OK[/green]    {name}")
            ok += 1
        except Exception as e:
            console.print(f"[red]FAIL[/red]  {name}  →  {type(e).__name__}: {e}")
            fail += 1

    skipped = len(COMMANDS) - len(to_update)
    console.print(f"\n{ok} updated, {skipped} skipped, {fail} failed")

    if ok:
        console.print()
        print_table(meta, ttl)

    return 1 if fail else 0


sys.exit(asyncio.run(main()))
