from datetime import timedelta
from typing import Any, cast

import pytest

from twscrape.accounts_pool import AccountsPool
from twscrape.dashboard import DashboardAuth, DashboardService, resolve_dashboard_credentials
from twscrape.utils import utc


async def test_dashboard_snapshot_exposes_only_safe_fields(pool_mock: AccountsPool):
    await pool_mock.add_account_cookies("ready-user", "auth_token=secret; ct0=csrf-secret")
    account = await pool_mock.get("ready-user")
    account.email = "private@example.com"
    account.proxy = "http://private-proxy"
    account.stats = {"SearchTimeline": 7}
    await pool_mock.save(account)

    snapshot = await DashboardService(pool_mock).snapshot()
    assert snapshot["summary"] == {
        "total": 1,
        "running": 1,
        "ready": 1,
        "cooling": 0,
        "attention": 0,
        "disabled": 0,
        "pool_healthy": True,
        "headline": "账号池正常 · 1/1 个账号可参与轮换",
    }
    item = snapshot["accounts"][0]
    assert item["username"] == "ready-user"
    assert item["status"] == "ready"
    assert item["status_label"] == "可用"
    assert item["has_proxy"] is True
    assert item["total_requests"] == 7
    assert item["requests_by_queue"] == [{"queue": "SearchTimeline", "count": 7}]
    assert "cookies" not in item
    assert "password" not in item
    assert "email" not in item
    assert "proxy" not in item
    assert "secret" not in str(snapshot)


async def test_dashboard_account_actions_are_scoped(pool_mock: AccountsPool):
    await pool_mock.add_account_cookies("first", "auth_token=a; ct0=b")
    await pool_mock.add_account_cookies("second", "auth_token=c; ct0=d")
    first = await pool_mock.get("first")
    second = await pool_mock.get("second")
    first.locks = {"SearchTimeline": utc.now() + timedelta(minutes=10)}
    second.locks = {"SearchTimeline": utc.now() + timedelta(minutes=10)}
    await pool_mock.save(first)
    await pool_mock.save(second)

    service = DashboardService(pool_mock)
    await service.reset_locks("first")
    await service.set_active("first", False)

    assert (await pool_mock.get("first")).locks == {}
    assert (await pool_mock.get("first")).active is False
    assert "SearchTimeline" in (await pool_mock.get("second")).locks
    assert (await pool_mock.get("second")).active is True


async def test_dashboard_updates_cookie_active_and_write_only_proxy(pool_mock: AccountsPool):
    await pool_mock.add_account_cookies("editable", "auth_token=old; ct0=old-csrf")
    service = DashboardService(pool_mock)

    await service.update_account(
        "editable",
        active=False,
        cookies="auth_token=new; ct0=new-csrf",
        proxy_mode="set",
        proxy="127.0.0.1:8080",
    )

    account = await pool_mock.get("editable")
    assert account.cookies == {"auth_token": "new", "ct0": "new-csrf"}
    assert account.active is False
    assert account.proxy == "http://127.0.0.1:8080"
    snapshot = await service.snapshot()
    assert snapshot["accounts"][0]["has_proxy"] is True
    assert "127.0.0.1" not in str(snapshot)

    await service.update_account(
        "editable", active=None, cookies=None, proxy_mode="clear", proxy=None
    )
    assert (await pool_mock.get("editable")).proxy is None


async def test_dashboard_deletes_only_target_account(pool_mock: AccountsPool):
    await pool_mock.add_account_cookies("first", "auth_token=a; ct0=b")
    await pool_mock.add_account_cookies("second", "auth_token=c; ct0=d")

    await DashboardService(pool_mock).delete_account("first")

    assert await pool_mock.get_account("first") is None
    assert await pool_mock.get_account("second") is not None


async def test_dashboard_rejects_invalid_edit_before_writing_cookie(pool_mock: AccountsPool):
    await pool_mock.add_account_cookies("editable", "auth_token=old; ct0=old-csrf")

    with pytest.raises(ValueError, match="代理地址不能超过"):
        await DashboardService(pool_mock).update_account(
            "editable",
            active=False,
            cookies="auth_token=new; ct0=new-csrf",
            proxy_mode="set",
            proxy="x" * 1001,
        )

    account = await pool_mock.get("editable")
    assert account.cookies == {"auth_token": "old", "ct0": "old-csrf"}
    assert account.active is True


async def test_dashboard_snapshot_prioritizes_attention_and_exposes_cooling_details(
    pool_mock: AccountsPool,
):
    await pool_mock.add_account_cookies("cooling", "auth_token=a; ct0=b")
    await pool_mock.add_account_cookies("attention", "auth_token=c; ct0=d")
    cooling = await pool_mock.get("cooling")
    cooling.locks = {"SearchTimeline": utc.now() + timedelta(minutes=10)}
    await pool_mock.save(cooling)
    attention = await pool_mock.get("attention")
    attention.error_msg = "session expired"
    attention.active = False
    await pool_mock.save(attention)

    snapshot = await DashboardService(pool_mock).snapshot()

    assert snapshot["summary"]["attention"] == 1
    assert snapshot["summary"]["cooling"] == 1
    assert snapshot["summary"]["pool_healthy"] is False
    assert snapshot["accounts"][0]["username"] == "attention"
    assert snapshot["accounts"][0]["next_action"] == "add_cookie"
    assert snapshot["accounts"][1]["status"] == "cooling"
    assert snapshot["accounts"][1]["next_unlock_in_seconds"] > 0
    assert snapshot["accounts"][1]["active_locks"][0]["queue"] == "SearchTimeline"


@pytest.mark.parametrize("cookies", ["", "auth_token=only", "ct0=only"])
async def test_dashboard_rejects_incomplete_cookie_sessions(pool_mock: AccountsPool, cookies: str):
    with pytest.raises(ValueError):
        await DashboardService(pool_mock).add_cookie_account("new-user", cookies)


def test_dashboard_auth_session_lifecycle():
    auth = DashboardAuth("admin", "strong-password")

    assert auth.authenticate("127.0.0.1", "admin", "wrong", now=1) is False
    assert auth.authenticate("127.0.0.1", "admin", "strong-password", now=2) is True
    token = auth.create_session(now=2)
    assert auth.validate_session(token, now=3) is True
    auth.revoke_session(token)
    assert auth.validate_session(token, now=4) is False


def test_dashboard_auth_rate_limits_failures():
    auth = DashboardAuth("admin", "strong-password")
    for attempt in range(5):
        assert auth.authenticate("127.0.0.1", "admin", "wrong", now=attempt) is False

    assert auth.is_locked("127.0.0.1", now=5) is True
    assert auth.authenticate("127.0.0.1", "admin", "strong-password", now=5) is False
    assert auth.authenticate("127.0.0.1", "admin", "strong-password", now=306) is True


def test_dashboard_credentials_from_environment(monkeypatch):
    monkeypatch.setenv("TWS_DASHBOARD_USERNAME", "operator")
    monkeypatch.setenv("TWS_DASHBOARD_PASSWORD", "strong-password")

    assert resolve_dashboard_credentials() == ("operator", "strong-password")


def test_dashboard_credentials_reject_short_password(monkeypatch):
    monkeypatch.setenv("TWS_DASHBOARD_PASSWORD", "short")

    with pytest.raises(ValueError, match="至少需要 8"):
        resolve_dashboard_credentials()


def test_dashboard_serves_requests_concurrently(pool_mock: AccountsPool, tmp_path):
    """慢请求不应该互相阻塞。

    改成 ThreadingHTTPServer + 常驻事件循环之前，每个请求各跑一次
    asyncio.run，四个 0.4s 的请求会串行成 1.6s，看板期间完全没响应。
    """
    import asyncio
    import threading
    import time
    import urllib.request

    from twscrape.dashboard import DashboardAuth, DashboardServer

    server = DashboardServer(
        ("127.0.0.1", 0),
        pool_mock,
        DashboardAuth("admin", "password123"),
        str(tmp_path / "test.db"),
    )

    class SlowXApi:
        async def user(self, ident: str, by: str = "username"):
            await asyncio.sleep(0.4)
            return {"id": ident, "by": by}

    server.x_api = cast(Any, SlowXApi())
    _, token = server.runner.run(server.api_keys.create("concurrency-test"))

    serve_thread = threading.Thread(target=server.serve_forever, daemon=True)
    serve_thread.start()
    port = server.server_port
    statuses: list[int] = []

    def hit():
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/user/alice",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            statuses.append(response.status)

    try:
        started = time.monotonic()
        workers = [threading.Thread(target=hit) for _ in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=10)
        elapsed = time.monotonic() - started

        assert statuses == [200, 200, 200, 200]
        assert elapsed < 1.2, f"请求被串行化了，耗时 {elapsed:.2f}s"
    finally:
        server.shutdown()
        serve_thread.join(timeout=5)
        server.server_close()


def test_api_keys_are_scoped_to_read_only_api(pool_mock: AccountsPool, tmp_path):
    import threading
    import urllib.error
    import urllib.request

    from twscrape.dashboard import SESSION_COOKIE, DashboardAuth, DashboardServer

    auth = DashboardAuth("admin", "password123")
    session_token = auth.create_session()
    server = DashboardServer(("127.0.0.1", 0), pool_mock, auth, str(tmp_path / "scope.db"))
    _, api_token = server.runner.run(server.api_keys.create("read-only-client"))
    serve_thread = threading.Thread(target=server.serve_forever, daemon=True)
    serve_thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    def status(path: str, headers: dict[str, str] | None = None) -> int:
        request = urllib.request.Request(f"{base_url}{path}", headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return int(response.status)
        except urllib.error.HTTPError as error:
            return error.code

    try:
        bearer = {"Authorization": f"Bearer {api_token}"}
        session = {"Cookie": f"{SESSION_COOKIE}={session_token}"}

        assert status("/api/_endpoints", bearer) == 200
        assert status("/api/_endpoints", session) == 200
        assert status("/api/_endpoints") == 401
        assert status("/admin/accounts", bearer) == 401
        assert status("/admin/keys", bearer) == 401
        assert status("/admin/keys", session) == 200
    finally:
        server.shutdown()
        serve_thread.join(timeout=5)
        server.server_close()


def test_following_503_reports_retry_after_and_pool_reason(pool_mock: AccountsPool, tmp_path):
    import json
    import threading
    import urllib.error
    import urllib.request

    from twscrape.accounts_pool import NoAccountError
    from twscrape.dashboard import DashboardAuth, DashboardServer

    class ExhaustedXApi:
        async def following(self, ident, limit, by, skip_user):
            raise NoAccountError("exhausted")

    server = DashboardServer(
        ("127.0.0.1", 0),
        pool_mock,
        DashboardAuth("admin", "password123"),
        str(tmp_path / "retry.db"),
    )
    server.x_api = cast(Any, ExhaustedXApi())
    _, api_token = server.runner.run(server.api_keys.create("retry-client"))
    server.runner.run(pool_mock.add_account_cookies("locked", "auth_token=a; ct0=b"))
    server.runner.run(pool_mock.lock_until("locked", "Following", utc.ts() + 120))
    serve_thread = threading.Thread(target=server.serve_forever, daemon=True)
    serve_thread.start()

    def request_error():
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/user/1/following?by=id&skip_user=true",
            headers={"Authorization": f"Bearer {api_token}"},
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=10)
        return caught.value, json.loads(caught.value.read())

    try:
        error, body = request_error()
        assert error.code == 503
        assert 118 <= int(error.headers["Retry-After"]) <= 120
        assert body["reason"] == "rate_limited"
        assert body["retry_after"] == int(error.headers["Retry-After"])

        server.runner.run(pool_mock.set_active("locked", False))
        error, body = request_error()
        assert error.code == 503
        assert error.headers.get("Retry-After") is None
        assert body["reason"] == "no_active_account"
        assert body["retry_after"] is None
    finally:
        server.shutdown()
        serve_thread.join(timeout=5)
        server.server_close()


def test_batch_following_validates_limit_and_preserves_ids(pool_mock: AccountsPool, tmp_path):
    import json
    import threading
    import urllib.error
    import urllib.request

    from twscrape.dashboard import DashboardAuth, DashboardServer

    class BatchXApi:
        calls = []

        async def following_batch(self, ids, limit, skip_user):
            self.calls.append((ids, limit, skip_user))
            return {"results": [{"id": str(uid), "ok": True, "users": [], "count": 0} for uid in ids]}

    server = DashboardServer(
        ("127.0.0.1", 0),
        pool_mock,
        DashboardAuth("admin", "password123"),
        str(tmp_path / "batch.db"),
    )
    fake = BatchXApi()
    server.x_api = cast(Any, fake)
    _, api_token = server.runner.run(server.api_keys.create("batch-client"))
    serve_thread = threading.Thread(target=server.serve_forever, daemon=True)
    serve_thread.start()

    def post(payload):
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/users/following/batch",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    try:
        status, body = post({"ids": [3, "2", 1], "limit": 50, "skip_user": True})
        assert status == 200
        assert [item["id"] for item in body["results"]] == ["3", "2", "1"]
        assert fake.calls == [([3, 2, 1], 50, True)]

        status, body = post({"ids": list(range(1, 102)), "limit": 50})
        assert status == 400
        assert "at most 100" in body["error"]
        assert len(fake.calls) == 1
    finally:
        server.shutdown()
        serve_thread.join(timeout=5)
        server.server_close()


def test_loop_runner_times_out_and_releases_caller():
    import asyncio
    from concurrent.futures import TimeoutError as FutureTimeoutError

    from twscrape.dashboard import LoopRunner

    runner = LoopRunner()
    try:
        with pytest.raises(FutureTimeoutError):
            runner.run(asyncio.sleep(1), timeout=0.01)
        assert runner.run(asyncio.sleep(0, result="ok"), timeout=1) == "ok"
    finally:
        runner.close()


def test_detailed_health_is_authenticated(pool_mock, tmp_path):
    import json
    import threading
    import urllib.error
    import urllib.request

    from twscrape.dashboard import DashboardAuth, DashboardServer

    server = DashboardServer(
        ("127.0.0.1", 0),
        pool_mock,
        DashboardAuth("admin", "password123"),
        str(tmp_path / "health.db"),
    )
    _, api_token = server.runner.run(server.api_keys.create("health-client"))
    serve_thread = threading.Thread(target=server.serve_forever, daemon=True)
    serve_thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    try:
        with urllib.request.urlopen(f"{base_url}/healthz", timeout=10) as response:
            assert json.loads(response.read()) == {"ok": True}

        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{base_url}/api/healthz", timeout=10)
        assert caught.value.code == 401

        request = urllib.request.Request(
            f"{base_url}/api/healthz",
            headers={"Authorization": f"Bearer {api_token}"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read())
        assert body == {
            "ok": True,
            "accounts": {"total": 0, "active": 0, "locked": 0},
            "next_available_in": None,
        }
    finally:
        server.shutdown()
        serve_thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize("trusted_proxy", [False, True])
def test_login_lockout_trusts_cf_ip_only_when_configured(pool_mock, tmp_path, trusted_proxy):
    import json
    import threading
    import urllib.error
    import urllib.request

    from twscrape.dashboard import DashboardAuth, DashboardServer

    server = DashboardServer(
        ("127.0.0.1", 0),
        pool_mock,
        DashboardAuth("admin", "password123"),
        str(tmp_path / f"proxy-{trusted_proxy}.db"),
        trusted_proxy=trusted_proxy,
    )
    serve_thread = threading.Thread(target=server.serve_forever, daemon=True)
    serve_thread.start()

    def login(password, source_ip):
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/auth/login",
            data=json.dumps({"username": "admin", "password": password}).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Twscrape-Token": server.csrf_token,
                "CF-Connecting-IP": source_ip,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    try:
        for _ in range(5):
            login("wrong-password", "203.0.113.10")
        status = login("password123", "203.0.113.11")
        assert status == (200 if trusted_proxy else 429)
    finally:
        server.shutdown()
        serve_thread.join(timeout=5)
        server.server_close()
