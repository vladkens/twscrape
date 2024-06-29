import asyncio

import twscrape
from twscrape.utils import gather

async def main():
    api = twscrape.API()
    # add accounts here or before from cli (see README.md for examples)
    await api.pool.add_account("BookmarkTe60140", "", '', '')
    await api.pool.login_all()
    bms = await gather(api.bookmarks())
    for bm in bms:
        print(bm.rawContent)
        print('-----')

if __name__ == "__main__":
    asyncio.run(main())