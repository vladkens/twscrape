#!/usr/bin/env python3
"""
Fetches current GraphQL operation IDs from Twitter's JS bundle
and updates them in twscrape/api.py.

Usage:
  uv run scripts/update_gql_ops.py
"""

import asyncio
import os
import re
import sys
from typing import Any

from twscrape.http import make_client
from twscrape.xclid import get_scripts_list, get_tw_page_text, script_url

API_FILE = "twscrape/api.py"
CACHE_DIR = "/tmp/twscrape-ops"
MARKER = "# GQL_OPS_CODEGEN"


def _is_relevant_script(url: str) -> bool:
    return "/i18n/" not in url and "/icons/" not in url and "react-syntax-highlighter" not in url


async def get_scripts() -> list[tuple[str, str]]:
    os.makedirs(CACHE_DIR, exist_ok=True)

    async with make_client() as clt:
        text = await get_tw_page_text("https://x.com/elonmusk", clt)

    urls = list(get_scripts_list(text))
    v = text.split("/client-web/main.")[1].split(".")[0]
    urls.append(script_url("main", v))
    urls = [x for x in urls if _is_relevant_script(x)]
    return [(x, f"{CACHE_DIR}/{x.split('/')[-1].split('?')[0]}") for x in urls]


async def fetch_scripts(scripts: list[tuple[str, str]], force: bool) -> None:
    todo = scripts if force else [x for x in scripts if not os.path.exists(x[1])]
    cached = len(scripts) - len(todo)
    print(f"Scripts: {len(scripts)} total, {cached} cached, {len(todo)} to download.")

    if not todo:
        print("Nothing to download.")
        return

    print(f"Downloading {len(todo)} scripts.")
    sem = asyncio.Semaphore(10)

    async def fetch(clt: Any, i: int, url: str, path: str) -> None:
        async with sem:
            print(f"  ({i:3d}/{len(todo):3d}) {url}")
            rep = await clt.get(url)
            rep.raise_for_status()
            ct = rep.headers.get("content-type", "")
            if "javascript" not in ct:
                raise ValueError(f"Unexpected content-type '{ct}' for {url} — rate limited?")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(rep.text)

    async with make_client() as clt:
        await asyncio.gather(*[fetch(clt, i, url, path) for i, (url, path) in enumerate(todo, 1)])


def parse_ops(content: str) -> tuple[str, list[tuple[str, str, str]]]:
    parts = content.split(MARKER)
    if len(parts) != 3:
        raise ValueError(f"Expected exactly two {MARKER!r} markers in {API_FILE}")

    res = []
    for line in parts[1].splitlines():
        line = line.strip()
        if not line:
            continue
        if not line.startswith("OP_"):
            raise ValueError(f"Unexpected line in {MARKER} block: {line}")

        name, value = line.split("=", 1)
        name = name.strip()[3:]
        value = value.strip().strip('"')
        op_id, gql_name = value.split("/", 1)
        res.append((name, op_id, gql_name))

    return parts[1], res


def render_ops(ops: list[tuple[str, str]]) -> str:
    lines = [f'OP_{name} = "{op_id}/{name}"' for name, op_id in ops]
    return "\n" + "\n".join(lines) + "\n"


def rewrite(content: str, block: str) -> str:
    parts = content.split(MARKER)
    if len(parts) != 3:
        raise ValueError(f"Expected exactly two {MARKER!r} markers in {API_FILE}")
    return parts[0] + MARKER + block + MARKER + parts[2]


async def main() -> int:
    force = "--force" in sys.argv

    with open(API_FILE, encoding="utf-8") as fp:
        content = fp.read()

    old_text, current_ops = parse_ops(content)
    renamed: list[tuple[str, str]] = []
    for var_suffix, hash_id, gql_name in current_ops:
        if var_suffix != gql_name:
            renamed.append((var_suffix, gql_name))

    print(f"Found {len(current_ops)} operations in {API_FILE}")
    print("")
    print("Downloading scripts...")
    scripts = await get_scripts()
    await fetch_scripts(scripts, force)
    print("")
    print("Analyzing scripts...")

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

    for _, path in scripts:
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="ignore") as fp:
            txt = fp.read()
        for rg in rgs:
            for op_id, op_name in re.findall(rg, txt):
                _add(op_name, op_id)

    if conflicts:
        print("WARNING: conflicting IDs found for same operation (last one wins):")
        for n, old_id, new_id in conflicts:
            print(f"  {n}: {old_id} vs {new_id}")

    print(f"Found {len(all_pairs)} operations in bundle")

    changed, missing = [], []
    next_ops: list[tuple[str, str]] = []

    for var_suffix, old_id, gql_name in current_ops:
        new_id = all_pairs.get(gql_name)
        if new_id is None:
            missing.append(f"OP_{var_suffix}")
            next_ops.append((gql_name, old_id))
        elif new_id != old_id:
            changed.append((var_suffix, old_id, new_id))
            next_ops.append((gql_name, new_id))
        else:
            next_ops.append((gql_name, old_id))

    next_ops.sort()
    new_block = render_ops(next_ops)
    updated = rewrite(content, new_block)

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

    if renamed:
        print("\nNon-canonical constant names:")
        for var_suffix, gql_name in renamed:
            print(f"  rename OP_{var_suffix} to OP_{gql_name}")

    if new_block != old_text:
        with open(API_FILE, "w", encoding="utf-8") as fp:
            fp.write(updated)
        print(f"\nSaved changes to {API_FILE}")

    return 0


sys.exit(asyncio.run(main()))
