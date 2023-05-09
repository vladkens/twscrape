# twscrape

Twitter GraphQL and Search API implementation with [SNScrape](https://github.com/JustAnotherArchivist/snscrape) data models.

## Install

```bash
pip install twscrape
```
Or development version:
```bash
pip install git+https://github.com/vladkens/twscrape.git
```

## Features
- Support both Search & GraphQL Twitter API
- Async/Await functions (can run multiple scrapers in parallel at the same time)
- Login flow (with receiving verification code from email)
- Saving/restoring account sessions
- Raw Twitter API responses & SNScrape models
- Automatic account switching to smooth Twitter API rate limits

## Usage

```python
import asyncio
from twscrape import AccountsPool, API, gather
from twscrape.logger import set_log_level

async def main():
    pool = AccountsPool()  # or AccountsPool("path-to.db") - default is `accounts.db` 
    await pool.add_account("user1", "pass1", "user1@example.com", "email_pass1")
    await pool.add_account("user2", "pass2", "user2@example.com", "email_pass2")

    # log in to all new accounts
    await pool.login_all()

    api = API(pool)

    # search api (latest tab)
    await gather(api.search("elon musk", limit=20))  # list[Tweet]

    # graphql api
    tweet_id, user_id, user_login = 20, 2244994945, "twitterdev"

    await api.tweet_details(tweet_id)  # Tweet
    await gather(api.retweeters(tweet_id, limit=20))  # list[User]
    await gather(api.favoriters(tweet_id, limit=20))  # list[User]

    await api.user_by_id(user_id)  # User
    await api.user_by_login(user_login)  # User
    await gather(api.followers(user_id, limit=20))  # list[User]
    await gather(api.following(user_id, limit=20))  # list[User]
    await gather(api.user_tweets(user_id, limit=20))  # list[Tweet]
    await gather(api.user_tweets_and_replies(user_id, limit=20))  # list[Tweet]

    # note 1: limit is optional, default is -1 (no limit)
    # note 2: all methods have `raw` version e.g.:

    async for tweet in api.search("elon musk"):
        print(tweet.id, tweet.user.username, tweet.rawContent)  # tweet is `Tweet` object

    async for rep in api.search_raw("elon musk"):
        print(rep.status_code, rep.json())  # rep is `httpx.Response` object

    # change log level, default info
    set_log_level("DEBUG")

    # Tweet & User model can be converted to regular dict or json, e.g.:
    doc = await api.user_by_id(user_id)  # User
    doc.dict()  # -> python dict
    doc.json()  # -> json string

if __name__ == "__main__":
    asyncio.run(main())
```

Note on rate limits:
- Search API – 250 requests per account / 15 minites
- GraphQL API – 500 requests per account per operation / 15 minutes

### Models
- [Tweet](https://github.com/vladkens/twscrape/blob/main/twscrape/models.py#:~:text=class%20Tweet)
- [User](https://github.com/vladkens/twscrape/blob/main/twscrape/models.py#:~:text=class%20User)

### Related
- [SNScrape](https://github.com/JustAnotherArchivist/snscrape) – is a scraper for social networking services (SNS)
