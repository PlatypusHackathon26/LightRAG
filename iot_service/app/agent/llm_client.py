import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional
import httpx

from app.config import settings

logger = logging.getLogger("app.agent.llm")


class LLMClient:
    """
    OpenAI-compatible LLM client supporting:
    - OpenAI API
    - Gemini (OpenAI-compatible endpoint)
    - Ollama (/v1)
    - Local models with structured JSON output enforcement.
    Tracks latency, token usage (if reported by provider), and handles limited retries.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 2,
    ):
        self.base_url = (base_url or settings.LLM_BASE_URL).rstrip("/")
        self.api_key = api_key or settings.LLM_API_KEY
        self.model = model or settings.LLM_MODEL
        self.timeout = timeout
        self.max_retries = max_retries

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        json_mode: bool = True,
    ) -> Dict[str, Any]:
        """
        Sends chat completion request to the OpenAI-compatible endpoint.
        Returns:
            {
                "content": str,
                "parsed_json": Optional[Dict[str, Any]],
                "latency_ms": float,
                "usage": Dict[str, int],
                "model": str
            }
        """
        endpoint = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        start_time = time.perf_counter()
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(endpoint, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()

                    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                    choices = data.get("choices", [])
                    if not choices:
                        raise ValueError(f"No choices returned from LLM provider: {data}")

                    content = choices[0].get("message", {}).get("content", "").strip()
                    usage = data.get("usage", {})

                    logger.info(
                        f"LLM call succeeded (model={self.model}, attempt={attempt + 1}, latency={elapsed_ms:.1f}ms, prompt_tokens={usage.get('prompt_tokens', 0)}, completion_tokens={usage.get('completion_tokens', 0)})"
                    )

                    parsed_json = None
                    if json_mode:
                        try:
                            parsed_json = self._extract_json(content)
                        except Exception as parse_ex:
                            logger.warning(f"Failed to parse JSON response from LLM: {parse_ex}. Content: {content[:200]}")

                    return {
                        "content": content,
                        "parsed_json": parsed_json,
                        "latency_ms": elapsed_ms,
                        "usage": usage,
                        "model": self.model,
                    }
            except Exception as ex:
                last_error = ex
                logger.warning(
                    f"LLM call attempt {attempt + 1}/{self.max_retries + 1} failed: {ex}"
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(1.0 * (attempt + 1))

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        logger.error(f"All LLM retries exhausted after {elapsed_ms:.1f}ms: {last_error}")
        raise RuntimeError(f"LLM request failed after {self.max_retries + 1} attempts: {last_error}")

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """Extracts JSON object from text (handling markdown code blocks if present)."""
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        # Find first { and last }
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            text = text[first_brace : last_brace + 1]

        return json.loads(text)


class FakeLLMClient(LLMClient):
    """
    Fake LLM Client for unit testing, offline integration, and CI/CD pipelines.
    Allows returning scripted sequence of responses or dynamic response based on scenario.
    """

    def __init__(self, scripted_responses: Optional[List[Dict[str, Any]]] = None):
        super().__init__(base_url="http://fake-llm", api_key="fake-key", model="fake-model")
        self.scripted_responses = scripted_responses or []
        self.call_count = 0
        self.recorded_messages: List[List[Dict[str, str]]] = []

    def set_responses(self, responses: List[Dict[str, Any]]):
        self.scripted_responses = responses
        self.call_count = 0

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        json_mode: bool = True,
    ) -> Dict[str, Any]:
        self.recorded_messages.append(messages)
        start_time = time.perf_counter()

        if self.scripted_responses and self.call_count < len(self.scripted_responses):
            resp_data = self.scripted_responses[self.call_count]
            self.call_count += 1
        else:
            # Default response
            resp_data = {
                "thought": "Đã thu thập đủ dữ liệu. Hoàn thành chẩn đoán.",
                "action": {
                    "tool": "finish",
                    "args": {
                        "root_cause": "Chưa xác định",
                        "confidence": 0.5,
                        "summary": "Không có thêm chỉ dẫn từ scripted response.",
                    },
                },
            }

        content_str = json.dumps(resp_data, ensure_ascii=False)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0 + 10.0

        return {
            "content": content_str,
            "parsed_json": resp_data,
            "latency_ms": elapsed_ms,
            "usage": {"prompt_tokens": 150, "completion_tokens": 50, "total_tokens": 200},
            "model": "fake-model",
        }
