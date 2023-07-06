# twscrape

<div align="center" style="padding-bottom: 8px">
  <a href="https://pypi.org/project/twscrape">
    <img src="https://badgen.net/pypi/v/twscrape" alt="version" />
  </a>
  <a href="https://pypi.org/project/twscrape">
    <img src="https://badgen.net/pypi/python/twscrape" alt="python versions" />
  </a>
  <a href="https://github.com/vladkens/twscrape/actions">
    <img src="https://github.com/vladkens/twscrape/workflows/test/badge.svg" alt="test status" />
  </a>
  <!-- <a href="https://npmjs.org/package/array-utils-ts">
    <img src="https://badgen.net/npm/dm/array-utils-ts" alt="downloads" />
  </a> -->
  <a href="https://github.com/vladkens/twscrape/blob/main/LICENSE">
    <img src="https://badgen.net/github/license/vladkens/twscrape" alt="license" />
  </a>
</div>

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

Since this project works through an authorized API, accounts need to be added. You can register and add an account yourself. You can also google sites that provide these things.

The email password is needed to get the code to log in to the account automatically (via imap protocol).

Data models:
- [User](https://github.com/vladkens/twscrape/blob/main/twscrape/models.py#L87)
- [Tweet](https://github.com/vladkens/twscrape/blob/main/twscrape/models.py#L136)

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

### Stoping iteration with break

In order to correctly release an account in case of `break` in loop, a special syntax must be used. Otherwise, Python's events loop will release lock on the account sometime in the future. See explanation [here](https://github.com/vladkens/twscrape/issues/27#issuecomment-1623395424).

```python
from contextlib import aclosing

async with aclosing(api.search("elon musk")) as gen:
    async for tweet in gen:
        if tweet.id < 200:
            break
```

## CLI

### Get help on CLI commands

```sh
# show all commands
twscrape

# help on specific comand
twscrape search --help
```

### Add accounts & login

First add accounts from file:

```sh
# twscrape add_accounts <file_path> <line_format>
# line_format should have "username", "password", "email", "email_password" tokens
# note: tokens delimeter should be same as an file
twscrape add_accounts accounts.txt username:password:email:email_password
```

Then call login:

```sh
twscrape login_accounts
```

Accounts and their sessions will be saved, so they can be reused for future requests

### Get list of accounts and their statuses

```sh
twscrape accounts

# Output:
# username  logged_in  active  last_used            total_req  error_msg
# user1     True       True    2023-05-20 03:20:40  100        None
# user2     True       True    2023-05-20 03:25:45  120        None
# user3     False      False   None                 120        Login error
```

### Re-login accounts

It is possible to re-login specific accounts:

```sh
twscrape relogin user1 user2
```

Or retry login for all failed logins:

```sh
twscrape relogin_failed
```

### Use different accounts file

Useful if using a different set of accounts for different actions

```
twscrape --db test-accounts.db <command>
```

### Search commands

```sh
twscrape search "QUERY" --limit=20
twscrape tweet_details TWEET_ID
twscrape retweeters TWEET_ID --limit=20
twscrape favoriters TWEET_ID --limit=20
twscrape user_by_id USER_ID
twscrape user_by_login USERNAME
twscrape followers USER_ID --limit=20
twscrape following USER_ID --limit=20
twscrape user_tweets USER_ID --limit=20
twscrape user_tweets_and_replies USER_ID --limit=20
```

The default output is in the console (stdout), one document per line. So it can be redirected to the file.

```sh
twscrape search "elon mask lang:es" --limit=20 > data.txt
```

By default, parsed data is returned. The original tweet responses can be retrieved with `--raw` flag.

```sh
twscrape search "elon mask lang:es" --limit=20 --raw
```

## Limitations

**NOTE:** After 1 July 2023 Twitter [introduced limits](https://twitter.com/elonmusk/status/1675187969420828672) on the number of tweets per day per account, so the values below may not be fully correct.

API rate limits (per account):
- Search API – 250 req / 15 min
- GraphQL API – has individual rate limits per operation (in most cases this is 500 req / 15 min)

API data limits:
- `user_tweets` & `user_tweets_and_replies` – can return ~3200 tweets maximum

## See also
- [twitter-advanced-search](https://github.com/igorbrigadir/twitter-advanced-search) – guide on search filters
- [twitter-api-client](https://github.com/trevorhobenshield/twitter-api-client) – Implementation of Twitter's v1, v2, and GraphQL APIs
- [snscrape](https://github.com/JustAnotherArchivist/snscrape) – is a scraper for social networking services (SNS)
- [twint](https://github.com/twintproject/twint) – Twitter Intelligence Tool
