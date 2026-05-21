import asyncio

from twscrape import API


async def main():
    api = API()

    # example community: https://x.com/i/communities/1501272736215322629
    community_id = 1501272736215322629

    # community info
    info = await api.community_info(community_id)
    print(info.name if info else "Unknown community")

    # members
    async for user in api.community_members(community_id, limit=5):
        print(f"member @{user.username} - {user.displayname}")

    # moderators
    async for user in api.community_moderators(community_id, limit=10):
        print(f"moderator @{user.username} - {user.displayname}")

    # tweets
    async for tweet in api.community_tweets(community_id, limit=5):
        print(f"tweet {tweet.id} by @{tweet.user.username}: {tweet.rawContent[:100]}...")


if __name__ == "__main__":
    asyncio.run(main())
