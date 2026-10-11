# agent/llm_client.py
"""LLM thật cho RAGEngine (thay bản giả lập theo từ khóa) qua API kiểu OpenAI.

Bật bằng biến môi trường (denso/scripts/serve_chat.ps1 -WithIoT tự đặt, trỏ vào proxy NVIDIA):
  LONG_AGENT_LLM_BASE        ví dụ http://127.0.0.1:8899/v1  (trống = giữ bản giả lập)
  LONG_AGENT_LLM_MODEL       ví dụ nvidia/nemotron-3-super-120b-a12b
  LONG_AGENT_LLM_KEY         khóa API nếu gọi thẳng nhà cung cấp (proxy tự chèn khóa thì bỏ trống)
  LONG_AGENT_LLM_EXTRA_BODY  JSON thêm vào request, ví dụ {"chat_template_kwargs": {"enable_thinking": false}}
"""

from __future__ import annotations

import json
import logging
import os
from typing import Callable, Optional

import httpx

logger = logging.getLogger("LLMClient")


def make_llm_callable(
    base_url: str,
    model: str,
    api_key: str = "",
    extra_body: Optional[dict] = None,
    timeout: float = 90.0,
) -> Callable[[str], str]:
    """Hàm prompt -> nội dung trả lời; lỗi mạng/HTTP được ném ra để RAGEngine rơi về bản giả lập."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    def call(prompt: str) -> str:
        body = {
            **(extra_body or {}),
            "model": model,
            "temperature": 0,
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": prompt}],
        }
        r = httpx.post(url, json=body, headers=headers, timeout=timeout)
        r.raise_for_status()
        content = (r.json().get("choices") or [{}])[0].get("message", {}).get(
            "content"
        ) or ""
        if not content.strip():
            raise ValueError("LLM trả về rỗng")
        return content

    return call


def llm_callable_from_env() -> Optional[Callable[[str], str]]:
    base = os.environ.get("LONG_AGENT_LLM_BASE", "").strip()
    model = os.environ.get("LONG_AGENT_LLM_MODEL", "").strip()
    if not base or not model:
        logger.info(
            "[LLMClient] Chưa cấu hình LONG_AGENT_LLM_BASE/MODEL: dùng chẩn đoán giả lập."
        )
        return None
    extra = json.loads(os.environ.get("LONG_AGENT_LLM_EXTRA_BODY") or "{}")
    logger.info(f"[LLMClient] Chẩn đoán bằng LLM {model} tại {base}")
    return make_llm_callable(
        base, model, os.environ.get("LONG_AGENT_LLM_KEY", ""), extra
    )
