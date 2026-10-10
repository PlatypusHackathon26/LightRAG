import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.agent.llm_client import LLMClient
from app.agent.prompts import REACT_SYSTEM_PROMPT, build_initial_prompt
from app.agent.rule_analyzer import AnalysisResult, ProposedActionPlan
from app.agent.tools import AgentToolExecutor
from app.config import settings
from app.db import DatabaseManager

logger = logging.getLogger("app.agent.loop")


class ReActAgentLoop:
    """
    Executes the ReAct (Reasoning + Acting) Agent loop.
    Hard bounds:
    - Maximum 6 reasoning steps.
    - Configurable total session timeout.
    - Records thoughts, actions, and observations to DB (agent_steps) and incident timeline.
    - Collects citations, work orders, and proposed actions.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        db_manager: DatabaseManager,
        max_steps: int = 6,
        timeout_seconds: float = 60.0,
    ):
        self.llm_client = llm_client
        self.db = db_manager
        self.max_steps = max_steps
        self.timeout = timeout_seconds

    async def run(
        self,
        machine_id: str,
        event_dict: Dict[str, Any],
        incident_id: str,
    ) -> Tuple[bool, Optional[AnalysisResult], List[Dict[str, Any]], str]:
        """
        Executes ReAct diagnostic loop.
        Returns:
            (success: bool, result: Optional[AnalysisResult], timeline_events: List[Dict], failure_reason: str)
        """
        tool_executor = AgentToolExecutor(db=self.db, incident_id=incident_id)
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": REACT_SYSTEM_PROMPT},
            {"role": "user", "content": build_initial_prompt(machine_id, event_dict, incident_id)},
        ]

        timeline_events: List[Dict[str, Any]] = []
        collected_citations: List[Dict[str, Any]] = []
        final_analysis: Optional[AnalysisResult] = None

        start_time = time.perf_counter()
        now_ts = datetime.now(timezone.utc)
        now_str = now_ts.strftime("%H:%M:%S")

        # Initial timeline observation
        timeline_events.append({
            "id": f"EVT-{int(now_ts.timestamp() * 1000)}-init",
            "timestamp": now_str,
            "type": "observation",
            "label": "Kích hoạt Agent LLM (ReAct Diagnostic)",
            "detail": f"Bắt đầu quy trình chẩn đoán ReAct cho mã lỗi {event_dict.get('error_code')} trên {machine_id}.",
        })

        for step in range(1, self.max_steps + 1):
            if (time.perf_counter() - start_time) > self.timeout:
                logger.warning(f"ReAct agent exceeded session timeout of {self.timeout}s at step {step}")
                return False, None, timeline_events, f"Vượt quá thời gian tối đa ({self.timeout}s)"

            step_start = time.perf_counter()
            try:
                llm_res = await self.llm_client.chat_completion(messages=messages, json_mode=True)
            except Exception as e:
                logger.error(f"ReAct step {step} LLM call failed: {e}")
                return False, None, timeline_events, f"Lỗi gọi LLM: {str(e)}"

            parsed = llm_res.get("parsed_json")
            if not parsed or not isinstance(parsed, dict):
                logger.warning(f"Step {step}: LLM did not return valid JSON: {llm_res.get('content')[:150]}")
                return False, None, timeline_events, "Đầu ra LLM sai định dạng JSON"

            thought = parsed.get("thought", "")
            action = parsed.get("action", {})
            tool_name = action.get("tool", "") if isinstance(action, dict) else ""
            tool_args = action.get("args", {}) if isinstance(action, dict) else {}

            step_latency = (time.perf_counter() - step_start) * 1000.0

            # Record thought to timeline
            step_ts = datetime.now(timezone.utc)
            timeline_events.append({
                "id": f"EVT-{int(step_ts.timestamp() * 1000)}-thought-{step}",
                "timestamp": step_ts.strftime("%H:%M:%S"),
                "type": "observation",
                "label": f"Bước {step}: Suy luận Agent",
                "detail": thought,
            })

            # Check if finished
            if tool_name == "finish":
                root_cause = tool_args.get("root_cause", "Đã hoàn thành phân tích")
                confidence = float(tool_args.get("confidence", 0.85))
                summary = tool_args.get("summary", thought)

                # Persist step
                await self.db.insert_agent_step(
                    incident_id=incident_id,
                    step_number=step,
                    thought=thought,
                    tool=tool_name,
                    tool_args=tool_args,
                    tool_result={"status": "completed"},
                    latency_ms=step_latency,
                )

                # Timeline conclusion
                fin_ts = datetime.now(timezone.utc)
                timeline_events.append({
                    "id": f"EVT-{int(fin_ts.timestamp() * 1000)}-conclusion",
                    "timestamp": fin_ts.strftime("%H:%M:%S"),
                    "type": "conclusion",
                    "label": f"Kết luận chẩn đoán: {root_cause}",
                    "detail": f"{summary} (Độ tin cậy: {int(confidence * 100)}%)",
                    "citations": collected_citations,
                })

                # Retrieve proposed action if any
                proposed_action_plan = None
                if tool_executor.actions_proposed:
                    last_act_id = tool_executor.actions_proposed[-1]
                    act_record = await self.db.get_action(last_act_id)
                    if act_record:
                        proposed_action_plan = ProposedActionPlan(
                            command=act_record["command"],
                            params=act_record["params"],
                            title_vi=f"Đề xuất: {act_record['command']}",
                            subtitle_vi=act_record.get("rationale", ""),
                            diagnosis_en=f"Proposed {act_record['command']} via ReAct Agent.",
                            rationale=act_record.get("rationale", ""),
                            items=[{
                                "type": "plc_command",
                                "title": "Lệnh điều khiển PLC",
                                "description": f"Thực thi {act_record['command']}",
                                "params": act_record["params"],
                            }],
                            timer_seconds=settings.ACTION_TTL_S,
                        )

                final_analysis = AnalysisResult(
                    matched_playbook_id="react_llm_agent",
                    title=f"CẢNH BÁO: {root_cause}",
                    root_cause=root_cause,
                    confidence=confidence,
                    severity=event_dict.get("severity", "CRITICAL").lower(),
                    diagnosis_vi=summary,
                    diagnosis_en=f"Root cause determined by ReAct Agent: {root_cause}",
                    tags=["#react-agent", f"#{machine_id.lower()}"],
                    proposed_action=proposed_action_plan,
                    timeline_events=timeline_events,
                    citations=collected_citations,
                )
                return True, final_analysis, timeline_events, ""

            # Execute tool
            tool_res = await tool_executor.execute_tool(tool_name, tool_args)

            # Persist step in DB
            await self.db.insert_agent_step(
                incident_id=incident_id,
                step_number=step,
                thought=thought,
                tool=tool_name,
                tool_args=tool_args,
                tool_result=tool_res,
                latency_ms=step_latency,
            )

            # Record tool execution to timeline
            tool_ts = datetime.now(timezone.utc)
            if tool_name == "search_manual":
                cits = tool_res.get("citations", [])
                collected_citations.extend(cits)
                timeline_events.append({
                    "id": f"EVT-{int(tool_ts.timestamp() * 1000)}-rag-{step}",
                    "timestamp": tool_ts.strftime("%H:%M:%S"),
                    "type": "document_lookup",
                    "label": f"Bước {step}: Tra cứu cẩm nang kỹ thuật",
                    "detail": f"Truy vấn: '{tool_args.get('query')}'. Trích xuất hướng dẫn từ tài liệu.",
                    "citations": cits,
                })
            elif tool_name in ("get_current_status", "get_history", "get_recent_events"):
                timeline_events.append({
                    "id": f"EVT-{int(tool_ts.timestamp() * 1000)}-tool-{step}",
                    "timestamp": tool_ts.strftime("%H:%M:%S"),
                    "type": "sensor_check",
                    "label": f"Bước {step}: Kiểm tra chéo cảm biến viễn trắc",
                    "detail": tool_res.get("summary", json.dumps(tool_res, ensure_ascii=False)),
                })
            elif tool_name == "propose_action":
                timeline_events.append({
                    "id": f"EVT-{int(tool_ts.timestamp() * 1000)}-action-{step}",
                    "timestamp": tool_ts.strftime("%H:%M:%S"),
                    "type": "proposed",
                    "label": f"Bước {step}: Đề xuất lệnh điều khiển {tool_args.get('command')}",
                    "detail": tool_res.get("message", tool_args.get("rationale", "")),
                })
            elif tool_name == "create_work_order":
                timeline_events.append({
                    "id": f"EVT-{int(tool_ts.timestamp() * 1000)}-wo-{step}",
                    "timestamp": tool_ts.strftime("%H:%M:%S"),
                    "type": "observation",
                    "label": f"Bước {step}: Mở phiếu sửa chữa / bảo trì",
                    "detail": f"Phiếu: {tool_args.get('title')}. Các bước: {'; '.join(tool_args.get('steps', []))}",
                    "citations": tool_args.get("citations", []),
                })

            # Append observation for next LLM iteration
            obs_str = json.dumps(tool_res, ensure_ascii=False)
            messages.append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)})
            messages.append({"role": "user", "content": f"KẾT QUẢ CÔNG CỤ ({tool_name}):\n{obs_str}"})

        # Step limit reached without finish
        logger.warning(f"ReAct agent reached hard step limit of {self.max_steps} without finishing.")
        return False, None, timeline_events, f"Vượt quá giới hạn {self.max_steps} bước suy luận"
