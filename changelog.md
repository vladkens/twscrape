## v0.18.1 – 2026-05-23

### Fixes
- Fixed profile image URL returning empty when a legacy empty value was present (#309)
- Fixed user location being empty when the legacy field was an empty string

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.18.0...v0.18.1

---

## v0.18.0 – 2026-05-22

### Breaking Changes
- Removed `user_by_id` API as X/Twitter no longer supports this endpoint

### Features
- Added `add_cookie` CLI command (#301, by @sakhnenkoff)
- Added API for fetching all tweets in a conversation thread (#252, by @Khanzadeh-AH)
- Added community scraping support (#275)
- Added `list_members` API for retrieving Twitter list members
- Added new fields to `Tweet` model (#279)
- Added user `about` info field (#277, by @terencedignon)

### Fixes
- Restored scraping compatibility after X platform changes in May 2026 (#306, #307, by @mar0ls)
- Fixed JS bundle parsing for `x-client-transaction-id` generation (#303, by @Flaburgan)
- Fixed HTTP client not being properly closed, resolving resource warnings (#304, by @Flaburgan)
- Fixed pagination to continue past empty pages (#265, #247)
- Improved robustness of GQL pagination handling
- Improved proxy handling and `xclid` calculation

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.17.0...v0.18.0

---

## v0.17.0 – 2025-04-29

### Fixes
- Fixed generation of `x-client-transaction-id` header required by the X API (#245, #248)

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.16.0...v0.17.0

---

## v0.16.0 – 2025-03-09

### Breaking Changes
- Removed previously deprecated `favoriters` and `liked_tweets` methods

### Features
- Added `list_explore` and `search_trend` methods to scrape trending topics on X (#234, by @mika-jpd)
- Added ability to search for users/people by query (by @viniciuskloppel)

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.15.0...v0.16.0

---

## v0.15.0 – 2025-01-01

### Fixes
- Fixed SQLite deprecated API warnings on newer Python versions

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.14...v0.15.0

---

## v0.14 – 2024-10-06

### Features
- Added Python 3.13 support

### Fixes
- Fixed media type detection in tweet parsing (by @hponka)

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.13...v0.14

---

## v0.13 – 2024-06-29

### Breaking Changes
- Disabled `favoriters` and `liked_tweets` endpoints — no longer available on X
- Updated API base URL from `twitter.com` to `x.com`

### Features
- Added bookmarks scraping via new `bookmarks` method (by @bjsi)
- Added `bookmarkedCount` field to the Tweet model (by @ShunnMatsumura)
- Added pinned tweets info to user profiles (#201)
- Added support for broadcast and audiospace card types (#191)

### Fixes
- Fixed bookmarks endpoint response parsing
- Fixed message prompt tweet types being incorrectly included in results (by @NielsOerbaek)

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.12...v0.13

---

## v0.12 – 2024-04-18

### Features
- Added TOTP (authenticator app) support for two-factor authentication (by @ritikkumarsahu, @catdevnull)
- Added user media tab scraping (by @Pigglebear, #131)
- Added card parsers for summary, poll, and player card types (#46, #72, #157)
- Added `NoAccountError` as a top-level import for easier error handling
- Added option to raise `NoAccountError` immediately when no active account is available, rather than waiting (#48, #148)
- Added alternate identifier login flow (username or email instead of handle) (by @LucasLeRay)
- Added ability to control which accounts handle specific API endpoints (#138)

### Fixes
- Fixed login failure when `ct0` cookie is absent (#143)
- Fixed infinite login loop for non-existent accounts (#132, #165)
- Fixed async generator resource leaks with `contextlib.aclosing` (by @andylolz)

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.11.1...v0.12

---

## v0.11.1 – 2024-02-12

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.11...v0.11.1

---

## v0.11 – 2024-02-11

### Features
- Added `tweet_replies` method to fetch replies for a tweet (#104)
- Added `verified_followers` and `subscriptions` endpoint methods (#121)
- Added `liked_tweets` method to fetch tweets liked by a user (by @Minecon724)
- Added proxy support with connection error handling (#85, #96, #118)
- Added string `id_str` field to all models (#116)

### Fixes
- Fixed accounts being unnecessarily locked on connection timeout (#113)
- Fixed proxy errors now raising exceptions instead of silently locking the account

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.10.1...v0.11

---

## v0.10.1 – 2024-01-08

### Fixes
- Fixed crash in search result parsing (#107)

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.10.0...v0.10.1

---

## v0.10.0 – 2024-01-05

### Features
- Added ability to enter email verification code manually when auto-detection fails (#86, #100)
- Added ability to fetch a single account by username via CLI
- Added `LOGIN_CODE_TIMEOUT` environment variable to configure the email code wait time
- Added database write locking to prevent conflicts in single-process usage (#64)

### Fixes
- Fixed ban detection logic and `relogin` CLI command to only target selected accounts
- Fixed UTC timezone handling in account timestamps (by @yemregundogmus)
- Fixed handling of unknown authorization errors that return HTTP 200 (by @NielsOerbaek)
- Improved login flow and API error handling reliability

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.9.0...v0.10.0

---

## v0.9.0 – 2023-11-01

### Features
- Added Python 3.12 support

### Fixes
- Fixed retweet and quote tweet parsing for `TweetWithVisibilityResults` response type (by @stygmate)
- Fixed email verification token retrieval during login (by @aatakansalar)
- Fixed raw content reconstruction for retweets

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.8.0...v0.9.0

---

## v0.8.0 – 2023-09-08

### Features
- Added support for `TweetWithVisibilityResults` response type (#53)

### Fixes
- Fixed parsed link count in tweet entities (#56)
- Fixed email login flow (by @entasadar)

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.7.0...v0.8.0

---

## v0.7.0 – 2023-07-30

### Features
- Added `blue` and `blueType` fields to the User model for Twitter Blue status (#38, by @PirateKG)
- Added support for additional cookie formats when importing accounts
- Added infinite retry on HTTP timeout or proxy error without locking the account

### Fixes
- Fixed full tweet text not being restored for retweets (#42)
- Fixed `user_by_id`, `user_by_login`, and `tweet_details` to return `None` instead of raising on inaccessible resources
- Restored login flow with optional email-first verification parameter

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.6.0...v0.7.0

---

## v0.6.0 – 2023-07-15

### Features
- Added account import via browser cookies
- Added `del_account` command to remove accounts via CLI
- Added ability to reset locked accounts via CLI
- Added usage stats to the `login_all` CLI command
- Simplified API client initialization

### Fixes
- Fixed API error handling for responses with HTTP 200 but error payloads in the body

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.5.0...v0.6.0

---

## v0.5.0 – 2023-07-07

### Features
- Added ability to pass a starting cursor to resume pagination (#16)
- Added `list_timeline` method to scrape tweets from a Twitter List (#20)
- Added `relogin` command to re-authenticate accounts from CLI
- Added current API usage overview to CLI
- Added long tweet text support (tweets beyond 140 characters)
- Expanded Tweet model with `viewsCount`, `retweetedTweet`, and `quotedTweet` fields (#28)

### Fixes
- Fixed `tweet_details` crash when the tweet is not found — now returns `None`

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.4.2...v0.5.0

---

## v0.4.2 – 2023-07-06

### Improvements
- Improved queue client stability and request scheduling

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.4.1...v0.4.2

---

## v0.4.1 – 2023-07-06

### Fixes
- Fixed accounts not being locked after a failed request
- Fixed CLI accounts list to sort by last used time

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.4.0...v0.4.1

---

## v0.4.0 – 2023-07-05

### Features
- Migrated search API from REST to GraphQL for improved reliability
- Added profile URL fields to the User model

### Fixes
- Fixed URL parsing in user profiles
- Fixed 401 error handling to automatically switch to another account
- Fixed `user_by_login` CLI endpoint returning incorrect results
- Fixed double-escaped JSON in non-raw CLI output

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.3.0...v0.4.0

---

## v0.3.0 – 2023-06-23

### Features
- Added media parser to extract image and video metadata from tweets

### Fixes
- Fixed CLI `--raw` output returning a stringified Python dict instead of valid JSON

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.2.2...v0.3.0

---

## v0.2.2 – 2023-06-06

### Fixes
- Fixed compatibility with SQLite 3.34

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.2.1...v0.2.2

---

## v0.2.1 – 2023-05-29

### Features
- Added SQLite version display to the `version` CLI command

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.2.0...v0.2.1

---

## v0.2.0 – 2023-05-29

### Features
- Added CLI commands to add accounts and trigger login
- Added `last_used` timestamp and usage statistics tracking per account
- Added error on unsupported SQLite versions

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.1.1...v0.2.0

---

## v0.1.1 – 2023-05-09

### Fixes
- Fixed timezone handling in timestamps
- Added `_type` field to all models for easier type discrimination

**Full Changelog**: https://github.com/vladkens/twscrape/compare/v0.1.0...v0.1.1

---

## v0.1.0 – 2023-05-06

### Features
- Initial release of twscrape
- GraphQL-based Twitter/X API scraping
- Account pool with automatic rotation and rate limit handling
- Search API with cursor-based pagination
- Login flow with email verification code support
- Session dump and restore for persistent accounts
- Automatic retry and account switching on rate limit or failure

**Full Changelog**: https://github.com/vladkens/twscrape/commits/v0.1.0

---
