import asyncio

from twscrape import API


async def main():
    api = API()
    username = "sama"

    info = await api.user_about(username)
    print(info.dict() if info else "Not found")


if __name__ == "__main__":
    asyncio.run(main())
