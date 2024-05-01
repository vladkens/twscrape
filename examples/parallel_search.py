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
    except Exception as e:
        print(f"Error in worker for query '{q}': {e}")
    except asyncio.TimeoutError:
        print(f"Timeout error in worker for query '{q}'")
    return tweets


async def main():
    api = twscrape.API()

    accounts = [("u1", "p1", "eu1", "ep1")]
    for account in accounts:
        try:
            await api.pool.add_account(*account)
        except Exception as e:
            print(f"Error adding account {account}: {e}")

    try:
        await api.pool.login_all()
    except Exception as e:
        print(f"Error logging in: {e}")
        return

    if not api.pool.logged_in:
        print("No accounts logged in")
        return

    queries = ["elon musk", "tesla", "spacex", "neuralink", "boring company"]
    results = await asyncio.gather(*(worker(api, q) for q in queries))

    combined = dict(zip(queries, results))
    for k, v in combined.items():
        if v:
            print(k, len(v))
        else:
            print(f"No results for query '{k}'")


if __name__ == "__main__":
    asyncio.run(main())
