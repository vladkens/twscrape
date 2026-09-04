import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Any, TypedDict

from .db import execute, fetchall, fetchone
from .utils import utc


class ApiKeyInfo(TypedDict):
    id: str
    name: str
    prefix: str
    created_at: str
    last_used_at: str | None
    revoked_at: str | None
    active: bool


class ApiKeyStore:
    def __init__(self, db_file: str):
        self.db_file = db_file

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def _public(row: Any) -> ApiKeyInfo:
        return {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "prefix": str(row["key_prefix"]),
            "created_at": str(row["created_at"]),
            "last_used_at": str(row["last_used_at"]) if row["last_used_at"] else None,
            "revoked_at": str(row["revoked_at"]) if row["revoked_at"] else None,
            "active": row["revoked_at"] is None,
        }

    async def create(self, name: str) -> tuple[ApiKeyInfo, str]:
        name = name.strip()
        if not name:
            raise ValueError("请输入密钥名称")
        if len(name) > 80:
            raise ValueError("密钥名称不能超过 80 个字符")

        key_id = secrets.token_hex(8)
        token = f"tws_{key_id}_{secrets.token_urlsafe(32)}"
        created_at = utc.now().isoformat()
        await execute(
            self.db_file,
            """
            INSERT INTO dashboard_api_keys
                (id, name, key_hash, key_prefix, created_at)
            VALUES
                (:id, :name, :key_hash, :key_prefix, :created_at)
            """,
            {
                "id": key_id,
                "name": name,
                "key_hash": self._hash(token),
                "key_prefix": f"tws_{key_id}_…",
                "created_at": created_at,
            },
        )
        row = await fetchone(
            self.db_file, "SELECT * FROM dashboard_api_keys WHERE id = :id", {"id": key_id}
        )
        if row is None:
            raise RuntimeError("密钥创建失败")
        return self._public(row), token

    async def list(self) -> list[ApiKeyInfo]:
        rows = await fetchall(
            self.db_file,
            """
            SELECT * FROM dashboard_api_keys
            ORDER BY created_at DESC
            """,
        )
        return [self._public(row) for row in rows]

    async def validate(self, token: str) -> bool:
        if len(token) > 512 or not token.startswith("tws_"):
            return False
        key_id, separator, secret = token[4:].partition("_")
        if not separator or not key_id or not secret:
            return False
        row = await fetchone(
            self.db_file,
            "SELECT key_hash, last_used_at, revoked_at FROM dashboard_api_keys WHERE id = :id",
            {"id": key_id},
        )
        if row is None or row["revoked_at"] is not None:
            return False
        if not hmac.compare_digest(str(row["key_hash"]), self._hash(token)):
            return False
        now = utc.now()
        last_used_at = utc.from_iso(row["last_used_at"]) if row["last_used_at"] else None
        if last_used_at is None or now - last_used_at >= timedelta(minutes=1):
            await execute(
                self.db_file,
                "UPDATE dashboard_api_keys SET last_used_at = :now WHERE id = :id",
                {"id": key_id, "now": now.isoformat()},
            )
        return True

    async def revoke(self, key_id: str, confirm_name: str) -> bool:
        row = await fetchone(
            self.db_file,
            "SELECT name, revoked_at FROM dashboard_api_keys WHERE id = :id",
            {"id": key_id},
        )
        if row is None or row["revoked_at"] is not None:
            return False
        if confirm_name != row["name"]:
            raise ValueError("请输入完整密钥名称确认撤销")
        await execute(
            self.db_file,
            "UPDATE dashboard_api_keys SET revoked_at = :now WHERE id = :id",
            {"id": key_id, "now": utc.now().isoformat()},
        )
        return True
