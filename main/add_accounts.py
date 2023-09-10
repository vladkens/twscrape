import asyncio
import twscrape
import json


async def main():
    api = twscrape.API()
    with open('accounts.json', 'r') as file:
        data = json.load(file)
    for acc in data:
        await api.accounts_pool.add_account(acc['username'], acc['password'], acc['email'], acc['email_password'])
    await api.accounts_pool.login_all(email_first=True)


if __name__ == "__main__":
    asyncio.run(main())
