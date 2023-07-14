import httpx

# update this url on next run
url = "https://abs.twimg.com/responsive-web/client-web/api.f4ff3bfa.js"
script = httpx.get(url).text

ops = """
SearchTimeline
UserByRestId
UserByScreenName
TweetDetail
Followers
Following
Retweeters
Favoriters
UserTweets
UserTweetsAndReplies
ListLatestTweetsTimeline
"""

ops = [op.strip() for op in ops.split("\n") if op.strip()]

for x in ops:
    idx = script.split(f'operationName:"{x}"')[0].split("queryId:")[-1]
    idx = idx.strip('",')
    print(f'OP_{x} = "{idx}/{x}"')
