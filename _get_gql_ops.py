import re

import httpx

# note: update this url on next run
# url = "https://abs.twimg.com/responsive-web/client-web/api.f4ff3bfa.js"
# url = "https://abs.twimg.com/responsive-web/client-web/api.bb81931a.js"
url = "https://abs.twimg.com/responsive-web/client-web/main.45d48c6a.js"

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

script: str = httpx.get(url).text
pairs = re.findall(r'queryId:"(.+?)".+?operationName:"(.+?)"', script)
pairs = {op_name: op_id for op_id, op_name in pairs}

for x in ops:
    print(f'OP_{x} = "{pairs.get(x, "???")}/{x}"')

# for ??? check urls:
# https://twitter.com/SpaceX/status/1719132541632864696/likes
# https://twitter.com/i/lists/1494877848087187461
