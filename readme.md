Twitter GraphQL and Search API implementation with [SNScrape](https://github.com/JustAnotherArchivist/snscrape) data models.

### Usage

```python
import asyncio
from twapi.client import UserClient
from twapi.search import Search

async def main():
    account = UserClient("user", "pass", "user@example.com", "email_pass")
    search = Search(account)

    async for rep, data, _ in search.query("elon musk"):
        print(rep.status_code, data)

if __name__ == "__main__":
    asyncio.run(main())
```
