"""
This example shows how to use twscrape to complete some queries in parallel.
To limit the number of concurrent requests, see examples/parallel_search_with_limit.py
"""

import asyncio

import twscrape


async def worker(api: twscrape.API, q: str) -> list[dict]:
    tweets = []
    try:
        async for doc in api.search(q, timeout=10):
            tweets.append(doc)
    except asyncio.TimeoutError:

