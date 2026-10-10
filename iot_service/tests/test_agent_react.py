import pytest
from datetime import datetime, timezone

from app.agent.agent_analyzer import AgentAnalyzer
from app.agent.llm_client import FakeLLMClient
from app.agent.loop import ReActAgentLoop
from app.db import DatabaseManager


@pytest.fixture
def test_db():
    return DatabaseManager()


@pytest.mark.asyncio
async def test_react_loop_step_limit(test_db):
    """Verifies that ReAct loop enforces the hard limit of 6 steps and aborts safely."""
    # Scripted responses that never call finish
    infinite_steps = [
        {
            "thought": f"Bước {i}: tiếp tục thu thập dữ liệu...",
            "action": {
                "tool": "get_current_status",
                "args": {"machine_id": "COMP-TB-01"},
            },
        }
        for i in range(10)
    ]

    fake_llm = FakeLLMClient(scripted_responses=infinite_steps)
    loop = ReActAgentLoop(llm_client=fake_llm, db_manager=test_db, max_steps=6)

    success, result, timeline, reason = await loop.run(
        machine_id="COMP-TB-01",
        event_dict={"error_code": "ERR_COMP_OVERHEAT_402", "severity": "CRITICAL"},
        incident_id="INC-TEST-01",
    )

    assert not success
    assert result is None
    assert "Vượt quá giới hạn 6 bước" in reason
    # Verify agent steps persisted in DB
    steps = await test_db.get_agent_steps("INC-TEST-01")
    assert len(steps) == 6


@pytest.mark.asyncio
async def test_react_loop_malformed_json_fallback(test_db):
    """Verifies that AgentAnalyzer safely falls back to RuleAnalyzer on malformed JSON."""
    fake_llm = FakeLLMClient(scripted_responses=[])
    # Override chat_completion to return invalid JSON
    async def bad_completion(*args, **kwargs):
        return {
            "content": "Đây không phải là JSON hợp lệ!",
            "parsed_json": None,
            "latency_ms": 10.0,
            "usage": {},
            "model": "fake-model",
        }
    fake_llm.chat_completion = bad_completion

    from app.config import settings
    monkeypatch_mode = settings.AGENT_MODE
    settings.AGENT_MODE = "llm"
    analyzer = AgentAnalyzer(llm_client=fake_llm)

    # Seed DB with telemetry for COMP-TB-01 condenser fan failure
    now = datetime.now(timezone.utc)
    metrics_batch = [
        (now, "COMP-TB-01", "discharge_temp", 125.0),
        (now, "COMP-TB-01", "discharge_pressure", 23.5),
        (now, "COMP-TB-01", "condenser_fan_rpm", 0.0),
        (now, "COMP-TB-01", "compressor_rpm", 1500.0),
        (now, "COMP-TB-01", "suction_pressure", 2.2),
        (now, "COMP-TB-01", "vibration", 2.0),
        (now, "COMP-TB-01", "oil_level", 90.0),
    ]
    await test_db.insert_metrics_batch(metrics_batch)

    trigger_event = {
        "event_id": "test-uuid",
        "error_code": "ERR_COND_FAN_217",
        "severity": "CRITICAL",
        "machine_id": "COMP-TB-01",
        "message": "Condenser fan stalled",
        "incident_id": "INC-TEST-FALLBACK",
    }

    res = await analyzer.analyze_incident("COMP-TB-01", trigger_event, test_db)

    # Check fallback activated and succeeded
    assert res is not None
    assert res.matched_playbook_id == "condenser_fan_failure"
    assert "dàn ngưng hỏng" in res.root_cause
    # Verify timeline records fallback
    timeline_labels = [ev.get("label", "") for ev in res.timeline_events]
    assert any("Rule-based Fallback" in lbl for lbl in timeline_labels)
    settings.AGENT_MODE = monkeypatch_mode


@pytest.mark.asyncio
async def test_react_full_successful_flow(test_db):
    """
    Verifies full 3-step ReAct diagnostic flow:
    Step 1: search_manual
    Step 2: get_current_status
    Step 3: propose_action + finish
    """
    now = datetime.now(timezone.utc)
    metrics_batch = [
        (now, "COMP-TB-01", "discharge_temp", 126.0),
        (now, "COMP-TB-01", "suction_pressure", 0.8),
        (now, "COMP-TB-01", "condenser_fan_rpm", 2400.0),
        (now, "COMP-TB-01", "compressor_rpm", 1500.0),
        (now, "COMP-TB-01", "vibration", 3.0),
        (now, "COMP-TB-01", "oil_level", 85.0),
        (now, "COMP-TB-01", "discharge_pressure", 12.0),
    ]
    await test_db.insert_metrics_batch(metrics_batch)

    scripted_steps = [
        # Step 1: Tra cứu tài liệu
        {
            "thought": "Bước 1: Tra cứu tài liệu xử lý sự cố rò rỉ môi chất lạnh.",
            "action": {
                "tool": "search_manual",
                "args": {"query": "thiếu môi chất lạnh rò rỉ gas DENSO"},
            },
        },
        # Step 2: Kiểm tra chéo cảm biến
        {
            "thought": "Bước 2: Kiểm tra chéo số liệu cảm biến hiện tại của bệ thử COMP-TB-01.",
            "action": {
                "tool": "get_current_status",
                "args": {"machine_id": "COMP-TB-01"},
            },
        },
        # Step 3: Đề xuất hành động giảm tải an toàn
        {
            "thought": "Bước 3: Đề xuất hạ tốc độ máy nén xuống 1000 RPM để tránh cháy cuộn dây.",
            "action": {
                "tool": "propose_action",
                "args": {
                    "machine_id": "COMP-TB-01",
                    "command": "SET_RPM",
                    "params": {"rpm": 1000},
                    "rationale": "Hạ tốc độ từ 1500 xuống 1000 RPM giảm sinh nhiệt khi thiếu gas.",
                },
            },
        },
        # Step 4: Tạo phiếu sửa chữa và kết thúc
        {
            "thought": "Bước 4: Tạo phiếu kiểm tra rò rỉ và kết luận nguyên nhân gốc rễ.",
            "action": {
                "tool": "create_work_order",
                "args": {
                    "machine_id": "COMP-TB-01",
                    "title": "Kiểm tra rò rỉ gas bệ thử COMP-TB-01",
                    "steps": ["Kiểm tra van sạc", "Dò vết dầu loang"],
                    "parts": ["Gas R134a", "O-ring"],
                    "priority": "high",
                },
            },
        },
        # Step 5: Kết thúc chẩn đoán
        {
            "thought": "Bước 5: Hoàn tất chẩn đoán với đầy đủ bằng chứng đối chiếu.",
            "action": {
                "tool": "finish",
                "args": {
                    "root_cause": "Thiếu môi chất lạnh (rò rỉ gas)",
                    "confidence": 0.94,
                    "summary": "Áp suất hút tụt 0.8 bar, nhiệt độ xả 126°C trong khi quạt bình thường 2400 rpm.",
                },
            },
        },
    ]

    fake_llm = FakeLLMClient(scripted_responses=scripted_steps)
    loop = ReActAgentLoop(llm_client=fake_llm, db_manager=test_db, max_steps=6)

    success, result, timeline, reason = await loop.run(
        machine_id="COMP-TB-01",
        event_dict={"error_code": "ERR_COMP_LOWPRESS_310", "severity": "CRITICAL"},
        incident_id="INC-REACT-SUCCESS",
    )

    assert success
    assert result is not None
    assert result.root_cause == "Thiếu môi chất lạnh (rò rỉ gas)"
    assert result.confidence == 0.94
    assert result.proposed_action is not None
    assert result.proposed_action.command == "SET_RPM"
    assert result.proposed_action.params == {"rpm": 1000}

    # Verify work order created
    wo_list = await test_db.get_work_orders_for_incident("INC-REACT-SUCCESS")
    assert len(wo_list) == 1
    assert "Kiểm tra rò rỉ gas" in wo_list[0]["title"]

    # Verify agent steps
    steps = await test_db.get_agent_steps("INC-REACT-SUCCESS")
    assert len(steps) == 5
