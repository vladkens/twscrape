# twscrape

<div align="center">

[<img src="https://badgen.net/pypi/v/twscrape" alt="version" />](https://pypi.org/project/twscrape)
[<img src="https://badgen.net/pypi/python/twscrape" alt="py versions" />](https://pypi.org/project/twscrape)
[<img src="https://badgen.net/pypi/dm/twscrape" alt="downloads" />](https://pypi.org/project/twscrape)
[<img src="https://badgen.net/github/license/vladkens/twscrape" alt="license" />](https://github.com/vladkens/twscrape/blob/main/LICENSE)
[<img src="https://badgen.net/static/-/buy%20me%20a%20coffee/ff813f?icon=buymeacoffee&label" alt="donate" />](https://buymeacoffee.com/vladkens)

</div>

Twitter GraphQL API implementation with [SNScrape](https://github.com/JustAnotherArchivist/snscrape) data models.

<div align="center">
  <img src=".github/example.png" alt="example of cli usage" height="400px">
</div>

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
from twscrape import API, gather
from twscrape.logger import set_log_level

async def main():
    api = API()  # or API("path-to.db") - default is `accounts.db`

    # ADD ACCOUNTS (for CLI usage see BELOW)
    await api.pool.add_account("user1", "pass1", "u1@example.com", "mail_pass1")
    await api.pool.add_account("user2", "pass2", "u2@example.com", "mail_pass2")
    await api.pool.login_all()

    # or add account with COOKIES (with cookies login not required)
    cookies = "abc=12; ct0=xyz"  # or '{"abc": "12", "ct0": "xyz"}'
    await api.pool.add_account("user3", "pass3", "u3@mail.com", "mail_pass3", cookies=cookies)

    # API USAGE

    # search (latest tab)
    await gather(api.search("elon musk", limit=20))  # list[Tweet]
    # change search tab (product), can be: Top, Latest (default), Media
    await gather(api.search("elon musk", limit=20, kv={"product": "Top"}))

    # tweet info
    tweet_id = 20
    await api.tweet_details(tweet_id)  # Tweet
    await gather(api.retweeters(tweet_id, limit=20))  # list[User]

    # Note: this method have small pagination from X side, like 5 tweets per query
    await gather(api.tweet_replies(tweet_id, limit=20))  # list[Tweet]

    # get user by login
    user_login = "xdevelopers"
    await api.user_by_login(user_login)  # User

    # user info
    user_id = 2244994945
    await api.user_by_id(user_id)  # User
    await gather(api.following(user_id, limit=20))  # list[User]
    await gather(api.followers(user_id, limit=20))  # list[User]
    await gather(api.verified_followers(user_id, limit=20))  # list[User]
    await gather(api.subscriptions(user_id, limit=20))  # list[User]
    await gather(api.user_tweets(user_id, limit=20))  # list[Tweet]
    await gather(api.user_tweets_and_replies(user_id, limit=20))  # list[Tweet]

    # list info
    list_id = 123456789
    await gather(api.list_timeline(list_id))

    # NOTE 1: gather is a helper function to receive all data as list, FOR can be used as well:
    async for tweet in api.search("elon musk"):
        print(tweet.id, tweet.user.username, tweet.rawContent)  # tweet is `Tweet` object

    # NOTE 2: all methods have `raw` version (returns `httpx.Response` object):
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

### Depraceted API methods (no more available in X)

- favoriters ([ref](https://x.com/XDevelopers/status/1800675411086409765))
- liked_tweets ([ref](https://x.com/XDevelopers/status/1800675411086409765))

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

### Add accounts

To add accounts use `add_accounts` command. Command syntax is:
```sh
twscrape add_accounts <file_path> <line_format>
```

Where:
`<line_format>` is format of line if accounts file splited by delimeter. Possible tokens:
- `username` – required
- `password` – required
- `email` – required
- `email_password` – to receive email code (you can use `--manual` mode to get code)
- `cookies` – can be any parsable format (string, json, base64 string, etc)
- `_` – skip column from parse

Tokens should be splited by delimeter, usually "`:`" used.

Example:

I have account files named `order-12345.txt` with format:
```text
username:password:email:email password:user_agent:cookies
```

Command to add accounts will be (user_agent column skiped with `_`):
```sh
twscrape add_accounts ./order-12345.txt username:password:email:email_password:_:cookies
```

### Login accounts

_Note:_ If you added accounts with cookies, login not required.

Run:

```sh
twscrape login_accounts
```

`twscrape` will start login flow for each new account. If X will ask to verify email and you provided `email_password` in `add_account`, then `twscrape` will try to receive verification code by IMAP protocol. After success login account cookies will be saved to db file for future use.

#### Manual email verification

In case your email provider not support IMAP protocol (ProtonMail, Tutanota, etc) or IMAP is disabled in settings, you can enter email verification code manually. To do this run login command with `--manual` flag.

Example:

```sh
twscrape login_accounts --manual
twscrape relogin user1 user2 --manual
twscrape relogin_failed --manual
```

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
twscrape tweet_replies TWEET_ID --limit=20
twscrape retweeters TWEET_ID --limit=20
twscrape user_by_id USER_ID
twscrape user_by_login USERNAME
twscrape following USER_ID --limit=20
twscrape followers USER_ID --limit=20
twscrape verified_followers USER_ID --limit=20
twscrape subscriptions USER_ID --limit=20
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

## Proxy

There are few options to use proxies.

1. You can add proxy per account

```py
proxy = "http://login:pass@example.com:8080"
await api.pool.add_account("user4", "pass4", "u4@mail.com", "mail_pass4", proxy=proxy)
```

2. You can use global proxy for all accounts

```py
proxy = "http://login:pass@example.com:8080"
api = API(proxy=proxy)
doc = await api.user_by_login("elonmusk")
```

3. Use can set proxy with environemt variable `TWS_RPOXY`:

```sh
TWS_PROXY=socks5://user:pass@127.0.0.1:1080 twscrape user_by_login elonmusk
```

4. You can change proxy any time like:

```py
api.proxy = "socks5://user:pass@127.0.0.1:1080"
doc = await api.user_by_login("elonmusk")  # new proxy will be used
api.proxy = None
doc = await api.user_by_login("elonmusk")  # no proxy used
```

5. Proxy priorities

- `api.proxy` have top priority
- `env.proxy` will be used if `api.proxy` is None
- `acc.proxy` have lowest priotity

So if you want to use proxy PER ACCOUNT, do NOT override proxy with env variable or by passing proxy param to API.

_Note:_ If proxy not working, exception will be raised from API class.

## Environment variables

- `TWS_WAIT_EMAIL_CODE` – timeout for email verification code during login (default: `30`, in seconds)
- `TWS_RAISE_WHEN_NO_ACCOUNT` – raise `NoAccountError` exception when no available accounts right now, instead of waiting for availability (default: `false`, possible value: `false` / `0` / `true` / `1`)

## Limitations

After 1 July 2023 Twitter [introduced new limits](https://x.com/elonmusk/status/1675187969420828672) and still continue to update it periodically.

The basic behaviour is as follows:
- the request limit is updated every 15 minutes for each endpoint individually
- e.g. each account have 50 search requests / 15 min, 50 profile requests / 15 min, etc.

API data limits:
- `user_tweets` & `user_tweets_and_replies` – can return ~3200 tweets maximum

## Articles
- [How to still scrape millions of tweets in 2023](https://medium.com/@vladkens/how-to-still-scrape-millions-of-tweets-in-2023-using-twscrape-97f5d3881434)
- [_(Add Article)_](https://github.com/vladkens/twscrape/edit/main/readme.md)

## See also
- [twitter-advanced-search](https://github.com/igorbrigadir/twitter-advanced-search) – guide on search filters
- [twitter-api-client](https://github.com/trevorhobenshield/twitter-api-client) – Implementation of Twitter's v1, v2, and GraphQL APIs
- [snscrape](https://github.com/JustAnotherArchivist/snscrape) – is a scraper for social networking services (SNS)
- [twint](https://github.com/twintproject/twint) – Twitter Intelligence Tool
