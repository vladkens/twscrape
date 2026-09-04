import argparse
import asyncio
import getpass
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Any, TypedDict
from urllib.parse import parse_qs, unquote, urlparse

from .accounts_pool import AccountsPool, NoAccountError
from .api_keys import ApiKeyStore
from .utils import get_env_bool, parse_proxy, utc
from .x_api import (
    XApiNotFoundError,
    XApiService,
    XApiUnavailableError,
    parse_bool,
    parse_by,
    parse_limit,
)

SESSION_COOKIE = "twscrape_session"
SESSION_TTL_SECONDS = 12 * 60 * 60
LOGIN_WINDOW_SECONDS = 5 * 60
LOGIN_LOCK_SECONDS = 5 * 60
MAX_LOGIN_FAILURES = 5


class DashboardAccountInfo(TypedDict):
    username: str
    active: bool
    has_session: bool
    has_proxy: bool
    login_method: str
    status: str
    status_label: str
    status_detail: str
    needs_attention: bool
    attention_reason: str | None
    next_action: str
    lock_count: int
    locked_queues: list[str]
    active_locks: list[dict[str, Any]]
    next_unlock_at: str | None
    next_unlock_in_seconds: int | None
    total_requests: int
    requests_by_queue: list[dict[str, Any]]
    last_used: str | None
    error_message: str | None


class DashboardAccountNotFoundError(ValueError):
    pass


def api_endpoint_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": "用户资料",
            "method": "GET",
            "path": "/api/user/{name}",
            "description": "获取公开资料；by=id 时路径参数按数字 ID 解析",
            "params": [
                {"name": "name", "in": "path", "required": True, "example": "xdevelopers"},
                {"name": "by", "in": "query", "required": False, "example": "id"},
            ],
        },
        {
            "name": "用户推文",
            "method": "GET",
            "path": "/api/user/{name}/tweets",
            "description": "获取用户时间线，可选择包含回复",
            "params": [
                {"name": "name", "in": "path", "required": True, "example": "xdevelopers"},
                {"name": "limit", "in": "query", "required": False, "example": "20"},
                {
                    "name": "include_replies",
                    "in": "query",
                    "required": False,
                    "example": "false",
                },
                {"name": "by", "in": "query", "required": False, "example": "id"},
            ],
        },
        {
            "name": "关注者列表",
            "method": "GET",
            "path": "/api/user/{name}/followers",
            "description": "获取关注该用户的账号；by=id 可按数字 ID 查询，skip_user=true 省去一次资料查询",
            "params": [
                {"name": "name", "in": "path", "required": True, "example": "xdevelopers"},
                {"name": "limit", "in": "query", "required": False, "example": "20"},
                {"name": "by", "in": "query", "required": False, "example": "id"},
                {"name": "skip_user", "in": "query", "required": False, "example": "true"},
            ],
        },
        {
            "name": "关注列表",
            "method": "GET",
            "path": "/api/user/{name}/following",
            "description": "获取该用户正在关注的账号；by=id 可按数字 ID 查询，skip_user=true 省去一次资料查询",
            "params": [
                {"name": "name", "in": "path", "required": True, "example": "xdevelopers"},
                {"name": "limit", "in": "query", "required": False, "example": "20"},
                {"name": "by", "in": "query", "required": False, "example": "id"},
                {"name": "skip_user", "in": "query", "required": False, "example": "true"},
            ],
        },
        {
            "name": "单条推文",
            "method": "GET",
            "path": "/api/tweet/{id}",
            "description": "按推文 ID 获取详情",
            "params": [{"name": "id", "in": "path", "required": True, "example": "20"}],
        },
        {
            "name": "搜索推文",
            "method": "GET",
            "path": "/api/search",
            "description": "使用 X 搜索语法查询推文",
            "params": [
                {"name": "q", "in": "query", "required": True, "example": "python lang:en"},
                {"name": "limit", "in": "query", "required": False, "example": "20"},
            ],
        },
        {
            "name": "账号池健康",
            "method": "GET",
            "path": "/api/healthz",
            "description": "检查账号池数量、锁定状态和 Following 队列可用时间",
            "params": [],
        },
    ]


class DashboardAuth:
    """Single-user, in-memory authentication for the local dashboard."""

    def __init__(self, username: str, password: str):
        self.username = username
        self._salt = secrets.token_bytes(16)
        self._password_digest = self._derive(password)
        self._sessions: dict[str, float] = {}
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}

    def _derive(self, password: str) -> bytes:
        return hashlib.scrypt(password.encode(), salt=self._salt, n=2**14, r=8, p=1, dklen=32)

    def is_locked(self, client: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return self._locked_until.get(client, 0) > now

    def authenticate(
        self, client: str, username: str, password: str, now: float | None = None
    ) -> bool:
        now = time.time() if now is None else now
        if self.is_locked(client, now):
            return False

        username_ok = hmac.compare_digest(username, self.username)
        password_ok = hmac.compare_digest(self._derive(password), self._password_digest)
        if username_ok and password_ok:
            self._failures.pop(client, None)
            self._locked_until.pop(client, None)
            return True

        failures = [
            timestamp
            for timestamp in self._failures.get(client, [])
            if timestamp > now - LOGIN_WINDOW_SECONDS
        ]
        failures.append(now)
        self._failures[client] = failures
        if len(failures) >= MAX_LOGIN_FAILURES:
            self._locked_until[client] = now + LOGIN_LOCK_SECONDS
            self._failures.pop(client, None)
        return False

    def create_session(self, now: float | None = None) -> str:
        now = time.time() if now is None else now
        token = secrets.token_urlsafe(32)
        self._sessions[self._token_digest(token)] = now + SESSION_TTL_SECONDS
        return token

    def validate_session(self, token: str | None, now: float | None = None) -> bool:
        if not token:
            return False
        now = time.time() if now is None else now
        digest = self._token_digest(token)
        expires_at = self._sessions.get(digest, 0)
        if expires_at <= now:
            self._sessions.pop(digest, None)
            return False
        return True

    def revoke_session(self, token: str | None) -> None:
        if token:
            self._sessions.pop(self._token_digest(token), None)

    @staticmethod
    def _token_digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()


def resolve_dashboard_credentials() -> tuple[str, str]:
    username = os.getenv("TWS_DASHBOARD_USERNAME", "admin").strip()
    if not username:
        raise ValueError("TWS_DASHBOARD_USERNAME 不能为空")

    password = os.getenv("TWS_DASHBOARD_PASSWORD")
    if password is None:
        if not sys.stdin.isatty():
            raise ValueError("非交互启动时必须设置 TWS_DASHBOARD_PASSWORD")
        password = getpass.getpass("Dashboard password: ")
        confirmation = getpass.getpass("Confirm dashboard password: ")
        if not hmac.compare_digest(password, confirmation):
            raise ValueError("两次输入的 Dashboard 密码不一致")
    if len(password) < 8:
        raise ValueError("Dashboard 密码至少需要 8 个字符")
    return username, password


class DashboardService:
    """Small, safe facade around AccountsPool for the local dashboard."""

    def __init__(self, pool: AccountsPool):
        self.pool = pool

    async def api_health(self) -> dict[str, Any]:
        accounts = await self.pool.get_all()
        now = utc.now()
        active = [account for account in accounts if account.active]
        locked = sum(
            1 for account in active if any(unlock_at > now for unlock_at in account.locks.values())
        )
        return {
            "ok": True,
            "accounts": {"total": len(accounts), "active": len(active), "locked": locked},
            "next_available_in": await self.pool.next_available_in("Following"),
        }

    async def snapshot(self) -> dict[str, Any]:
        accounts = await self.pool.get_all()
        now = utc.now()
        items: list[DashboardAccountInfo] = []

        for account in accounts:
            active_locks = {
                queue: unlock_at for queue, unlock_at in account.locks.items() if unlock_at > now
            }
            if account.error_msg:
                status = "attention"
                status_label = "需处理"
                status_detail = str(account.error_msg)[:120]
                attention_reason = "auth_error"
                next_action = "add_cookie"
            elif not account.active:
                status = "disabled"
                status_label = "已停用"
                status_detail = "手动停用，不参与账号轮换"
                attention_reason = None
                next_action = "enable"
            elif not account.has_session:
                status = "attention"
                status_label = "需处理"
                status_detail = "会话缺失，请重新添加 Cookie"
                attention_reason = "session_missing"
                next_action = "add_cookie"
            elif active_locks:
                status = "cooling"
                status_label = "冷却中"
                status_detail = f"{len(active_locks)} 个端点正在等待限流恢复"
                attention_reason = None
                next_action = "none"
            else:
                status = "ready"
                status_label = "可用"
                status_detail = "可参与账号轮换"
                attention_reason = None
                next_action = "none"

            next_unlock = min(active_locks.values()) if active_locks else None
            lock_items = [
                {"queue": queue, "unlock_at": unlock_at.isoformat()}
                for queue, unlock_at in sorted(active_locks.items())
            ]
            request_items = [
                {"queue": queue, "count": count}
                for queue, count in sorted(
                    account.stats.items(), key=lambda item: (-item[1], item[0])
                )
            ]
            needs_attention = status == "attention"

            items.append(
                {
                    "username": account.username,
                    "active": account.active,
                    "has_session": account.has_session,
                    "has_proxy": bool(account.proxy),
                    "login_method": account.login_method,
                    "status": status,
                    "status_label": status_label,
                    "status_detail": status_detail,
                    "needs_attention": needs_attention,
                    "attention_reason": attention_reason,
                    "next_action": next_action,
                    "lock_count": len(active_locks),
                    "locked_queues": sorted(active_locks),
                    "active_locks": lock_items,
                    "next_unlock_at": next_unlock.isoformat() if next_unlock else None,
                    "next_unlock_in_seconds": max(int((next_unlock - now).total_seconds()), 0)
                    if next_unlock
                    else None,
                    "total_requests": sum(account.stats.values()),
                    "requests_by_queue": request_items,
                    "last_used": account.last_used.isoformat() if account.last_used else None,
                    "error_message": str(account.error_msg)[:120] if account.error_msg else None,
                }
            )

        priority = {"attention": 0, "cooling": 1, "ready": 2, "disabled": 3}
        items.sort(key=lambda item: (priority[item["status"]], item["username"].lower()))
        ready = sum(1 for item in items if item["status"] == "ready")
        cooling = sum(1 for item in items if item["status"] == "cooling")
        attention = sum(1 for item in items if item["status"] == "attention")
        disabled = sum(1 for item in items if item["status"] == "disabled")
        running = ready + cooling
        total = len(items)
        if total == 0:
            headline = "还没有账号 · 添加一个 Cookie 就能开始抓取"
        elif attention:
            headline = f"{attention} 个账号需要处理 · {running}/{total} 个账号可参与轮换"
        elif running == 0:
            headline = "账号池不可用 · 没有可参与轮换的账号"
        elif ready == 0:
            headline = f"{cooling} 个账号正在冷却 · 等待限流恢复"
        else:
            headline = f"账号池正常 · {running}/{total} 个账号可参与轮换"
        return {
            "summary": {
                "total": total,
                "running": running,
                "ready": ready,
                "cooling": cooling,
                "attention": attention,
                "disabled": disabled,
                "pool_healthy": attention == 0 and running > 0,
                "headline": headline,
            },
            "accounts": items,
            "updated_at": datetime.now().astimezone().isoformat(),
        }

    async def add_cookie_account(self, username: str, cookies: str) -> None:
        username = username.strip()
        cookies = cookies.strip()
        if not username:
            raise ValueError("请输入账号名称")
        if len(username) > 80:
            raise ValueError("账号名称不能超过 80 个字符")
        if not cookies:
            raise ValueError("请输入 Cookie")
        await self.pool.add_account_cookies(username, cookies)

    async def set_active(self, username: str, active: bool) -> None:
        if await self.pool.get_account(username) is None:
            raise DashboardAccountNotFoundError("账号不存在")
        await self.pool.set_active(username, active)

    async def reset_locks(self, username: str) -> None:
        if await self.pool.get_account(username) is None:
            raise DashboardAccountNotFoundError("账号不存在")
        await self.pool.reset_locks(username)

    async def update_account(
        self,
        username: str,
        *,
        active: bool | None,
        cookies: str | None,
        proxy_mode: str,
        proxy: str | None,
    ) -> None:
        account = await self.pool.get_account(username)
        if account is None:
            raise DashboardAccountNotFoundError("账号不存在")

        cookies = cookies.strip() if cookies is not None else None
        next_proxy = account.proxy
        if proxy_mode == "set":
            proxy = proxy.strip() if proxy is not None else ""
            if not proxy:
                raise ValueError("请输入代理地址")
            if len(proxy) > 1000:
                raise ValueError("代理地址不能超过 1000 个字符")
            next_proxy = parse_proxy(proxy)
        elif proxy_mode == "clear":
            next_proxy = None
        elif proxy_mode != "keep":
            raise ValueError("proxy_mode 必须是 keep、set 或 clear")

        if cookies:
            await self.pool.add_account_cookies(username, cookies)
            account = await self.pool.get(username)

        account.proxy = next_proxy
        if active is not None:
            account.active = active
        await self.pool.save(account)

    async def delete_account(self, username: str) -> None:
        if await self.pool.get_account(username) is None:
            raise DashboardAccountNotFoundError("账号不存在")
        await self.pool.delete_accounts(username)


class LoopRunner:
    """后台常驻事件循环。

    原先每个请求各跑一次 asyncio.run，一是慢请求会把整个服务卡死，二是
    换成多线程后 twscrape 内部那个模块级 asyncio.Lock 会横跨多个事件循环，
    唤醒等待者时必然出错。所以改成：一个常驻循环 + 多线程 HTTP，
    请求线程把协程提交进来等结果。
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="twscrape-loop", daemon=True
        )
        self._thread.start()

    def run(self, coroutine: Any, timeout: float | None = 60.0) -> Any:
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            return future.result(timeout)
        except FutureTimeoutError:
            future.cancel()
            raise

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        self._loop.close()


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        pool: AccountsPool,
        auth: DashboardAuth,
        db_file: str,
        trusted_proxy: bool = False,
    ):
        self.runner = LoopRunner()
        super().__init__(address, DashboardHandler)
        self.service = DashboardService(pool)
        self.x_api = XApiService(pool)
        self.api_keys = ApiKeyStore(db_file)
        self.auth = auth
        self.trusted_proxy = trusted_proxy
        self.csrf_token = secrets.token_urlsafe(32)

    def server_close(self) -> None:
        super().server_close()
        self.runner.close()


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardServer

    def log_message(self, format: str, *args: Any) -> None:
        # Keep request bodies and credentials out of logs.
        print(f"[dashboard] {self.address_string()} - {format % args}")

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'",
        )

    def _send_bytes(
        self,
        body: bytes,
        content_type: str,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(
        self, payload: Any, status: int = 200, headers: dict[str, str] | None = None
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self._send_bytes(body, "application/json; charset=utf-8", status, headers)

    def _redirect(self, location: str) -> None:
        self._send_bytes(b"", "text/plain; charset=utf-8", HTTPStatus.FOUND, {"Location": location})

    def _read_json(self) -> dict[str, Any]:
        if self.headers.get_content_type() != "application/json":
            raise ValueError("请求格式必须为 JSON")
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_000_000:
            raise ValueError("请求内容为空或过大")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("请求格式无效")
        return payload

    def _allow_mutation(self) -> bool:
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        same_origin = origin in {None, f"http://{host}"}
        return same_origin and secrets.compare_digest(
            self.headers.get("X-Twscrape-Token", ""), self.server.csrf_token
        )

    def _session_token(self) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        try:
            cookies = SimpleCookie()
            cookies.load(raw)
            morsel = cookies.get(SESSION_COOKIE)
            return str(morsel.value) if morsel is not None else None
        except CookieError:
            return None

    def _is_authenticated(self) -> bool:
        return self.server.auth.validate_session(self._session_token())

    def _require_session_auth(self) -> bool:
        if self._is_authenticated():
            return True
        self._send_json({"error": "Authentication required"}, HTTPStatus.UNAUTHORIZED)
        return False

    def _bearer_token(self) -> str | None:
        scheme, separator, token = self.headers.get("Authorization", "").partition(" ")
        if not separator or scheme.casefold() != "bearer":
            return None
        return token.strip()

    def _require_data_api_auth(self) -> bool:
        if self._is_authenticated():
            return True
        token = self._bearer_token()
        if token and self._run(self.server.api_keys.validate(token)):
            return True
        self._send_json(
            {"error": "Dashboard session or valid API key required"},
            HTTPStatus.UNAUTHORIZED,
        )
        return False

    def _run(self, coroutine: Any, timeout: float | None = 60.0) -> Any:
        return self.server.runner.run(coroutine, timeout)

    def _client_identity(self) -> str:
        if self.server.trusted_proxy:
            forwarded = self.headers.get("CF-Connecting-IP", "").strip()
            try:
                if forwarded:
                    return str(ipaddress.ip_address(forwarded))
            except ValueError:
                pass
        return self.client_address[0]

    def _send_no_account(self, queue: str) -> None:
        retry_after = self._run(self.server.service.pool.next_available_in(queue))
        reason = "rate_limited" if retry_after is not None else "no_active_account"
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        self._send_json(
            {
                "error": "No active account is available",
                "retry_after": retry_after,
                "reason": reason,
            },
            HTTPStatus.SERVICE_UNAVAILABLE,
            headers,
        )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/healthz":
            self._send_json({"ok": True})
            return
        assets = files("twscrape").joinpath("dashboard_assets")
        if path == "/dashboard.css":
            self._send_bytes(
                assets.joinpath("dashboard.css").read_bytes(), "text/css; charset=utf-8"
            )
            return
        if path == "/dashboard.js":
            self._send_bytes(
                assets.joinpath("dashboard.js").read_bytes(), "text/javascript; charset=utf-8"
            )
            return
        if path == "/console.js":
            self._send_bytes(
                assets.joinpath("console.js").read_bytes(), "text/javascript; charset=utf-8"
            )
            return
        if path == "/login.js":
            self._send_bytes(
                assets.joinpath("login.js").read_bytes(), "text/javascript; charset=utf-8"
            )
            return
        if path == "/":
            if self._is_authenticated():
                self._redirect("/accounts")
                return
            path = "/login"
        if path == "/login" and self._is_authenticated():
            self._redirect("/accounts")
            return
        if path in {"/accounts", "/console", "/login"}:
            page = (
                "login.html"
                if path == "/login" or not self._is_authenticated()
                else "console.html"
                if path == "/console"
                else "index.html"
            )
            html = assets.joinpath(page).read_text(encoding="utf-8")
            html = html.replace("__CSRF_TOKEN__", self.server.csrf_token)
            self._send_bytes(html.encode(), "text/html; charset=utf-8")
            return
        if path == "/auth/session":
            if not self._require_session_auth():
                return
            self._send_json({"authenticated": True, "username": self.server.auth.username})
            return
        if path == "/admin/accounts":
            if not self._require_session_auth():
                return
            self._send_json(self._run(self.server.service.snapshot()))
            return
        if path == "/admin/keys":
            if not self._require_session_auth():
                return
            self._send_json({"keys": self._run(self.server.api_keys.list())})
            return
        if (
            path == "/api"
            or path == "/api/_endpoints"
            or path == "/api/healthz"
            or path.startswith(("/api/user/", "/api/tweet/"))
            or path == "/api/search"
        ) and not self._require_data_api_auth():
            return
        if path == "/api":
            self._send_json(
                {
                    "name": "twscrape JSON API",
                    "read_only": True,
                    "endpoints": api_endpoint_catalog(),
                }
            )
            return
        if path == "/api/_endpoints":
            self._send_json({"endpoints": api_endpoint_catalog()})
            return
        if path == "/api/healthz":
            self._send_json(self._run(self.server.service.api_health()))
            return
        if path.startswith(("/api/user/", "/api/tweet/")) or path == "/api/search":
            self._handle_x_api(parsed)
            return

        if not self._require_session_auth():
            return
        self._send_json({"error": "页面不存在"}, HTTPStatus.NOT_FOUND)

    def _handle_x_api(self, parsed: Any) -> None:
        path = parsed.path
        query = parse_qs(parsed.query)
        queue = "SearchTimeline"
        try:
            limit = parse_limit(query.get("limit", [None])[0])
            if path == "/api/search":
                search_query = query.get("q", [""])[0]
                self._send_json(self._run(self.server.x_api.search(search_query, limit)))
                return

            by = parse_by(query.get("by", [None])[0])

            parts = [unquote(part) for part in path.split("/") if part]
            if len(parts) == 3 and parts[:2] == ["api", "user"]:
                queue = "UserByRestId" if by == "id" else "UserByScreenName"
                self._send_json(self._run(self.server.x_api.user(parts[2], by)))
                return
            if len(parts) == 4 and parts[:2] == ["api", "user"] and parts[3] == "tweets":
                include_replies = parse_bool(query.get("include_replies", [None])[0])
                queue = "UserTweetsAndReplies" if include_replies else "UserTweets"
                self._send_json(
                    self._run(
                        self.server.x_api.user_tweets(parts[2], limit, include_replies, by)
                    )
                )
                return
            if (
                len(parts) == 4
                and parts[:2] == ["api", "user"]
                and parts[3] in {"followers", "following"}
            ):
                skip_user = parse_bool(query.get("skip_user", [None])[0], name="skip_user")
                queue = "Followers" if parts[3] == "followers" else "Following"
                method = getattr(self.server.x_api, parts[3])
                self._send_json(self._run(method(parts[2], limit, by, skip_user)))
                return
            if len(parts) == 3 and parts[:2] == ["api", "tweet"]:
                queue = "TweetDetail"
                try:
                    tweet_id = int(parts[2])
                except ValueError as error:
                    raise ValueError("tweet id must be an integer") from error
                if tweet_id <= 0:
                    raise ValueError("tweet id must be positive")
                self._send_json(self._run(self.server.x_api.tweet(tweet_id)))
                return
            self._send_json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)
        except XApiNotFoundError as error:
            self._send_json({"error": str(error)}, HTTPStatus.NOT_FOUND)
        except XApiUnavailableError as error:
            self._send_json({"error": str(error), "reason": error.reason}, HTTPStatus.FORBIDDEN)
        except NoAccountError:
            self._send_no_account(queue)
        except FutureTimeoutError:
            self._send_json({"error": "Upstream X request timed out"}, HTTPStatus.GATEWAY_TIMEOUT)
        except ValueError as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception:
            self._send_json({"error": "Upstream X request failed"}, HTTPStatus.BAD_GATEWAY)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/users/following/batch":
            if not self._require_data_api_auth():
                return
            self._handle_following_batch()
            return
        if path == "/auth/login":
            self._handle_login()
            return
        if not self._require_session_auth():
            return
        if path == "/auth/logout":
            self._handle_logout()
            return
        self._handle_mutation("POST")

    def _handle_following_batch(self) -> None:
        try:
            payload = self._read_json()
            if unknown := set(payload) - {"ids", "limit", "skip_user"}:
                raise ValueError(f"Unsupported fields: {', '.join(sorted(unknown))}")
            raw_ids = payload.get("ids")
            if not isinstance(raw_ids, list) or not raw_ids:
                raise ValueError("ids must be a non-empty array")
            if len(raw_ids) > 100:
                raise ValueError("ids must contain at most 100 items")
            ids: list[int] = []
            for value in raw_ids:
                if isinstance(value, bool) or not isinstance(value, (int, str)):
                    raise ValueError("each id must be a positive integer")
                text = str(value)
                if not text.isdigit() or int(text) <= 0:
                    raise ValueError("each id must be a positive integer")
                ids.append(int(text))
            limit_value = payload.get("limit", 20)
            if isinstance(limit_value, bool):
                raise ValueError("limit must be an integer")
            limit = parse_limit(str(limit_value))
            skip_user = payload.get("skip_user", True)
            if not isinstance(skip_user, bool):
                raise ValueError("skip_user must be true or false")
            timeout = max(60.0, len(ids) * 30.0)
            result = self._run(
                self.server.x_api.following_batch(ids, limit, skip_user), timeout=timeout
            )
            self._send_json(result)
        except NoAccountError:
            self._send_no_account("Following")
        except FutureTimeoutError:
            self._send_json({"error": "Upstream X request timed out"}, HTTPStatus.GATEWAY_TIMEOUT)
        except (ValueError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception:
            self._send_json({"error": "Upstream X request failed"}, HTTPStatus.BAD_GATEWAY)

    def do_PATCH(self) -> None:
        if not self._require_session_auth():
            return
        self._handle_mutation("PATCH")

    def do_DELETE(self) -> None:
        if not self._require_session_auth():
            return
        self._handle_mutation("DELETE")

    def _handle_login(self) -> None:
        if not self._allow_mutation():
            self._send_json({"error": "请求校验失败，请刷新页面后重试"}, HTTPStatus.FORBIDDEN)
            return
        client = self._client_identity()
        if self.server.auth.is_locked(client):
            self._send_json(
                {"error": "登录尝试过多，请 5 分钟后重试"}, HTTPStatus.TOO_MANY_REQUESTS
            )
            return
        try:
            payload = self._read_json()
            username = str(payload.get("username", ""))
            password = str(payload.get("password", ""))
            if len(username) > 80 or len(password) > 1024:
                raise ValueError("登录信息过长")
        except (ValueError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if not self.server.auth.authenticate(client, username, password):
            status = (
                HTTPStatus.TOO_MANY_REQUESTS
                if self.server.auth.is_locked(client)
                else HTTPStatus.UNAUTHORIZED
            )
            message = "登录尝试过多，请 5 分钟后重试" if status == 429 else "用户名或密码错误"
            self._send_json({"error": message}, status)
            return
        token = self.server.auth.create_session()
        cookie = (
            f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; "
            f"Max-Age={SESSION_TTL_SECONDS}"
        )
        self._send_json({"ok": True}, headers={"Set-Cookie": cookie})

    def _handle_logout(self) -> None:
        if not self._allow_mutation():
            self._send_json({"error": "请求校验失败，请刷新页面后重试"}, HTTPStatus.FORBIDDEN)
            return
        self.server.auth.revoke_session(self._session_token())
        cookie = f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
        self._send_json({"ok": True}, headers={"Set-Cookie": cookie})

    def _handle_mutation(self, method: str) -> None:
        if not self._allow_mutation():
            self._send_json({"error": "请求校验失败，请刷新页面后重试"}, HTTPStatus.FORBIDDEN)
            return

        path = urlparse(self.path).path
        try:
            payload = self._read_json()
            if method == "POST" and path == "/admin/keys":
                if set(payload) - {"name"}:
                    raise ValueError("不支持的字段")
                name = payload.get("name")
                if not isinstance(name, str):
                    raise ValueError("密钥名称必须是字符串")
                info, token = self._run(self.server.api_keys.create(name))
                self._send_json({"key": info, "token": token}, HTTPStatus.CREATED)
                return

            if method == "POST" and path == "/admin/accounts":
                self._run(
                    self.server.service.add_cookie_account(
                        str(payload.get("username", "")), str(payload.get("cookies", ""))
                    )
                )
                self._send_json({"ok": True}, HTTPStatus.CREATED)
                return

            parts = [unquote(part) for part in path.split("/") if part]
            if method == "DELETE" and len(parts) == 3 and parts[:2] == ["admin", "keys"]:
                confirm_name = payload.get("confirm_name")
                if not isinstance(confirm_name, str):
                    raise ValueError("请输入完整密钥名称确认撤销")
                if not self._run(self.server.api_keys.revoke(parts[2], confirm_name)):
                    self._send_json({"error": "密钥不存在或已撤销"}, HTTPStatus.NOT_FOUND)
                    return
                self._send_json({"ok": True})
                return
            if len(parts) >= 3 and parts[:2] == ["admin", "accounts"]:
                username = parts[2]
                if method == "PATCH" and len(parts) == 3:
                    allowed = {"active", "cookies", "proxy_mode", "proxy"}
                    if unknown := set(payload) - allowed:
                        raise ValueError(f"不支持的字段: {', '.join(sorted(unknown))}")
                    active = payload.get("active")
                    if active is not None and not isinstance(active, bool):
                        raise ValueError("active 必须是布尔值")
                    cookies = payload.get("cookies")
                    if cookies is not None and not isinstance(cookies, str):
                        raise ValueError("cookies 必须是字符串")
                    proxy_mode = payload.get("proxy_mode", "keep")
                    proxy = payload.get("proxy")
                    if not isinstance(proxy_mode, str):
                        raise ValueError("proxy_mode 必须是字符串")
                    if proxy is not None and not isinstance(proxy, str):
                        raise ValueError("proxy 必须是字符串")
                    if active is None and not (cookies or "").strip() and proxy_mode == "keep":
                        raise ValueError("没有需要更新的字段")
                    self._run(
                        self.server.service.update_account(
                            username,
                            active=active,
                            cookies=cookies,
                            proxy_mode=proxy_mode,
                            proxy=proxy,
                        )
                    )
                    self._send_json({"ok": True})
                    return
                if method == "DELETE" and len(parts) == 3:
                    if payload.get("confirm_username") != username:
                        raise ValueError("请输入完整账号名称确认删除")
                    self._run(self.server.service.delete_account(username))
                    self._send_json({"ok": True})
                    return
                if method == "POST" and parts[3:] == ["reset-locks"]:
                    self._run(self.server.service.reset_locks(username))
                    self._send_json({"ok": True})
                    return

            self._send_json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)
        except DashboardAccountNotFoundError as error:
            self._send_json({"error": str(error)}, HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except FutureTimeoutError:
            self._send_json({"error": "Operation timed out"}, HTTPStatus.GATEWAY_TIMEOUT)
        except Exception:
            self._send_json({"error": "操作失败，请检查本地日志"}, HTTPStatus.INTERNAL_SERVER_ERROR)


def serve_dashboard(args: argparse.Namespace) -> None:
    host = args.host
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("MVP 看板仅允许绑定到 127.0.0.1 或 localhost")

    username, password = resolve_dashboard_credentials()
    pool = AccountsPool(args.db, raise_when_no_account=True)
    server = DashboardServer(
        (host, args.port),
        pool,
        DashboardAuth(username, password),
        args.db,
        trusted_proxy=get_env_bool("TWS_TRUSTED_PROXY"),
    )
    actual_host, actual_port = host, server.server_port
    url = f"http://{actual_host}:{actual_port}"
    print(f"twscrape dashboard: {url}")
    print(f"Dashboard username: {username}")
    print("Press Ctrl+C to stop")
    if not args.no_open:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
