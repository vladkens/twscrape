"""
This example shows how to use twscrape in parallel with concurrency limit.
"""
import asyncio
import time

import twscrape


async def worker(queue: asyncio.Queue, api: twscrape.API):
    while True:
        query = await queue.get()

        try:
            tweets = await twscrape.gather(api.search(query))
            print(f"{query} - {len(tweets)} - {int(time.time())}")
            # do something with tweets here, eg same to file, etc
        except Exception as e:
            print(f"Error on {query} - {type(e)}")
        finally:
            queue.task_done()


async def main():
    api = twscrape.API()
    # add accounts here or before from cli (see README.md for examples)
    await api.pool.add_account("u1", "p1", "eu1", "ep1")
    await api.pool.login_all()

    queries = ["elon musk", "tesla", "spacex", "neuralink", "boring company"]

    queue = asyncio.Queue()

    workers_count = 2  # limit concurrency here 2 concurrent requests at time
    workers = [asyncio.create_task(worker(queue, api)) for _ in range(workers_count)]
    for q in queries:
        queue.put_nowait(q)

    await queue.join()
    for worker_task in workers:
        worker_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
