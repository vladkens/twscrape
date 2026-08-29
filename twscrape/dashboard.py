import argparse
import asyncio
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files
from typing import Any, TypedDict
from urllib.parse import parse_qs, unquote, urlparse

from .accounts_pool import AccountsPool, NoAccountError
from .utils import utc
from .x_api import (
    XApiNotFoundError,
    XApiService,
    XApiUnavailableError,
    parse_bool,
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


def api_endpoint_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": "用户资料",
            "method": "GET",
            "path": "/api/user/{name}",
            "description": "按 X 用户名获取公开资料",
            "params": [{"name": "name", "in": "path", "required": True, "example": "xdevelopers"}],
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
            ],
        },
        {
            "name": "关注者列表",
            "method": "GET",
            "path": "/api/user/{name}/followers",
            "description": "获取关注该用户的账号",
            "params": [
                {"name": "name", "in": "path", "required": True, "example": "xdevelopers"},
                {"name": "limit", "in": "query", "required": False, "example": "20"},
            ],
        },
        {
            "name": "关注列表",
            "method": "GET",
            "path": "/api/user/{name}/following",
            "description": "获取该用户正在关注的账号",
            "params": [
                {"name": "name", "in": "path", "required": True, "example": "xdevelopers"},
                {"name": "limit", "in": "query", "required": False, "example": "20"},
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
            raise ValueError("账号不存在")
        await self.pool.set_active(username, active)

    async def reset_locks(self, username: str) -> None:
        if await self.pool.get_account(username) is None:
            raise ValueError("账号不存在")
        await self.pool.reset_locks(username)


class DashboardServer(HTTPServer):
    def __init__(self, address: tuple[str, int], pool: AccountsPool, auth: DashboardAuth):
        super().__init__(address, DashboardHandler)
        self.service = DashboardService(pool)
        self.x_api = XApiService(pool)
        self.auth = auth
        self.csrf_token = secrets.token_urlsafe(32)


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

    def _require_api_auth(self) -> bool:
        if self._is_authenticated():
            return True
        self._send_json({"error": "Authentication required"}, HTTPStatus.UNAUTHORIZED)
        return False

    def _run(self, coroutine: Any) -> Any:
        return asyncio.run(coroutine)

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
        if path == "/login.js":
            self._send_bytes(
                assets.joinpath("login.js").read_bytes(), "text/javascript; charset=utf-8"
            )
            return
        if path in {"/", "/login"}:
            page = "index.html" if self._is_authenticated() else "login.html"
            html = assets.joinpath(page).read_text(encoding="utf-8")
            html = html.replace("__CSRF_TOKEN__", self.server.csrf_token)
            self._send_bytes(html.encode(), "text/html; charset=utf-8")
            return
        if not self._require_api_auth():
            return
        if path == "/auth/session":
            self._send_json({"authenticated": True, "username": self.server.auth.username})
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
        if path == "/api/accounts":
            self._send_json(self._run(self.server.service.snapshot()))
            return
        if path.startswith(("/api/user/", "/api/tweet/")) or path == "/api/search":
            self._handle_x_api(parsed)
            return

        self._send_json({"error": "页面不存在"}, HTTPStatus.NOT_FOUND)

    def _handle_x_api(self, parsed: Any) -> None:
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            limit = parse_limit(query.get("limit", [None])[0])
            if path == "/api/search":
                search_query = query.get("q", [""])[0]
                self._send_json(self._run(self.server.x_api.search(search_query, limit)))
                return

            parts = [unquote(part) for part in path.split("/") if part]
            if len(parts) == 3 and parts[:2] == ["api", "user"]:
                self._send_json(self._run(self.server.x_api.user(parts[2])))
                return
            if len(parts) == 4 and parts[:2] == ["api", "user"] and parts[3] == "tweets":
                include_replies = parse_bool(query.get("include_replies", [None])[0])
                self._send_json(
                    self._run(self.server.x_api.user_tweets(parts[2], limit, include_replies))
                )
                return
            if (
                len(parts) == 4
                and parts[:2] == ["api", "user"]
                and parts[3] in {"followers", "following"}
            ):
                method = getattr(self.server.x_api, parts[3])
                self._send_json(self._run(method(parts[2], limit)))
                return
            if len(parts) == 3 and parts[:2] == ["api", "tweet"]:
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
            self._send_json(
                {"error": "No active account is available"}, HTTPStatus.SERVICE_UNAVAILABLE
            )
        except ValueError as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception:
            self._send_json({"error": "Upstream X request failed"}, HTTPStatus.BAD_GATEWAY)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/auth/login":
            self._handle_login()
            return
        if not self._require_api_auth():
            return
        if path == "/auth/logout":
            self._handle_logout()
            return
        self._handle_mutation("POST")

    def do_PATCH(self) -> None:
        if not self._require_api_auth():
            return
        self._handle_mutation("PATCH")

    def _handle_login(self) -> None:
        if not self._allow_mutation():
            self._send_json({"error": "请求校验失败，请刷新页面后重试"}, HTTPStatus.FORBIDDEN)
            return
        client = self.client_address[0]
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
            if method == "POST" and path == "/api/accounts":
                self._run(
                    self.server.service.add_cookie_account(
                        str(payload.get("username", "")), str(payload.get("cookies", ""))
                    )
                )
                self._send_json({"ok": True}, HTTPStatus.CREATED)
                return

            parts = [unquote(part) for part in path.split("/") if part]
            if len(parts) >= 3 and parts[:2] == ["api", "accounts"]:
                username = parts[2]
                if method == "PATCH" and len(parts) == 3:
                    active = payload.get("active")
                    if not isinstance(active, bool):
                        raise ValueError("active 必须是布尔值")
                    self._run(self.server.service.set_active(username, active))
                    self._send_json({"ok": True})
                    return
                if method == "POST" and parts[3:] == ["reset-locks"]:
                    self._run(self.server.service.reset_locks(username))
                    self._send_json({"ok": True})
                    return

            self._send_json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception:
            self._send_json({"error": "操作失败，请检查本地日志"}, HTTPStatus.INTERNAL_SERVER_ERROR)


def serve_dashboard(args: argparse.Namespace) -> None:
    host = args.host
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("MVP 看板仅允许绑定到 127.0.0.1 或 localhost")

    username, password = resolve_dashboard_credentials()
    pool = AccountsPool(args.db, raise_when_no_account=True)
    server = DashboardServer((host, args.port), pool, DashboardAuth(username, password))
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
