#!/usr/bin/env python3

import argparse
import asyncio

from .api import API, AccountsPool
from .logger import logger, set_log_level
from .utils import print_table


def get_fn_arg(args):
    names = ["query", "tweet_id", "user_id"]
    for name in names:
        if name in args:
            return name, getattr(args, name)

    logger.error(f"Missing argument: {names}")
    exit(1)


async def main(args):
    if args.debug:
        set_log_level("DEBUG")

    pool = AccountsPool(args.db)
    api = API(pool, debug=args.debug)

    if args.command == "accounts":
        print_table(await pool.accounts_info())
        return

    if args.command == "stats":
        print(await pool.stats())
        return

    fn = args.command + "_raw" if args.raw else args.command
    fn = getattr(api, fn, None)
    if fn is None:
        logger.error(f"Unknown command: {args.command}")
        exit(1)

    _, val = get_fn_arg(args)

    if "limit" in args:
        async for doc in fn(val, limit=args.limit):
            print(doc.json())
    else:
        doc = await fn(val)
        print(doc.json())


def run():
    p = argparse.ArgumentParser()
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
        p.add_argument("--limit", type=int, default=20, help="Max tweets to retrieve")
        return p

    subparsers.add_parser("accounts", help="List all accounts")
    subparsers.add_parser("stats", help="Show scraping statistics")

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
    asyncio.run(main(args))
