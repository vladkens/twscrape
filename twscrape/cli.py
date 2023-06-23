#!/usr/bin/env python3

import argparse
import asyncio
import io
import json
import sqlite3
from importlib.metadata import version

from .api import API, AccountsPool
from .db import get_sqlite_version
from .logger import logger, set_log_level
from .utils import print_table


class CustomHelpFormatter(argparse.HelpFormatter):
    def __init__(self, prog):
        super().__init__(prog, max_help_position=30, width=120)


def get_fn_arg(args):
    names = ["query", "tweet_id", "user_id", "username"]
    for name in names:
        if name in args:
            return name, getattr(args, name)

    logger.error(f"Missing argument: {names}")
    exit(1)


def to_str(doc):
    # doc is httpx.Response or twscrape.User / twscrape.Tweet
    # both have .json method but with different return type
    return doc if isinstance(doc, str) else json.dumps(doc.json(), default=str)


async def main(args):
    if args.debug:
        set_log_level("DEBUG")

    if args.command == "version":
        print(f"twscrape: {version('twscrape')}")
        print(f"SQLite client: {sqlite3.version}")
        print(f"SQLite runtime: {sqlite3.sqlite_version} ({await get_sqlite_version()})")
        return

    logger.debug(f"Using database: {args.db}")
    pool = AccountsPool(args.db)
    api = API(pool, debug=args.debug)

    if args.command == "accounts":
        print_table(await pool.accounts_info())
        return

    if args.command == "stats":
        print(await pool.stats())
        return

    if args.command == "add_accounts":
        await pool.load_from_file(args.file_path, args.line_format)
        return

    if args.command == "login_accounts":
        await pool.login_all()
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

    def cone(name: str, msg: str, a_name: str, a_msg: str, a_type: type = str):
        p = subparsers.add_parser(name, help=msg)
        p.add_argument(a_name, help=a_msg, type=a_type)
        p.add_argument("--raw", action="store_true", help="Print raw response")
        return p

    def clim(name: str, msg: str, a_name: str, a_msg: str, a_type: type = str):
        p = cone(name, msg, a_name, a_msg, a_type)
        p.add_argument("--limit", type=int, default=-1, help="Max tweets to retrieve")
        return p

    subparsers.add_parser("version", help="Show version")

    subparsers.add_parser("accounts", help="List all accounts")
    add_accounts = subparsers.add_parser("add_accounts", help="Add accounts")
    add_accounts.add_argument("file_path", help="File with accounts")
    add_accounts.add_argument("line_format", help="args of Pool.add_account splited by same delim")
    subparsers.add_parser("login_accounts", help="Login accounts")

    clim("search", "Search for tweets", "query", "Search query")
    cone("tweet_details", "Get tweet details", "tweet_id", "Tweet ID", int)
    clim("retweeters", "Get retweeters of a tweet", "tweet_id", "Tweet ID", int)
    clim("favoriters", "Get favoriters of a tweet", "tweet_id", "Tweet ID", int)
    cone("user_by_id", "Get user data by ID", "user_id", "User ID", int)
    clim("user_by_login", "Get user data by username", "username", "Username")
    clim("followers", "Get user followers", "user_id", "User ID", int)
    clim("following", "Get user following", "user_id", "User ID", int)
    clim("user_tweets", "Get user tweets", "user_id", "User ID", int)
    clim("user_tweets_and_replies", "Get user tweets and replies", "user_id", "User ID", int)

    args = p.parse_args()
    if args.command is None:
        return custom_help(p)

    asyncio.run(main(args))
