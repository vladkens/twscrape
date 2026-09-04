from twscrape.api_keys import ApiKeyStore
from twscrape.db import fetchone


async def test_api_key_lifecycle_stores_only_hash(tmp_path):
    db_file = str(tmp_path / "accounts.db")
    store = ApiKeyStore(db_file)

    info, token = await store.create("Local client")

    assert token.startswith(f"tws_{info['id']}_")
    assert info["name"] == "Local client"
    assert info["prefix"] == f"tws_{info['id']}_…"
    assert info["active"] is True
    assert info["last_used_at"] is None
    row = await fetchone(
        db_file, "SELECT key_hash FROM dashboard_api_keys WHERE id = :id", {"id": info["id"]}
    )
    assert row is not None
    assert row["key_hash"] != token
    assert token not in str(row["key_hash"])

    assert await store.validate(token) is True
    listed = await store.list()
    assert len(listed) == 1
    assert listed[0]["last_used_at"] is not None
    assert token not in str(listed)

    try:
        await store.revoke(info["id"], "wrong name")
    except ValueError:
        pass
    else:
        raise AssertionError("API key was revoked without exact name confirmation")

    assert await store.revoke(info["id"], "Local client") is True
    assert await store.validate(token) is False
    revoked = await store.list()
    assert revoked[0]["active"] is False
    assert revoked[0]["revoked_at"] is not None
    assert await store.revoke(info["id"], "Local client") is False


async def test_api_key_rejects_invalid_tokens_and_names(tmp_path):
    store = ApiKeyStore(str(tmp_path / "accounts.db"))

    for token in ("", "wrong", "tws_missing", "tws__secret", "x" * 513):
        assert await store.validate(token) is False

    for name in ("", " ", "x" * 81):
        try:
            await store.create(name)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid API key name was accepted")
