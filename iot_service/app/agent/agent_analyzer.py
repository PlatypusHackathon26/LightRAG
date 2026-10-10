import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.agent.llm_client import LLMClient
from app.agent.loop import ReActAgentLoop
from app.agent.rule_analyzer import AnalysisResult, BaseAnalyzer, RuleAnalyzer
from app.config import settings
from app.db import DatabaseManager

logger = logging.getLogger("app.agent.agent_analyzer")


class AgentAnalyzer(BaseAnalyzer):
    """
    Primary LLM-based ReAct Diagnostic Analyzer with automatic fallback to RuleAnalyzer.
    Flow:
    1. If settings.AGENT_MODE == 'rules', delegates directly to RuleAnalyzer.
    2. Runs ReActAgentLoop with LLMClient, tool calls, and step bounds.
    3. If LLM fails, times out, exceeds steps, or malformed JSON:
       - Logs warning.
       - Records fallback notice in incident timeline.
       - Calls RuleAnalyzer as fallback to safeguard the test bench.
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        rule_analyzer: Optional[RuleAnalyzer] = None,
    ):
        self.llm_client = llm_client or LLMClient()
        self.rule_analyzer = rule_analyzer or RuleAnalyzer(playbooks_path="config/playbooks.yaml")

    async def analyze_incident(
        self,
        machine_id: str,
        trigger_event: Dict[str, Any],
        db_manager: DatabaseManager,
    ) -> AnalysisResult:
        inc_id = trigger_event.get("incident_id") or "INC-CURRENT"

        # Explicit rules mode
        if settings.AGENT_MODE == "rules":
            logger.info("AGENT_MODE=rules: Running RuleAnalyzer directly.")
            return await self.rule_analyzer.analyze_incident(machine_id, trigger_event, db_manager)

        logger.info(f"AGENT_MODE=llm: Starting ReAct Agent diagnostic for {machine_id} (incident {inc_id})")

        react_loop = ReActAgentLoop(
            llm_client=self.llm_client,
            db_manager=db_manager,
            max_steps=6,
            timeout_seconds=45.0,
        )

        success, result, loop_timeline, failure_reason = await react_loop.run(
            machine_id=machine_id,
            event_dict=trigger_event,
            incident_id=inc_id,
        )

        if success and result:
            logger.info(f"ReAct Agent completed diagnosis successfully: {result.root_cause} ({result.confidence:.2f})")
            return result

        # Fallback to RuleAnalyzer
        logger.warning(
            f"ReAct Agent diagnosis failed or aborted ({failure_reason}). Triggering automatic fallback to RuleAnalyzer."
        )

        # Append fallback marker event to timeline
        now_ts = datetime.now(timezone.utc)
        fallback_timeline_evt = {
            "id": f"EVT-{int(now_ts.timestamp() * 1000)}-fallback",
            "timestamp": now_ts.strftime("%H:%M:%S"),
            "type": "observation",
            "label": "Kích hoạt chế độ dự phòng theo luật (Rule-based Fallback)",
            "detail": f"Agent LLM không thể hoàn tất vòng lặp ({failure_reason}). Hệ thống tự động chuyển sang bộ phân tích dự phòng RuleAnalyzer để đảm bảo an toàn.",
        }

        fallback_result = await self.rule_analyzer.analyze_incident(
            machine_id=machine_id,
            trigger_event=trigger_event,
            db_manager=db_manager,
        )

        # Merge timeline events from failed loop and fallback result
        combined_timeline = list(loop_timeline)
        combined_timeline.append(fallback_timeline_evt)
        combined_timeline.extend(fallback_result.timeline_events)

        fallback_result.timeline_events = combined_timeline
        return fallback_result
