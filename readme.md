Twitter GraphQL and Search API implementation with [SNScrape](https://github.com/JustAnotherArchivist/snscrape) data models.

### Usage

```python
import asyncio
from twapi.client import UserClient
from twapi.pool import AccountsPool
from twapi.search import Search

async def main():
    acc1 = UserClient("user1", "pass1", "user1@example.com", "email_pass1")
    acc2 = UserClient("user2", "pass2", "user2@example.com", "email_pass2")

    pool = AccountsPool()
    pool.add_account(acc1)
    pool.add_account(acc2)

    search = Search(pool)
    async for rep in search.query("elon musk"):
        print(rep.status_code, rep.json())

if __name__ == "__main__":
    asyncio.run(main())
```
