#!/usr/bin/env python3
"""
Fetches current GraphQL operation IDs from Twitter's JS bundle
and updates them in twscrape/api.py.

Usage:
  uv run scripts/update_gql_ops.py

For a fully clean refresh, remove the temp cache first:
  rm -rf /tmp/twscrape-ops
"""

import asyncio
import os
import re
import sys
from urllib.parse import urljoin

from twscrape.http import HttpClient, make_client
from twscrape.xclid import get_tw_page_text, script_url

API_FILE = "twscrape/api.py"
CACHE_DIR = "/tmp/twscrape-ops"
MARKER = "# GQL_OPS_CODEGEN"
X_WEB_URL_RE = re.compile(r"https://[\w.-]+/x-web/[\w./-]+\.js")
RESPONSIVE_WEB_URL_RE = re.compile(r"https://[\w.-]+/responsive-web/client-web/[\w./-]+\.js")
JS_REF_RE = re.compile(r'(?:from|import)\s*\(?\s*[`"]((?:\.{1,2}/)[^`"]+?\.js)[`"]')


def _is_relevant_script(url: str) -> bool:
    return "/i18n/" not in url and "/icons/" not in url and "react-syntax-highlighter" not in url


def get_scripts_list(text: str) -> list[str]:
    urls = list(dict.fromkeys(X_WEB_URL_RE.findall(text) + RESPONSIVE_WEB_URL_RE.findall(text)))

    # HTML can contain both direct script URLs and a legacy webpack chunk map.
    # The map has separate chunk_id -> name and chunk_id -> hash entries; combine
    # them into /responsive-web/client-web/{name}.{hash}a.js URLs.
    hash_map = {m.group(1): m.group(2) for m in re.finditer(r'(\d+):"([0-9a-f]{7})"', text)}
    if not hash_map and not urls:
        raise Exception("Failed to parse scripts")

    name_map: dict[str, str] = {}
    for m in re.finditer(r'(\d+):"([^"]+)"', text):
        val = m.group(2)
        if not re.fullmatch(r"[0-9a-f]{7}", val):
            name_map[m.group(1)] = val

    urls.extend(
        script_url(name_map.get(chunk_id, chunk_id), hash_val + "a")
        for chunk_id, hash_val in hash_map.items()
    )
    return list(dict.fromkeys(urls))


def _get_legacy_main_script(text: str) -> str | None:
    match = re.search(r"/client-web/main\.([^.\"']+)\.js", text)
    if not match:
        return None
    return script_url("main", match.group(1))


async def get_scripts() -> list[tuple[str, str]]:
    os.makedirs(CACHE_DIR, exist_ok=True)

    urls: list[str] = []
    async with make_client() as clt:
        for page_url in ("https://x.com/xdevelopers", "https://x.com/home"):
            text = await get_tw_page_text(page_url, clt)
            urls.extend(get_scripts_list(text))
            if main_script := _get_legacy_main_script(text):
                urls.append(main_script)

    urls = list(dict.fromkeys(urls))
    urls = [x for x in urls if _is_relevant_script(x)]
    return [_script_entry(x) for x in urls]


def _script_entry(url: str) -> tuple[str, str]:
    return (url, f"{CACHE_DIR}/{url.split('/')[-1].split('?')[0]}")


def _discover_scripts(scripts: list[tuple[str, str]]) -> list[tuple[str, str]]:
    urls = {url for url, _ in scripts}
    found: list[str] = []

    for base_url, path in scripts:
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="ignore") as fp:
            text = fp.read()
        for ref in JS_REF_RE.findall(text):
            url = urljoin(base_url, ref)
            if url not in urls and _is_relevant_script(url):
                urls.add(url)
                found.append(url)

    return [_script_entry(x) for x in found]


async def fetch_scripts(scripts: list[tuple[str, str]], force: bool) -> list[tuple[str, str]]:
    all_scripts = list(dict.fromkeys(scripts))
    seen = {url for url, _ in all_scripts}
    batch = all_scripts

    while batch:
        await _fetch_scripts_batch(batch, force)
        discovered = _discover_scripts(batch)
        batch = [x for x in discovered if x[0] not in seen]
        seen.update(url for url, _ in batch)
        all_scripts.extend(batch)

    return all_scripts


async def _fetch_scripts_batch(scripts: list[tuple[str, str]], force: bool) -> None:
    todo = scripts if force else [x for x in scripts if not os.path.exists(x[1])]
    cached = len(scripts) - len(todo)
    print(f"Scripts: {len(scripts)} total, {cached} cached, {len(todo)} to download.")

    if not todo:
        print("Nothing to download.")
        return

    print(f"Downloading {len(todo)} scripts.")
    sem = asyncio.Semaphore(10)

    async def fetch(clt: HttpClient, i: int, url: str, path: str) -> None:
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
    lines = dict.fromkeys(f'OP_{name} = "{op_id}/{name}"' for name, op_id in ops)
    return "\n" + "\n".join(lines) + "\n"


def rewrite(content: str, block: str) -> str:
    parts = content.split(MARKER)
    if len(parts) != 3:
        raise ValueError(f"Expected exactly two {MARKER!r} markers in {API_FILE}")
    return parts[0] + MARKER + block + MARKER + parts[2]


def _source_priority(url: str) -> int:
    if "/responsive-web/client-web/" in url:
        return 2
    if "/x-web/" in url:
        return 1
    return 0


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
    scripts = await fetch_scripts(scripts, force)
    print("")
    print("Analyzing scripts...")

    all_pairs: dict[str, tuple[str, int]] = {}

    def _add(op_name: str, op_id: str, url: str):
        priority = _source_priority(url)
        existing = all_pairs.get(op_name)
        if existing is not None and existing[0] != op_id and priority < existing[1]:
            return
        all_pairs[op_name] = (op_id, priority)

    rgs = [
        r'queryId:[`"](.+?)[`"].+?operationName:[`"](.+?)[`"]',
        r'params:\{id:[`"]([^`"]+)[`"].+?name:[`"]([^`"]+)[`"].+?operationKind:[`"]',
    ]

    for url, path in scripts:
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="ignore") as fp:
            txt = fp.read()
        for rg in rgs:
            for op_id, op_name in re.findall(rg, txt):
                _add(op_name, op_id, url)

    print(f"Found {len(all_pairs)} operations in bundle")

    changed, missing = [], []
    next_ops: list[tuple[str, str]] = []

    for var_suffix, old_id, gql_name in current_ops:
        found = all_pairs.get(gql_name)
        if found is None:
            missing.append(f"OP_{var_suffix}")
            next_ops.append((gql_name, old_id))
            continue

        new_id = found[0]
        if new_id != old_id:
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

    if renamed:
        print("\nNon-canonical constant names:")
        for var_suffix, gql_name in renamed:
            print(f"  rename OP_{var_suffix} to OP_{gql_name}")

    if new_block != old_text:
        with open(API_FILE, "w", encoding="utf-8") as fp:
            fp.write(updated)
        print(f"\nSaved changes to {API_FILE}")

    if missing:
        print("\nERROR: some configured GraphQL operations were not found in downloaded bundles.")
        for n in missing:
            print(f"  {n}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
