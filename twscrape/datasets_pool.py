import json

from .models import Tweet
from .db import execute, executemany
from .utils import utc_ts, utc_iso, default_json_dumps


class DatasetsPool:
    def __init__(self, db_file="database.db"):
        self._db_file = db_file

    async def save_tweets(self, tweets: list[Tweet]):
        cols = ["id", "tweet", "created_at", "updated_at"]
        data = []
        for tweet in tweets:
            data.append(dict(
                {
                    "id": tweet.id,
                    "tweet": json.dumps(tweet.dict(), sort_keys=True, indent=1, default=default_json_dumps),
                    "created_at": utc_iso(),
                    "updated_at": utc_iso()
                }
            ))
        values = [(row["id"], row["tweet"], row["created_at"], row["updated_at"]) for row in data]
        qs = f"""
        INSERT INTO tweets ({",".join(cols)})
        VALUES ({','.join(['?'] * len(cols))})
        ON CONFLICT(id) DO UPDATE SET updated_at = {utc_iso()}
        """
        await executemany(self._db_file, qs, values)

    async def save_keyword_tweets(self, tweets: list[Tweet], q: str):
        cols = ["tweet_id", "keyword"]
        data = []
        for tweet in tweets:
            data.append(dict(
                {
                    "tweet_id": tweet.id,
                    "keyword": q,
                }
            ))
        values = [(row["tweet_id"], row["keyword"]) for row in data]
        qs = f"""
        INSERT INTO tweet_keywords ({",".join(cols)})
        VALUES ({','.join(['?'] * len(cols))})
        ON CONFLICT(tweet_id,keyword) DO NOTHING
        """
        await executemany(self._db_file, qs, values)
