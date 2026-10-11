"""Changes made to run Long-agent inside the DENSO project: a real LLM for the diagnosis,
operating limits in its prompt, repeat suppression and approval of every proposed command."""
import json
from unittest.mock import MagicMock, patch

from agent.brain import AgentBrain
from agent.llm_client import llm_callable_from_env, make_llm_callable
from agent.rag_engine import RAGEngine, _limits_text
from iot.action_approval import ActionApproval


def test_the_prompt_states_each_metrics_limits():
    text = _limits_text("ROBOT_ARM")
    assert "Gripper_Pressure_Bar (Áp suất kẹp gắp): danh nghĩa 6 Bar; tối thiểu 3.5" in text
    prompt = RAGEngine().build_format_prompt("MC-ROBOT-01", "ROBOT_ARM", {"Gripper_Pressure_Bar": 0.74})
    assert "NGƯỠNG VẬN HÀNH" in prompt and "tối thiểu 3.5" in prompt


def test_the_llm_callable_posts_an_openai_chat_request():
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"choices": [{"message": {"content": "{\"diagnosis\": \"Rò khí nén\"}"}}]}
    call = make_llm_callable("http://proxy/v1/", "nemotron", extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    with patch("agent.llm_client.httpx.post", return_value=response) as post:
        assert call("prompt") == "{\"diagnosis\": \"Rò khí nén\"}"
    url = post.call_args.args[0]
    body = post.call_args.kwargs["json"]
    assert url == "http://proxy/v1/chat/completions"
    assert body["model"] == "nemotron" and body["temperature"] == 0
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["messages"] == [{"role": "user", "content": "prompt"}]


def test_without_configuration_the_mock_stays(monkeypatch):
    monkeypatch.delenv("LONG_AGENT_LLM_BASE", raising=False)
    assert llm_callable_from_env() is None
    monkeypatch.setenv("LONG_AGENT_LLM_BASE", "http://proxy/v1")
    monkeypatch.setenv("LONG_AGENT_LLM_MODEL", "nemotron")
    assert callable(llm_callable_from_env())


def test_an_llm_diagnosis_keeps_only_catalogue_commands():
    answer = json.dumps({"diagnosis": "Áp suất kẹp gắp 0.74 Bar dưới 3.5 Bar: rò khí nén ở tay gắp.",
                         "actions": [{"command": "pause_motion", "params": {}, "risk_level": "HIGH", "reason": "an toàn"},
                                     {"command": "MAKE_COFFEE", "params": {}}]})
    rag = RAGEngine(llm_callable=lambda prompt: answer)
    result = rag.query_with_schema("MC-ROBOT-01", "ROBOT_ARM", {"Gripper_Pressure_Bar": 0.74})
    assert result["diagnosis"].startswith("Áp suất kẹp gắp 0.74 Bar")
    assert [a["command"] for a in result["actions"]] == ["PAUSE_MOTION"]
    assert result["actions"][0]["risk_level"] == "LOW"  # the catalogue's level, not the LLM's


def test_a_failing_llm_falls_back_to_the_mock():
    def down(prompt):
        raise ConnectionError("proxy down")
    result = RAGEngine(llm_callable=down).query_with_schema("MC-AMR-01", "AMR_VEHICLE", {"Battery_Pct": 5})
    assert "Pin" in result["diagnosis"]


def _alert(machine="MC-ROBOT-01", param="Gripper_Pressure_Bar"):
    return {"machine_id": machine, "machine_type": "ROBOT_ARM", "payload": {param: 0.7},
            "anomalies": [{"param": param, "value": 0.7}]}


def test_a_repeated_alert_is_not_diagnosed_again_within_the_window():
    rag = MagicMock()
    rag.query_with_schema.return_value = {"diagnosis": "Rò khí nén", "actions": []}
    brain = AgentBrain(rag_engine=rag, tools=MagicMock(), event_bus=MagicMock(), repeat_window_s=120)
    brain.handle_alert(_alert())
    brain.handle_alert(_alert())                               # same machine, same metric: skipped
    brain.handle_alert(_alert(param="Joint_3_Current_A"))     # another metric: diagnosed
    brain.handle_alert(_alert(machine="MC-ROBOT-02"))         # another machine: diagnosed
    assert rag.query_with_schema.call_count == 3
    original = AgentBrain(rag_engine=rag, tools=MagicMock(), event_bus=MagicMock())  # default 0: as upstream
    original.handle_alert(_alert())
    original.handle_alert(_alert())
    assert rag.query_with_schema.call_count == 5


def test_every_command_can_be_made_to_wait_for_an_engineer():
    dispatched = []

    def dispatch(command):
        dispatched.append(command)
        return {"status": "SUCCESS"}

    approval = ActionApproval(dispatcher_callback=dispatch, require_approval_for_all=True)
    record = approval.process_action_request({"machine_id": "MC-AMR-01", "command": "RETURN_TO_CHARGER", "risk_level": "LOW"})
    assert record["status"] == "PENDING_APPROVAL" and not dispatched
    approval.decide(record["approval_id"], "APPROVE")
    assert dispatched and dispatched[0]["command"] == "RETURN_TO_CHARGER"
    upstream = ActionApproval(dispatcher_callback=dispatch)  # default: LOW runs at once
    upstream.process_action_request({"machine_id": "MC-AMR-01", "command": "RETURN_TO_CHARGER", "risk_level": "LOW"})
    assert len(dispatched) == 2


def test_one_fault_tripping_several_metrics_is_diagnosed_once_then_again_when_it_spreads():
    rag = MagicMock()
    rag.query_with_schema.return_value = {"diagnosis": "x", "actions": []}
    brain = AgentBrain(rag_engine=rag, tools=MagicMock(), event_bus=MagicMock(), repeat_window_s=120)
    brain.handle_alert(_alert(param="Spindle_Load_Pct"))      # diagnosed
    brain.handle_alert(_alert(param="Spindle_Load_Pct"))      # same metric: skipped
    brain.handle_alert(_alert(param="Vibration_RMS_mm_s"))    # a new metric joins: diagnosed again
    brain.handle_alert(_alert(param="Spindle_Load_Pct"))      # already covered: skipped
    assert rag.query_with_schema.call_count == 2


def test_the_prompt_names_the_metrics_out_of_their_limits():
    prompt = RAGEngine().build_format_prompt("MC-MILL-01", "CNC_MILLING",
                                             {"Spindle_RotaryVelocity_RPM": 11994.0, "Coolant_Pressure_Bar": 0.0,
                                              "Spindle_Temp_C": 139.9})
    section = prompt.split("--- CHỈ SỐ ĐANG VƯỢT NGƯỠNG ---")[1].split("---")[0]
    assert "Coolant_Pressure_Bar (Áp suất tưới nguội) = 0.0 Bar < tối thiểu 5" in section
    assert "Spindle_Temp_C (Nhiệt độ trục chính) = 139.9 °C > tối đa 75" in section
    assert "RPM" not in section  # within noise: not a deviation


def test_the_prompt_asks_for_the_root_cause_fix_first():
    prompt = RAGEngine().build_format_prompt("MC-MILL-01", "CNC_MILLING", {"Coolant_Pressure_Bar": 0.0})
    assert "action ĐẦU TIÊN phải là lệnh khắc phục tận gốc" in prompt
    assert "REPAIR_COOLANT_SYSTEM" in prompt  # the catalogue it must choose from
