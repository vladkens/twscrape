import pytest

from twscrape import telemetry

URL = "https://x.com/i/api/graphql/id/SearchTimeline"


@pytest.fixture(autouse=True)
def allow_telemetry(monkeypatch):
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    monkeypatch.delenv("TWS_TELEMETRY", raising=False)


def telemetry_events():
    return telemetry.snapshot()


def find_event(name: str, **properties):
    for event in telemetry_events():
        if event["event"] != name:
            continue

        props = event["properties"]
        if all(props.get(k) == v for k, v in properties.items()):
            return event

    raise AssertionError(f"Event not found: {name} {properties}")


async def test_telemetry_tracks_gql_request(client_fixture):
    _, client, mock = client_fixture
    mock.backend = "httpx"
    mock.add_response(json={"ok": True})

    await client.__aenter__()
    rep = await client.get(URL)
    await client.__aexit__(None, None, None)

    assert rep is not None
    event = find_event(
        "gql_request",
        operation="SearchTimeline",
        http_method="GET",
        http_backend="httpx",
        source="lib",
    )

    assert event["count"] == 1
    assert event["properties"]["$lib"] == "twscrape"
    assert event["properties"]["$process_person_profile"] is False
    assert event["properties"]["$session_id"]
    assert event["properties"]["distinct_id"]
    assert event["properties"]["app_version"]
    assert event["properties"]["platform"]
    assert event["properties"]["python"]
    assert event["properties"]["$current_url"] == "lib://twscrape/gql/SearchTimeline"


async def test_telemetry_tracks_cli_source_on_gql_request(client_fixture):
    _, client, mock = client_fixture
    mock.backend = "curl"
    mock.add_response(json={"ok": True})
    telemetry.set_source("cli")

    await client.__aenter__()
    rep = await client.get(URL)
    await client.__aexit__(None, None, None)

    assert rep is not None
    event = find_event(
        "gql_request",
        operation="SearchTimeline",
        http_method="GET",
        http_backend="curl",
        source="cli",
    )

    assert event["count"] == 1
    assert event["properties"]["$lib"] == "twscrape"
    assert event["properties"]["$process_person_profile"] is False
    assert event["properties"]["$session_id"]
    assert event["properties"]["distinct_id"]
    assert event["properties"]["app_version"]
    assert event["properties"]["platform"]
    assert event["properties"]["python"]
    assert event["properties"]["$current_url"] == "cli://twscrape/gql/SearchTimeline"


def test_telemetry_capture_aggregates_events():
    telemetry.capture("gql_request", {"operation": "SearchTimeline", "http_backend": "httpx"})
    telemetry.capture("gql_request", {"operation": "SearchTimeline", "http_backend": "httpx"})

    event = find_event("gql_request", operation="SearchTimeline", http_backend="httpx")
    assert event["count"] == 2
    assert event["properties"]["$lib"] == "twscrape"
    assert event["properties"]["$process_person_profile"] is False
    assert event["properties"]["$session_id"]
    assert event["properties"]["distinct_id"]
    assert event["properties"]["app_version"]
    assert event["properties"]["platform"]
    assert event["properties"]["python"]


def test_telemetry_aggregation_ignores_identity_properties(monkeypatch):
    monkeypatch.setattr(telemetry, "_distinct_id", lambda: "first")
    telemetry.capture("gql_request", {"operation": "SearchTimeline", "http_backend": "httpx"})

    monkeypatch.setattr(telemetry, "_distinct_id", lambda: "second")
    telemetry.capture("gql_request", {"operation": "SearchTimeline", "http_backend": "httpx"})

    events = telemetry.snapshot()
    assert len(events) == 1
    assert events[0]["count"] == 2
    assert events[0]["properties"]["distinct_id"] == "second"


def test_telemetry_respects_opt_out(monkeypatch):
    monkeypatch.setenv("TWS_TELEMETRY", "0")
    telemetry.capture("gql_request", {"operation": "SearchTimeline"})
    assert telemetry.snapshot() == []


def test_telemetry_respects_do_not_track(monkeypatch):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    telemetry.capture("gql_request", {"operation": "SearchTimeline"})
    assert telemetry.snapshot() == []


async def test_telemetry_flush_sends_aggregated_batch(monkeypatch):
    requests = []

    class MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, *, json, timeout):
            requests.append({"url": url, "json": json, "timeout": timeout})

    monkeypatch.setattr(telemetry, "POSTHOG_KEY", "test-key")
    monkeypatch.setattr(telemetry.httpx, "AsyncClient", MockClient)

    telemetry.capture("gql_request", {"operation": "SearchTimeline", "http_backend": "httpx"})
    telemetry.capture("gql_request", {"operation": "SearchTimeline", "http_backend": "httpx"})

    await telemetry.flush()

    assert telemetry.snapshot() == []
    assert len(requests) == 1
    assert requests[0]["url"] == telemetry.POSTHOG_BATCH_URL
    assert requests[0]["timeout"] == 5

    payload = requests[0]["json"]
    assert payload["api_key"] == "test-key"
    assert len(payload["batch"]) == 1

    item = payload["batch"][0]
    assert item["event"] == "gql_request"
    assert item["distinct_id"]
    assert item["timestamp"]
    assert item["properties"]["operation"] == "SearchTimeline"
    assert item["properties"]["http_backend"] == "httpx"
    assert item["properties"]["count"] == 2


async def test_telemetry_flush_without_key_clears_events():
    telemetry.capture("gql_request", {"operation": "SearchTimeline"})
    await telemetry.flush()
    assert telemetry.snapshot() == []


async def test_telemetry_flush_swallows_errors(monkeypatch):
    class MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, *, json, timeout):
            raise RuntimeError("boom")

    monkeypatch.setattr(telemetry, "POSTHOG_KEY", "test-key")
    monkeypatch.setattr(telemetry.httpx, "AsyncClient", MockClient)

    telemetry.capture("gql_request", {"operation": "SearchTimeline"})
    await telemetry.flush()
    assert telemetry.snapshot() == []
