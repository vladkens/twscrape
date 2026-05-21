#!/usr/bin/env python3
"""
Fetches current GraphQL operation IDs from Twitter's JS bundle
and updates them in twscrape/api.py.

Usage:
  uv run scripts/update_gql_ops.py          # dry run, show diff
  uv run scripts/update_gql_ops.py --apply  # write changes to api.py
"""

import asyncio
import re
import sys
from pathlib import Path

import httpx

from twscrape.xclid import get_scripts_list, get_tw_page_text, script_url

API_FILE = Path("twscrape/api.py")
CACHE_DIR = Path("/tmp/twscrape-ops")


def _is_relevant_script(url: str) -> bool:
    return "/i18n/" not in url and "/icons/" not in url and "react-syntax-highlighter" not in url


async def get_scripts() -> list[str]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(follow_redirects=True) as clt:
        text = await get_tw_page_text("https://x.com/elonmusk", clt)

    urls = list(get_scripts_list(text))
    v = text.split("/client-web/main.")[1].split(".")[0]
    urls.append(script_url("main", v))
    urls = [x for x in urls if _is_relevant_script(x)]

    force = "--force" in sys.argv
    sem = asyncio.Semaphore(10)

    async def fetch(clt: httpx.AsyncClient, i: int, url: str) -> str:
        cache_path = CACHE_DIR / url.split("/")[-1].split("?")[0]
        if cache_path.exists() and not force:
            print(f"  ({i:3d}/{len(urls):3d}) [cache] {url}")
            return cache_path.read_text()
        async with sem:
            print(f"  ({i:3d}/{len(urls):3d}) [fetch] {url}")
            rep = await clt.get(url)
            rep.raise_for_status()
            ct = rep.headers.get("content-type", "")
            if "javascript" not in ct:
                raise ValueError(f"Unexpected content-type '{ct}' for {url} — rate limited?")
            cache_path.write_text(rep.text)
            return rep.text

    async with httpx.AsyncClient(follow_redirects=True) as clt:
        scripts = await asyncio.gather(*[fetch(clt, i, url) for i, url in enumerate(urls, 1)])

    return list(scripts)


async def main():
    apply = "--apply" in sys.argv

    content = API_FILE.read_text()
    # key=GQL operation name (after /), value=(var_suffix, hash_id)
    current_ops: dict[str, tuple[str, str]] = {}
    for m in re.finditer(r'^OP_(\w+)\s*=\s*"([^/]+)/(\w+)"', content, re.MULTILINE):
        var_suffix, hash_id, gql_name = m.groups()
        current_ops[gql_name] = (var_suffix, hash_id)
    print(f"Found {len(current_ops)} operations in {API_FILE}\n")

    print("Fetching Twitter JS bundle...")
    all_pairs: dict[str, str] = {}
    conflicts: list[tuple[str, str, str]] = []

    def _add(op_name: str, op_id: str):
        existing = all_pairs.get(op_name)
        if existing is not None and existing != op_id:
            conflicts.append((op_name, existing, op_id))
        all_pairs[op_name] = op_id

    rgs = [
        r'queryId:"(.+?)".+?operationName:"(.+?)"',
        r'params:\{id:"([^"]+)".+?name:"([^"]+)".+?operationKind:"',
    ]

    for txt in await get_scripts():
        for rg in rgs:
            for op_id, op_name in re.findall(rg, txt):
                _add(op_name, op_id)

    print("-" * 40)

    if conflicts:
        print("WARNING: conflicting IDs found for same operation (last one wins):")
        for n, old_id, new_id in conflicts:
            print(f"  {n}: {old_id} vs {new_id}")

    print(f"Found {len(all_pairs)} operations in bundle\n")

    updated = content
    changed, missing = [], []

    for gql_name, (var_suffix, old_id) in current_ops.items():
        new_id = all_pairs.get(gql_name)
        if new_id is None:
            missing.append(f"OP_{var_suffix}")
        elif new_id != old_id:
            changed.append((var_suffix, old_id, new_id))
            updated = updated.replace(f'"{old_id}/{gql_name}"', f'"{new_id}/{gql_name}"')

    if changed:
        print("Changed:")
        for n, old_id, new_id in changed:
            print(f"  OP_{n}: {old_id} → {new_id}")
    else:
        print("No ID changes.")

    if missing:
        print("\nNot found in bundle (possibly removed):")
        for n in missing:
            print(f"  {n}")

    if changed and apply:
        API_FILE.write_text(updated)
        print(f"\nWritten to {API_FILE}")
    elif changed:
        print("\nRun with --apply to write changes.")


asyncio.run(main())
