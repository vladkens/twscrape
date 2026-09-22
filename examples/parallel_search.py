"""
This example shows how to use perchx to complete some queries in parallel.
To limit the number of concurrent requests, see examples/parallel_search_with_limit.py
"""

import asyncio

import perchx


async def worker(api: perchx.API, q: str):
    tweets = []
    try:
        async for doc in api.search(q):
            tweets.append(doc)
    except Exception as e:
        print(e)
    return tweets


async def main():
    api = perchx.API()
    # add accounts here or before from cli (see README.md for examples)
    await api.pool.add_account("u1", "p1", "eu1", "ep1")
    await api.pool.login_all()

    queries = ["elon musk", "tesla", "spacex", "neuralink", "boring company"]
    results = await asyncio.gather(*(worker(api, q) for q in queries))

    combined = dict(zip(queries, results))
    for k, v in combined.items():
        print(k, len(v))


if __name__ == "__main__":
    asyncio.run(main())
