import argparse
import asyncio
import json
import secrets
import threading
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files
from typing import Any, TypedDict
from urllib.parse import unquote, urlparse

from .accounts_pool import AccountsPool
from .utils import utc


class DashboardAccountInfo(TypedDict):
    username: str
    active: bool
    has_session: bool
    login_method: str
    status: str
    needs_attention: bool
    lock_count: int
    locked_queues: list[str]
    total_requests: int
    last_used: str | None
    error_message: str | None


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
            needs_attention = bool(
                not account.active or not account.has_session or account.error_msg
            )
            if account.error_msg:
                status = "error"
            elif not account.active:
                status = "inactive"
            elif not account.has_session:
                status = "session"
            elif active_locks:
                status = "locked"
            else:
                status = "ready"

            items.append(
                {
                    "username": account.username,
                    "active": account.active,
                    "has_session": account.has_session,
                    "login_method": account.login_method,
                    "status": status,
                    "needs_attention": needs_attention,
                    "lock_count": len(active_locks),
                    "locked_queues": sorted(active_locks),
                    "total_requests": sum(account.stats.values()),
                    "last_used": account.last_used.isoformat() if account.last_used else None,
                    "error_message": str(account.error_msg)[:120] if account.error_msg else None,
                }
            )

        items.sort(key=lambda item: (item["needs_attention"], item["username"].lower()))
        items.sort(key=lambda item: item["needs_attention"], reverse=True)
        return {
            "summary": {
                "total": len(items),
                "running": sum(
                    1
                    for item in items
                    if item["active"] and item["has_session"] and not item["error_message"]
                ),
                "attention": sum(1 for item in items if item["needs_attention"]),
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
    def __init__(self, address: tuple[str, int], pool: AccountsPool):
        super().__init__(address, DashboardHandler)
        self.service = DashboardService(pool)
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

    def _send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self._send_bytes(body, "application/json; charset=utf-8", status)

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

    def _run(self, coroutine: Any) -> Any:
        return asyncio.run(coroutine)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/accounts":
            self._send_json(self._run(self.server.service.snapshot()))
            return

        assets = files("twscrape").joinpath("dashboard_assets")
        if path == "/":
            html = assets.joinpath("index.html").read_text(encoding="utf-8")
            html = html.replace("__CSRF_TOKEN__", self.server.csrf_token)
            self._send_bytes(html.encode(), "text/html; charset=utf-8")
            return
        if path == "/dashboard.css":
            body = assets.joinpath("dashboard.css").read_bytes()
            self._send_bytes(body, "text/css; charset=utf-8")
            return
        if path == "/dashboard.js":
            body = assets.joinpath("dashboard.js").read_bytes()
            self._send_bytes(body, "text/javascript; charset=utf-8")
            return
        self._send_json({"error": "页面不存在"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        self._handle_mutation("POST")

    def do_PATCH(self) -> None:
        self._handle_mutation("PATCH")

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

    server = DashboardServer((host, args.port), AccountsPool(args.db))
    actual_host, actual_port = host, server.server_port
    url = f"http://{actual_host}:{actual_port}"
    print(f"twscrape dashboard: {url}")
    print("Press Ctrl+C to stop")
    if not args.no_open:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
