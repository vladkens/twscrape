#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["twscrape", "rich>=13.0"]
#
# [tool.uv.sources]
# twscrape = { path = "..", editable = true }
# ///
"""
Usage:
  uv run scripts/update-mocked-data.py fetch                  # fetch stale fixtures
  uv run scripts/update-mocked-data.py fetch --only search    # refetch one fixture
  uv run scripts/update-mocked-data.py validate               # inspect and test fixtures
  uv run scripts/update-mocked-data.py prune                  # validate, then restore value-only changes
  uv run scripts/update-mocked-data.py refresh                # fetch stale fixtures, validate, prune

Fetch downloads stale fixtures; --only always refetches the selected names. Validation is read-only. Pruning runs validation first, compares the downloaded fixtures with HEAD, and restores files whose keys, types, and structural values have not changed.
"""

import argparse
import asyncio
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, TypeAlias

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from twscrape import API, AccountsPool
from twscrape import api as api_mod
from twscrape.logger import set_log_level

OUT = "tests/mocked-data"
META = f"{OUT}/__meta.json"
DEFAULT_TTL_DAYS = 7
MOCK_TESTS = ("tests/test_parser.py", "tests/test_pagination.py", "tests/test_cli.py")
console = Console()

MetaEntry: TypeAlias = tuple[str, str]  # (gql_op_id, file_sha256)
Shape: TypeAlias = frozenset[str]


def shape_signature(obj: Any) -> Shape:
    return frozenset(_shape_lines(obj, "$", None))


def shape_diff(old: Any, new: Any) -> tuple[list[str], list[str]]:
    old_shape = shape_signature(old)
    new_shape = shape_signature(new)
    return sorted(new_shape - old_shape), sorted(old_shape - new_shape)


def _shape_lines(obj: Any, path: str, key: str | None) -> set[str]:
    if isinstance(obj, dict):
        lines = {f"{path}:object"}
        for child_key, value in obj.items():
            lines.update(_shape_lines(value, _child_path(path, child_key), child_key))
        return lines

    if isinstance(obj, list):
        lines = {f"{path}:array"}
        for item in obj:
            lines.update(_shape_lines(item, f"{path}[]", key))
        return lines

    return {f"{path}:{_scalar_shape(path, key, obj)}"}


def _scalar_shape(path: str, key: str | None, value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        if key is not None and _is_structural_string(path, key):
            return f"str={json.dumps(value, ensure_ascii=False)}"
        return "str"
    return type(value).__name__


def _is_structural_string(path: str, key: str) -> bool:
    return (
        key in {"__typename", "type", "operationKind"}
        or key.endswith("Type")
        or key.endswith("_type")
        or path.endswith(".card.legacy.name")
        or path.endswith(".card.legacy.binding_values[].key")
    )


def _child_path(path: str, key: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        return f"{path}.{key}"
    return f"{path}[{json.dumps(key, ensure_ascii=False)}]"


def _collapse_shape_changes(lines: list[str]) -> list[str]:
    paths = {line.split(":", 1)[0] for line in lines}

    def is_descendant(path: str, parent: str) -> bool:
        return (
            path.startswith(f"{parent}.")
            or path.startswith(f"{parent}[]")
            or path.startswith(f"{parent}[")
        )

    return [
        line
        for line in lines
        if not any(
            parent != line.split(":", 1)[0] and is_descendant(line.split(":", 1)[0], parent)
            for parent in paths
        )
    ]


def _split_shape_line(line: str) -> tuple[str, str]:
    path, shape = line.split(":", 1)
    return path, shape


def _shape_json_location(line: str) -> tuple[str, str]:
    path, _ = _split_shape_line(line)
    markers = (
        ("$.data.user.result.", "User result"),
        (".user_results.result.", "User result"),
        (".user_refs_results[].result.", "User result"),
        (".tweet_results.result.", "Tweet result"),
        (".article_results.result.", "Article result"),
        (".note_tweet_results.result.", "Note tweet result"),
        (".members_slice.items_results[].result.", "Community member result"),
        (".moderators_slice.items_results[].result.", "Community moderator result"),
    )
    matches = [(path.rfind(marker), marker, label) for marker, label in markers if marker in path]
    if matches:
        index, marker, label = max(matches)
        return label, path[index + len(marker) :]
    return "Response", path.removeprefix("$.")


def _human_shape(value: str) -> str:
    names = {"bool": "boolean", "int": "integer", "str": "string"}
    if value.startswith("str="):
        return f"string value {value.removeprefix('str=')}"
    return names.get(value, value)


def _describe_subtree(root_line: str, lines: list[str]) -> tuple[str, set[str]]:
    root_path, root_shape = _split_shape_line(root_line)
    members = []
    prefix = f"{root_path}."
    array_prefix = f"{root_path}[]."

    for line in lines:
        path, shape = _split_shape_line(line)
        if path.startswith(prefix):
            relative = path[len(prefix) :]
        elif path.startswith(array_prefix):
            relative = f"[].{path[len(array_prefix) :]}"
        else:
            continue
        if "." not in relative and "[]" not in relative and "[" not in relative:
            members.append(f"{relative}: {_human_shape(shape)}")

    return _human_shape(root_shape), set(members)


def _format_subtree(shapes: set[str], members: set[str]) -> str:
    if not shapes:
        return "missing"
    description = " / ".join(sorted(shapes))
    if members:
        description += " {" + ", ".join(sorted(members)) + "}"
    return description


def load_meta() -> dict[str, MetaEntry]:
    try:
        if not os.path.exists(META):
            return {}
        with open(META, encoding="utf-8") as fp:
            raw = json.load(fp)
        result: dict[str, MetaEntry] = {}
        for k, v in raw.items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                result[k] = (v[0], str(v[1]))
            elif isinstance(v, list) and len(v) == 2:
                result[k] = (str(v[1]), "")
            elif isinstance(v, list) and len(v) == 3:
                result[k] = (str(v[1]), str(v[2]))
        return result
    except Exception:
        return {}


def save_meta(meta: dict[str, MetaEntry]):
    with open(META, "w", encoding="utf-8") as fp:
        json.dump({k: list(v) for k, v in sorted(meta.items())}, fp, indent=2)
        fp.write("\n")


def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        while chunk := fp.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


_UID = 2244994945  # https://x.com/xdevelopers
_TID = 1649191520250245121  # https://x.com/i/status/1649191520250245121
_CID = 1501272736215322629  # https://x.com/i/communities/1501272736215322629
_LID = 1494877848087187461  # https://x.com/i/lists/1494877848087187461


def search_query() -> str:
    until = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    return f"tesla lang:en min_faves:100 until:{until}"


COMMANDS = [
    ("user_by_id", lambda api: api.user_by_id_raw(_UID)),
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
    ("search", lambda api: _first(api.search_raw(search_query(), limit=5))),
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


def print_shape_report() -> int:
    value_only = []
    new_fixtures = []
    shape_changed = 0
    failed = 0
    errors: list[tuple[str, str]] = []
    changes: defaultdict[tuple[str, str], dict[str, set[str]]] = defaultdict(
        lambda: {
            "before_shapes": set(),
            "before_members": set(),
            "after_shapes": set(),
            "after_members": set(),
            "fixtures": set(),
        }
    )

    for name, _ in COMMANDS:
        path = f"{OUT}/raw_{name}.json"
        if not os.path.exists(path):
            continue

        previous = _read_head_file(path)
        if previous is None:
            new_fixtures.append(name)
            shape_changed += 1
            continue

        with open(path, "rb") as fp:
            current = fp.read()
        if current == previous:
            continue

        try:
            added, removed = shape_diff(json.loads(previous), json.loads(current))
        except Exception as e:
            errors.append((name, f"{type(e).__name__}: {e}"))
            failed += 1
            continue

        if not added and not removed:
            value_only.append(name)
            continue

        added_roots = _collapse_shape_changes(added)
        removed_roots = _collapse_shape_changes(removed)
        shape_changed += 1

        for side, roots, all_lines in (
            ("after", added_roots, added),
            ("before", removed_roots, removed),
        ):
            for line in roots:
                location = _shape_json_location(line)
                shape, members = _describe_subtree(line, all_lines)
                changes[location][f"{side}_shapes"].add(shape)
                changes[location][f"{side}_members"].update(members)
                changes[location]["fixtures"].add(name)

    if new_fixtures:
        console.print(
            "[bold green]New fixtures:[/bold green] "
            + ", ".join(f"raw_{name}.json" for name in new_fixtures)
        )

    if value_only:
        console.print(
            "[bold]Value-only fixtures:[/bold] "
            + ", ".join(f"raw_{name}.json" for name in value_only)
        )

    if changes:
        shared_minimum = 1 if shape_changed == 1 else max(2, (shape_changed + 1) // 2)
        shared_changes = {
            location: details
            for location, details in changes.items()
            if len(details["fixtures"]) >= shared_minimum
        }
        shown_changes = shared_changes or changes
        if shared_changes:
            title = (
                "[bold]Shared JSON schema changes[/bold] "
                f"[dim](present in at least {shared_minimum} fixtures; not Python symbols)[/dim]"
            )
        else:
            title = "[bold]Changed JSON payload fields[/bold] [dim](not Python symbols)[/dim]"
        tree = Tree(title)
        grouped: defaultdict[str, list[tuple[str, dict[str, set[str]]]]] = defaultdict(list)
        for (json_object, field), details in shown_changes.items():
            grouped[json_object].append((field, details))

        object_order = sorted(
            grouped,
            key=lambda name: (-max(len(x[1]["fixtures"]) for x in grouped[name]), name),
        )
        for json_object in object_order:
            object_node = tree.add(Text(f"{json_object} JSON", style="bold"))
            fields = sorted(
                grouped[json_object],
                key=lambda item: (-len(item[1]["fixtures"]), item[0]),
            )
            for field, details in fields:
                names = sorted(details["fixtures"])
                label = Text(field, style="cyan")
                label.append(
                    f"  ({len(names)} fixtures; e.g. raw_{names[0]}.json)",
                    style="dim",
                )
                field_node = object_node.add(label)
                before = _format_subtree(details["before_shapes"], details["before_members"])
                after = _format_subtree(details["after_shapes"], details["after_members"])
                before_text = Text("Before: ", style="bold")
                before_text.append(before, style="dim" if before == "missing" else "red")
                after_text = Text("After:  ", style="bold")
                after_text.append(after, style="dim" if after == "missing" else "green")
                field_node.add(before_text)
                field_node.add(after_text)
        console.print(tree)

    for name, error in errors:
        console.print(f"[red]Failed to inspect raw_{name}.json:[/red] {error}")

    console.print(
        f"[bold]{shape_changed}[/bold] shape-changed, "
        f"[bold]{len(value_only)}[/bold] value-only, "
        f"[bold red]{failed}[/bold red] failed"
    )
    return 1 if failed else 0


def validate_fixtures() -> int:
    if print_shape_report() != 0:
        return 1

    print("\nparser validation:", flush=True)
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    result = subprocess.run(["uv", "run", "pytest", "-q", *MOCK_TESTS], check=False, env=env)
    return result.returncode


def prune_unchanged_fixtures() -> int:
    paths = [f"{OUT}/raw_{name}.json" for name, _ in COMMANDS]
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", *paths],
        check=False,
    )
    if staged.returncode == 1:
        print("fail  mocked data is staged; prune it before adding files to the index")
        return 1
    if staged.returncode != 0:
        print("fail  unable to inspect staged mocked data")
        return 1

    meta = load_meta()
    restored = 0
    kept = 0
    failed = 0
    meta_changed = False

    for name, _ in COMMANDS:
        path = f"{OUT}/raw_{name}.json"
        if not os.path.exists(path):
            continue

        previous = _read_head_file(path)
        if previous is None:
            print(f"keep  {name}  (new fixture)")
            kept += 1
            continue

        with open(path, "rb") as fp:
            current = fp.read()
        if current == previous:
            continue

        try:
            added, removed = shape_diff(json.loads(previous), json.loads(current))
        except Exception as e:
            print(f"fail  {name}  ({type(e).__name__}: {e})")
            failed += 1
            continue

        if added or removed:
            print(f"keep  {name}  (shape changed: +{len(added)} -{len(removed)})")
            kept += 1
            continue

        with open(path, "wb") as fp:
            fp.write(previous)
        if item := meta.get(name):
            meta[name] = (item[0], file_hash(path))
            meta_changed = True
        print(f"drop  {name}  (shape unchanged)")
        restored += 1

    if meta_changed:
        save_meta(meta)

    print(f"\n{restored} value-only changes dropped, {kept} shape changes kept, {failed} failed")
    return 1 if failed else 0


def _read_head_file(path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return result.stdout if result.returncode == 0 else None


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
    path = f"{OUT}/raw_{name}.json"
    if not os.path.exists(path):
        return "missing"
    item = meta.get(name)
    if item is None:
        return "op"
    if item[0] != op:
        return "op"
    if not item[1] or item[1] != file_hash(path):
        return "hash"
    if (time.time() - os.path.getmtime(path)) > ttl_days * 86400:
        return "ttl"
    return "ok"


def print_table(meta: dict[str, MetaEntry], ops: dict[str, str], ttl_days: int):
    table = Table(title="Mock fixture status", box=box.SIMPLE_HEAVY)
    table.add_column("Name")
    table.add_column("Updated at")
    table.add_column("Next in", justify="right")
    table.add_column("Status")
    for name, _ in COMMANDS:
        path = f"{OUT}/raw_{name}.json"
        op = ops[f"{name}_raw"]
        state = get_state(name, op, meta, ttl_days)
        item = meta.get(name)

        if state == "missing":
            table.add_row(name, "—", "—", Text("missing", style="red"))
            continue

        stale_reasons = {"op": "op changed", "hash": "file changed"}
        if state in stale_reasons:
            updated_at = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
            table.add_row(
                name,
                updated_at,
                stale_reasons[state],
                Text("stale", style="yellow"),
            )
            continue

        assert item is not None
        modified_at = os.path.getmtime(path)
        updated_at = datetime.fromtimestamp(modified_at).strftime("%Y-%m-%d %H:%M")
        due_days = ttl_days - (time.time() - modified_at) / 86400

        if due_days < 0:
            next_in, status = f"{abs(due_days):.1f}d overdue", "stale"
        elif due_days < 1:
            next_in, status = f"{due_days * 24:.0f}h", "soon"
        else:
            next_in, status = f"{due_days:.1f}d", "ok"

        status_style = {"ok": "green", "soon": "yellow", "stale": "yellow"}[status]
        table.add_row(name, updated_at, next_in, Text(status, style=status_style))
    console.print(table)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update and validate mock API responses")
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser("fetch", help="download stale fixtures")
    fetch.add_argument("--only", help="comma-separated fixture names")

    commands.add_parser("validate", help="inspect fixtures and run parser tests")
    commands.add_parser("prune", help="validate, then restore value-only changes")
    commands.add_parser("refresh", help="download stale fixtures, validate, and prune")
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "validate":
        return validate_fixtures()
    if args.command == "prune":
        if validate_fixtures() != 0:
            return 1
        return prune_unchanged_fixtures()

    only = (
        {name.strip() for name in (args.only or "").split(",") if name.strip()}
        if args.command == "fetch"
        else set()
    )

    unknown = only - {n for n, _ in COMMANDS}
    if unknown:
        print(f"fail  unknown command(s): {', '.join(sorted(unknown))}")
        return 1

    ttl = DEFAULT_TTL_DAYS

    set_log_level("WARNING")
    os.makedirs(OUT, exist_ok=True)
    meta = load_meta()
    ops = get_ops()

    print_table(meta, ops, ttl)

    to_update = [
        (n, f"{n}_raw", fn)
        for n, fn in COMMANDS
        if (not only or n in only) and (only or is_stale(n, ops[f"{n}_raw"], meta, ttl))
    ]

    if not to_update:
        print("\nAll files are up to date.")
    else:
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
                obj = rep.json()
                if "errors" in obj and "data" not in obj:
                    err = "; ".join(x.get("message", "unknown error") for x in obj["errors"])
                    print(f"fail  {name}  ({err})")
                    fail += 1
                    continue
                with open(outfile, "w", encoding="utf-8") as fp:
                    json.dump(obj, fp, indent=2)
                meta[name] = (ops[method], file_hash(outfile))
                save_meta(meta)
                print(f"ok    {name}")
                ok += 1
            except Exception as e:
                print(f"fail  {name}  ({type(e).__name__}: {e})")
                fail += 1

        skipped = len(COMMANDS) - len(to_update)
        print(f"\n{ok} updated, {skipped} skipped, {fail} failed")

        if fail:
            return 1
    if args.command == "refresh" and validate_fixtures() != 0:
        return 1
    return prune_unchanged_fixtures() if args.command == "refresh" else 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
