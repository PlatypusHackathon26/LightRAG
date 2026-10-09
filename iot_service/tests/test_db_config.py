import pytest
import logging
from app.db import DatabaseManager, mask_dsn
from app.config import Settings


def test_mask_dsn():
    # Standard postgresql DSN with password
    dsn = "postgresql://myuser:super_secret_pw@localhost:5433/denso_iot"
    masked = mask_dsn(dsn)
    assert "super_secret_pw" not in masked
    assert masked == "postgresql://myuser:***@localhost:5433/denso_iot"

    # DSN with special characters in password
    dsn_special = "postgresql://admin:p%40ssw0rd!@127.0.0.1:5432/testdb"
    masked_special = mask_dsn(dsn_special)
    assert "p%40ssw0rd!" not in masked_special
    assert "***" in masked_special

    # DSN without password
    dsn_nopass = "postgresql://myuser@localhost:5433/denso_iot"
    assert mask_dsn(dsn_nopass) == "postgresql://myuser@localhost:5433/denso_iot"

    # Empty DSN
    assert mask_dsn("") == ""


@pytest.mark.asyncio
async def test_db_required_failure_raises_runtime_error(monkeypatch):
    """When DB_REQUIRED=True (default) and connection fails, connect() must raise RuntimeError with clear message."""
    invalid_dsn = "postgresql://postgres:mysecretpass@127.0.0.1:59999/denso_iot"
    mgr = DatabaseManager(dsn=invalid_dsn)

    # Ensure DB_REQUIRED is True and DB_MODE is timescale
    monkeypatch.setattr("app.db.settings.DB_REQUIRED", True)
    monkeypatch.setattr("app.db.settings.DB_MODE", "timescale")

    with pytest.raises(RuntimeError) as exc_info:
        await mgr.connect()

    err_msg = str(exc_info.value)
    # Password must NOT appear in error message
    assert "mysecretpass" not in err_msg
    # Masked DSN must appear
    assert "postgres:***@127.0.0.1:59999/denso_iot" in err_msg
    # Explicit message indicating failure
    assert "Cannot connect to TimescaleDB and DB_REQUIRED=true" in err_msg


@pytest.mark.asyncio
async def test_db_mode_memory_opt_in(monkeypatch):
    """When DB_MODE='memory', connect() enters in-memory mode explicitly without raising error."""
    mgr = DatabaseManager(dsn="postgresql://invalid:invalid@localhost:9999/test")

    monkeypatch.setattr("app.db.settings.DB_MODE", "memory")
    monkeypatch.setattr("app.db.settings.DB_REQUIRED", True)

    await mgr.connect()
    assert mgr.is_connected is False
    assert mgr._in_memory is True

    # Check inserting metrics in memory works
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    await mgr.insert_metrics_batch([(now, "TEST-01", "temp", 50.0)])
    history = await mgr.get_metrics_history("TEST-01", now)
    assert "temp" in history
    await mgr.disconnect()


@pytest.mark.asyncio
async def test_db_fallback_when_db_required_false(monkeypatch):
    """When DB_REQUIRED=False, connection failure logs warning and falls back to memory mode."""
    invalid_dsn = "postgresql://postgres:secret@127.0.0.1:59999/denso_iot"
    mgr = DatabaseManager(dsn=invalid_dsn)

    monkeypatch.setattr("app.db.settings.DB_REQUIRED", False)
    monkeypatch.setattr("app.db.settings.DB_MODE", "timescale")

    # Should not raise
    await mgr.connect()
    assert mgr.is_connected is False
    assert mgr._in_memory is True
    await mgr.disconnect()
