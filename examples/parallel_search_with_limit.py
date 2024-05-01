"""
This example shows how to use twscrape in parallel with concurrency limit.
"""

import asyncio
import time
import logging

import twscrape

logging.basicConfig(level=logging.INFO)

async def worker(queue: asyncio.Queue, api: twscrape.API):
    try:
        while True:
            query = await asyncio.wait_for(queue.get(), timeout=10)

            try:
                tweets = await twscrape.gather(api.search(query), return_exceptions=True)
                logging.info(f"{query} - {len(tweets)} - {int(time.time())}")
                # do something with tweets here, eg same to file, etc
            except Exception as e:
                logging.error(f"Error on {query} - {type(e)}")
            finally:
                queue.task_done()
    except asyncio.CancelledError:
        pass

