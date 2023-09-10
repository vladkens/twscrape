import asyncio
import argparse

import twscrape


async def worker(queue: asyncio.Queue, api: twscrape.API, args):
    while True:
        query = await queue.get()
        try:
            await api.search(query, args.limit, with_result=False)
        except Exception as e:
            print(f"Error on {query} - {type(e)}")
        finally:
            queue.task_done()


async def main(args):
    with open('queries.txt', 'r') as file:
        lines = file.readlines()
    queries = [line.strip().lower() for line in lines]
    api = twscrape.API()
    queue = asyncio.Queue()
    workers_count = 100  # limit concurrency here 2 concurrent requests at time
    workers = [asyncio.create_task(worker(queue, api, args)) for _ in range(workers_count)]
    for q in queries:
        queue.put_nowait(q)

    await queue.join()
    for worker_task in workers:
        worker_task.cancel()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parser For Arguments",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--limit", dest="limit", default=-1, help="Limit each workers", )
    parser.add_argument("--with_result", dest="with_result", default=True, help="Return Result of Tweets", )

    args = parser.parse_args()

    asyncio.run(main(args))
