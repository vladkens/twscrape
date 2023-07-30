#!/usr/bin/env python3

import argparse
import asyncio
import io
import json
import sqlite3
from importlib.metadata import version

import httpx

from .api import API, AccountsPool
from .db import get_sqlite_version
from .logger import logger, set_log_level
from .models import Tweet, User
from .utils import print_table


class CustomHelpFormatter(argparse.HelpFormatter):
    def __init__(self, prog):
        super().__init__(prog, max_help_position=30, width=120)


def get_fn_arg(args):
    names = ["query", "tweet_id", "user_id", "username", "list_id"]
    for name in names:
        if name in args:
            return name, getattr(args, name)

    logger.error(f"Missing argument: {names}")
    exit(1)


def to_str(doc: httpx.Response | Tweet | User | None) -> str:
    if doc is None:
        return "Not Found. See --raw for more details."

    tmp = doc.json()
    return tmp if isinstance(tmp, str) else json.dumps(tmp, default=str)


async def main(args):
    if args.debug:
        set_log_level("DEBUG")

    if args.command == "version":
        print(f"twscrape: {version('twscrape')}")
        print(f"SQLite client: {sqlite3.version}")
        print(f"SQLite runtime: {sqlite3.sqlite_version} ({await get_sqlite_version()})")
        return

    pool = AccountsPool(args.db)
    api = API(pool, debug=args.debug)

    if args.command == "accounts":
        print_table(await pool.accounts_info())
        return

    if args.command == "stats":
        rep = await pool.stats()
        total, active, inactive = rep["total"], rep["active"], rep["inactive"]

        res = []
        for k, v in rep.items():
            if not k.startswith("locked") or v == 0:
                continue
            res.append({"queue": k, "locked": v, "available": max(active - v, 0)})

        res = sorted(res, key=lambda x: x["locked"], reverse=True)
        print_table(res, hr_after=True)
        print(f"Total: {total} - Active: {active} - Inactive: {inactive}")
        return

    if args.command == "add_accounts":
        await pool.load_from_file(args.file_path, args.line_format)
        return

    if args.command == "del_accounts":
        await pool.delete_accounts(args.usernames)
        return

    if args.command == "login_accounts":
        stats = await pool.login_all(email_first=args.email_first)
        print(stats)
        return

    if args.command == "relogin_failed":
        await pool.relogin_failed(email_first=args.email_first)
        return

    if args.command == "relogin":
        await pool.relogin(args.usernames, email_first=args.email_first)
        return

    if args.command == "reset_locks":
        await pool.reset_locks()
        return

    if args.command == "delete_inactive":
        await pool.delete_inactive()
        return

    fn = args.command + "_raw" if args.raw else args.command
    fn = getattr(api, fn, None)
    if fn is None:
        logger.error(f"Unknown command: {args.command}")
        exit(1)

    _, val = get_fn_arg(args)

    if "limit" in args:
        async for doc in fn(val, limit=args.limit):
            print(to_str(doc))
    else:
        doc = await fn(val)
        print(to_str(doc))


def custom_help(p):
    buffer = io.StringIO()
    p.print_help(buffer)
    msg = buffer.getvalue()

    cmd = msg.split("positional arguments:")[1].strip().split("\n")[0]
    msg = msg.replace("positional arguments:", "commands:")
    msg = [x for x in msg.split("\n") if cmd not in x and "..." not in x]
    msg[0] = f"{msg[0]} <command> [...]"

    i = 0
    for i, line in enumerate(msg):
        if line.strip().startswith("search"):
            break

    msg.insert(i, "")
    msg.insert(i + 1, "search commands:")

    print("\n".join(msg))


def run():
    p = argparse.ArgumentParser(add_help=False, formatter_class=CustomHelpFormatter)
    p.add_argument("--db", default="accounts.db", help="Accounts database file")
    p.add_argument("--debug", action="store_true", help="Enable debug mode")
    subparsers = p.add_subparsers(dest="command")

    def c_one(name: str, msg: str, a_name: str, a_msg: str, a_type: type = str):
        p = subparsers.add_parser(name, help=msg)
        p.add_argument(a_name, help=a_msg, type=a_type)
        p.add_argument("--raw", action="store_true", help="Print raw response")
        return p

    def c_lim(name: str, msg: str, a_name: str, a_msg: str, a_type: type = str):
        p = c_one(name, msg, a_name, a_msg, a_type)
        p.add_argument("--limit", type=int, default=-1, help="Max tweets to retrieve")
        return p

    subparsers.add_parser("version", help="Show version")
    subparsers.add_parser("accounts", help="List all accounts")
    subparsers.add_parser("stats", help="Get current usage stats")

    add_accounts = subparsers.add_parser("add_accounts", help="Add accounts")
    add_accounts.add_argument("file_path", help="File with accounts")
    add_accounts.add_argument("line_format", help="args of Pool.add_account splited by same delim")

    del_accounts = subparsers.add_parser("del_accounts", help="Delete accounts")
    del_accounts.add_argument("usernames", nargs="+", default=[], help="Usernames to delete")

    login_cmd = subparsers.add_parser("login_accounts", help="Login accounts")
    relogin = subparsers.add_parser("relogin", help="Re-login selected accounts")
    relogin.add_argument("usernames", nargs="+", default=[], help="Usernames to re-login")
    re_failed = subparsers.add_parser("relogin_failed", help="Retry login for failed accounts")

    check_email = [login_cmd, relogin, re_failed]
    for cmd in check_email:
        cmd.add_argument("--email-first", action="store_true", help="Check email first")

    subparsers.add_parser("reset_locks", help="Reset all locks")
    subparsers.add_parser("delete_inactive", help="Delete inactive accounts")

    c_lim("search", "Search for tweets", "query", "Search query")
    c_one("tweet_details", "Get tweet details", "tweet_id", "Tweet ID", int)
    c_lim("retweeters", "Get retweeters of a tweet", "tweet_id", "Tweet ID", int)
    c_lim("favoriters", "Get favoriters of a tweet", "tweet_id", "Tweet ID", int)
    c_one("user_by_id", "Get user data by ID", "user_id", "User ID", int)
    c_one("user_by_login", "Get user data by username", "username", "Username")
    c_lim("followers", "Get user followers", "user_id", "User ID", int)
    c_lim("following", "Get user following", "user_id", "User ID", int)
    c_lim("user_tweets", "Get user tweets", "user_id", "User ID", int)
    c_lim("user_tweets_and_replies", "Get user tweets and replies", "user_id", "User ID", int)
    c_lim("list_timeline", "Get tweets from list", "list_id", "List ID", int)

    args = p.parse_args()
    if args.command is None:
        return custom_help(p)

    asyncio.run(main(args))
