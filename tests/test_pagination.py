"""
Regression tests for pagination bugs:
  - #265 / #247: followers() / following() stops early when X returns a promo-only page
    (all entries have entryId starting with "who-to-follow-", leaving els=[] after filter)
"""

import json
import os

from twscrape import API, gather
from twscrape.queue_client import QueueClient

BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "mocked-data")


class FakeRep:
    def __init__(self, data: dict):
        self._data = data

    def json(self):
        return self._data


def make_promo_page(cursor: str | None = "next_cursor"):
    """One page where every real entry is a who-to-follow promo (plus an optional cursor)."""
    entries = [{"entryId": "who-to-follow-123", "content": {}}]
    if cursor:
        entries.append(
            {
                "entryId": "cursor-bottom-1",
                "content": {
                    "__typename": "TimelineTimelineCursor",
                    "cursorType": "Bottom",
                    "entryType": "TimelineTimelineCursor",
                    "value": cursor,
                },
                "sortIndex": "1",
            }
        )
    return {"data": {"entries": entries}}


def make_content_page(entry_id: str, cursor: str):
    return {
        "data": {
            "entries": [
                {"entryId": entry_id, "content": {"itemContent": {}}},
                {
                    "entryId": f"cursor-{cursor}",
                    "content": {
                        "__typename": "TimelineTimelineCursor",
                        "cursorType": "Bottom",
                        "value": cursor,
                    },
                },
            ]
        }
    }


async def test_followers_continues_past_promo_pages(monkeypatch, api_mock: API):
    """followers() must not stop when X returns a page consisting entirely of promo entries."""
    with open(os.path.join(DATA_DIR, "raw_followers.json")) as f:
        users_page = json.load(f)

    # page 1: only who-to-follow entries + cursor  →  els=[] after filter, but cursor exists
    # page 2: real user entries  →  should be reached and parsed
    pages = [make_promo_page(cursor="next_cursor"), users_page]
    idx = 0

    async def mock_get(self, url, params=None):
        nonlocal idx
        if idx >= len(pages):
            return None
        data = pages[idx]
        idx += 1
        return FakeRep(data)

    monkeypatch.setattr(QueueClient, "get", mock_get)

    users = await gather(api_mock.followers(123))

    assert idx >= 2, (
        f"pagination stopped after {idx} page(s); promo-only page should not terminate pagination"
    )
    assert len(users) > 0, "expected users from page 2 but got none"


async def test_following_continues_past_promo_pages(monkeypatch, api_mock: API):
    """following() must not stop when X returns a page consisting entirely of promo entries."""
    with open(os.path.join(DATA_DIR, "raw_following.json")) as f:
        users_page = json.load(f)

    pages = [make_promo_page(cursor="next_cursor"), users_page]
    idx = 0

    async def mock_get(self, url, params=None):
        nonlocal idx
        if idx >= len(pages):
            return None
        data = pages[idx]
        idx += 1
        return FakeRep(data)

    monkeypatch.setattr(QueueClient, "get", mock_get)

    users = await gather(api_mock.following(123))

    assert idx >= 2, (
        f"pagination stopped after {idx} page(s); promo-only page should not terminate pagination"
    )
    assert len(users) > 0, "expected users from page 2 but got none"


async def test_followers_stops_after_too_many_consecutive_empty_pages(monkeypatch, api_mock: API):
    """Safeguard: if X returns many consecutive promo-only pages with cursors, pagination must stop."""
    idx = 0

    async def mock_get(self, url, params=None):
        nonlocal idx
        idx += 1
        return FakeRep(make_promo_page(cursor=f"cursor_{idx}"))

    monkeypatch.setattr(QueueClient, "get", mock_get)

    users = await gather(api_mock.followers(123))

    assert len(users) == 0
    assert idx < 10, f"too many requests ({idx}); should have stopped after a few empty pages"


async def test_gql_items_stops_on_repeated_cursor(monkeypatch, api_mock: API):
    page = make_content_page("user-1", "same-cursor")
    calls = 0

    async def mock_get(self, url, params=None):
        nonlocal calls
        calls += 1
        return FakeRep(page)

    monkeypatch.setattr(QueueClient, "get", mock_get)
    reps = [x async for x in api_mock._gql_items("hash/Followers", {})]

    assert len(reps) == 1
    assert calls == 2


async def test_search_stops_on_repeated_page_with_new_cursor(monkeypatch, api_mock: API):
    pages = [
        make_content_page("tweet-1", "cursor-1"),
        make_content_page("tweet-1", "cursor-2"),
    ]
    calls = 0

    async def mock_get(self, url, params=None):
        nonlocal calls
        page = pages[min(calls, len(pages) - 1)]
        calls += 1
        return FakeRep(page)

    monkeypatch.setattr(QueueClient, "get", mock_get)
    reps = [x async for x in api_mock._gql_items("hash/SearchTimeline", {})]

    assert len(reps) == 1
    assert calls == 2
