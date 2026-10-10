import uuid
from datetime import datetime, timezone
import pytest
from app.db import DatabaseManager


@pytest.mark.asyncio
async def test_event_deduplication():
    db = DatabaseManager(dsn="postgresql://invalid:5432/none")  # In-memory mode
    now = datetime.now(timezone.utc)

    event1 = {
        "event_id": str(uuid.uuid4()),
        "timestamp": now.isoformat(),
        "machine_id": "COMP-TB-01",
        "source": "machine",
        "event_type": "ERROR",
        "severity": "CRITICAL",
        "error_code": "ERR_COMP_OVERHEAT_402",
        "message": "Discharge temperature exceeded 120 C",
    }

    # 1. First event
    is_new, canon_id1 = await db.insert_or_dedup_event(event1)
    assert is_new is True
    assert canon_id1 == event1["event_id"]

    # 2. Duplicate event 5 seconds later with new event_id
    event2 = {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.fromtimestamp(now.timestamp() + 5, tz=timezone.utc).isoformat(),
        "machine_id": "COMP-TB-01",
        "source": "machine",
        "event_type": "ERROR",
        "severity": "CRITICAL",
        "error_code": "ERR_COMP_OVERHEAT_402",
        "message": "Discharge temperature exceeded 120 C",
    }
    is_new2, canon_id2 = await db.insert_or_dedup_event(event2)
    assert is_new2 is False
    assert canon_id2 == canon_id1

    # 3. Different error code
    event3 = {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.fromtimestamp(now.timestamp() + 10, tz=timezone.utc).isoformat(),
        "machine_id": "COMP-TB-01",
        "source": "machine",
        "event_type": "ERROR",
        "severity": "CRITICAL",
        "error_code": "ERR_COMP_LOWPRESS_310",
        "message": "Suction pressure dropped below 1.0 bar",
    }
    is_new3, canon_id3 = await db.insert_or_dedup_event(event3)
    assert is_new3 is True
    assert canon_id3 == event3["event_id"]

    # 4. Check querying recent events
    recent = await db.get_recent_events("COMP-TB-01", since_time=datetime.fromtimestamp(now.timestamp() - 60, tz=timezone.utc))
    assert len(recent) == 2  # Only 2 distinct events, not 3!
    overheat_ev = next(e for e in recent if e["error_code"] == "ERR_COMP_OVERHEAT_402")
    assert overheat_ev["repeat_count"] == 2
