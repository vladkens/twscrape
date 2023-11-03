import asyncio
import argparse

import twscrape
from twscrape import set_log_level


async def worker(queue: asyncio.Queue, api: twscrape.API, args):
    while True:
        query = await queue.get()
        try:
            await twscrape.gather(api.search(query, args.limit), with_result=args.with_result)
        except Exception as e:
            print(f"Error on {query} - {type(e)}")
        finally:
            queue.task_done()


async def main(args):
    set_log_level("DEBUG")
    with open('queries.txt', 'r') as file:
        lines = file.readlines()
    queries = [line.strip().lower() for line in lines]
    api = twscrape.API()
    queue = asyncio.Queue()
    workers_count = args.workers
    workers = [asyncio.create_task(worker(queue, api, args)) for _ in range(workers_count)]
    for q in queries:
        queue.put_nowait(q)

    await queue.join()
    for worker_task in workers:
        worker_task.cancel()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parser For Arguments",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--limit", dest="limit", default=40, help="Limit each workers", )
    parser.add_argument("--with_result", dest="with_result", default=False, help="Return Result of Tweets", )
    parser.add_argument("--workers", dest="workers", default=2, help="Workers", )

    args = parser.parse_args()

    asyncio.run(main(args))
