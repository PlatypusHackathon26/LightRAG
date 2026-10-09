import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
import httpx
import yaml

from app.config import resolve_file_path, settings

logger = logging.getLogger("app.agent.rag")


class RAGClient:
    """
    RAG Client interfacing with LightRAG /query or static mock knowledge stub.
    Supported modes:
    - live: calls LightRAG /query (defaults to mode='mix')
    - mock: uses static entries from config/knowledge_stub.yaml
    - auto: tries live with timeout; on failure/timeout falls back to mock and sets source='mock'
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        mode: Optional[Literal["live", "mock", "auto"]] = None,
        stub_path: str = "config/knowledge_stub.yaml",
        timeout: float = 8.0,
    ):
        self.base_url = (base_url or settings.RAG_BASE_URL).rstrip("/")
        self.api_key = api_key or settings.RAG_API_KEY
        self.mode = mode or settings.RAG_MODE
        self.stub_path = stub_path
        self.timeout = timeout
        self._stub_entries: List[Dict[str, Any]] = []
        self._load_stub()

    def _load_stub(self):
        try:
            resolved = resolve_file_path(self.stub_path)
            if resolved.exists():
                with open(resolved, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    self._stub_entries = data.get("entries", []) if isinstance(data, dict) else []
        except Exception as e:
            logger.warning(f"Could not load knowledge stub from {self.stub_path}: {e}")
            self._stub_entries = []

    async def search_manual(self, query: str) -> Dict[str, Any]:
        """
        Unified search method.
        Returns:
            {
                "answer": str,
                "citations": List[Dict[str, Any]],  # [{id, documentId, documentName, pages, excerpt}]
                "source": "live" | "mock",
                "raw_response": Optional[Dict[str, Any]]
            }
        """
        req_mode = self.mode.lower()

        if req_mode == "mock":
            return self._search_mock(query)

        if req_mode == "live":
            return await self._search_live(query)

        # auto mode: try live, fallback to mock
        try:
            return await self._search_live(query)
        except Exception as e:
            logger.warning(
                f"LightRAG live query failed in 'auto' mode ({e}). Falling back to mock knowledge stub."
            )
            mock_res = self._search_mock(query)
            mock_res["fallback_reason"] = str(e)
            return mock_res

    async def _search_live(self, query: str) -> Dict[str, Any]:
        endpoint = f"{self.base_url}/query"
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key.strip():
            headers["X-API-Key"] = self.api_key
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "query": query,
            "mode": "mix",
            "stream": False,
            "include_references": True,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        # Parse QueryResponse: response, references: List[ReferenceItem]
        answer = data.get("response", "")
        raw_refs = data.get("references", []) or []

        citations: List[Dict[str, Any]] = []
        for idx, ref in enumerate(raw_refs):
            file_path = ref.get("file_path", "")
            doc_name = Path(file_path).name if file_path else f"Doc-{idx + 1}"
            content_snippets = ref.get("content", [])
            excerpt = (
                content_snippets[0][:200]
                if (content_snippets and isinstance(content_snippets, list))
                else ""
            )

            # Note: LightRAG does not return page numbers in reference schema.
            # We do NOT fabricate fake page numbers; we keep pages as None or "N/A"
            citations.append({
                "id": f"CIT-LIVE-{idx + 1}",
                "documentId": ref.get("reference_id") or f"ref-{idx + 1}",
                "documentName": doc_name,
                "pages": None,
                "excerpt": excerpt,
            })

        return {
            "answer": answer,
            "citations": citations,
            "source": "live",
            "raw_response": data,
        }

    def _search_mock(self, query: str) -> Dict[str, Any]:
        """
        Searches local knowledge stub by keyword relevance matching.
        """
        q_lower = query.lower()
        matched = []

        for entry in self._stub_entries:
            keywords = entry.get("keywords", [])
            score = 0
            for kw in keywords:
                if kw.lower() in q_lower:
                    score += 1
            if score > 0:
                matched.append((score, entry))

        # Sort by relevance score
        matched.sort(key=lambda x: x[0], reverse=True)

        if not matched:
            # If no direct keyword match, provide general guidance snippet
            matched = [(0, self._stub_entries[0])] if self._stub_entries else []

        answer_parts = []
        citations = []

        for idx, (_, entry) in enumerate(matched[:2]):
            content = entry.get("content", "")
            doc_file = entry.get("file", "DENSO-Technical-Manual.pdf")
            pages = entry.get("pages", "1")
            excerpt = entry.get("excerpt", content[:150])

            answer_parts.append(f"[{doc_file}, p.{pages}]: {content}")
            citations.append({
                "id": f"CIT-MOCK-{idx + 1}",
                "documentId": entry.get("id", f"doc-{idx + 1}"),
                "documentName": doc_file,
                "pages": str(pages),
                "excerpt": excerpt,
            })

        combined_answer = "\n\n".join(answer_parts) if answer_parts else "Không tìm thấy tài liệu phù hợp."

        return {
            "answer": combined_answer,
            "citations": citations,
            "source": "mock",
            "raw_response": None,
        }


rag_client = RAGClient()


async def search_manual(query: str) -> Dict[str, Any]:
    """Single unified function exported for the rest of the system."""
    return await rag_client.search_manual(query)
