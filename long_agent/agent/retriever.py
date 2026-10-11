"""Maintenance documents for the agent, from the LightRAG knowledge base.

Env:
  LONG_AGENT_RAG_URL   LightRAG server (e.g. http://127.0.0.1:9621); empty = no documents
  LIGHTRAG_API_KEY     sent as X-API-Key when set
Only the retrieved context is requested (`only_need_context`): the agent's own LLM call decides.
"""
from __future__ import annotations

import logging
import os
from typing import Callable, Optional

import httpx

logger = logging.getLogger("Retriever")


def make_retriever(base_url: str, api_key: str = "", timeout: float = 20.0,
                   max_chars: int = 6000) -> Callable[[str], str]:
    headers = {"X-API-Key": api_key} if api_key else {}
    url = base_url.rstrip("/") + "/query"

    def retrieve(question: str) -> str:
        r = httpx.post(url, json={"query": question, "mode": "naive", "only_need_context": True},
                       headers=headers, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        text = data.get("response") if isinstance(data, dict) else data
        return str(text or "")[:max_chars]

    return retrieve


def retriever_from_env() -> Optional[Callable[[str], str]]:
    base = os.environ.get("LONG_AGENT_RAG_URL", "").strip()
    if not base:
        logger.info("[Retriever] LONG_AGENT_RAG_URL chưa đặt: chẩn đoán không có tài liệu")
        return None
    return make_retriever(base, os.environ.get("LIGHTRAG_API_KEY", ""))
