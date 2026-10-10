import pytest
from unittest.mock import MagicMock, patch

from app.agent.rag_client import RAGClient


@pytest.mark.asyncio
async def test_rag_mock_search_refrigerant():
    client = RAGClient(mode="mock", stub_path="config/knowledge_stub.yaml")
    res = await client.search_manual("thiếu môi chất lạnh rò rỉ gas")

    assert res["source"] == "mock"
    assert "refrigerant" in res["answer"].lower() or "overheating" in res["answer"].lower()
    assert len(res["citations"]) > 0
    cit = res["citations"][0]
    assert cit["documentName"] == "DENSO-Compressor-Fault-Finding-Poster-A1_English.pdf"
    assert cit["pages"] == "1"


@pytest.mark.asyncio
async def test_rag_mock_search_fan_failure():
    client = RAGClient(mode="mock", stub_path="config/knowledge_stub.yaml")
    res = await client.search_manual("quạt dàn ngưng hỏng áp suất xả cao")

    assert res["source"] == "mock"
    assert len(res["citations"]) > 0
    assert "AC-Condenser-Installation-Manual-Multilingual_web.pdf" in [c["documentName"] for c in res["citations"]]


@pytest.mark.asyncio
async def test_rag_auto_fallback_when_live_fails():
    client = RAGClient(
        base_url="http://non-existent-host:9999",
        mode="auto",
        stub_path="config/knowledge_stub.yaml",
        timeout=0.5,
    )
    # Live will fail and immediately fallback to mock
    res = await client.search_manual("thiếu dầu bôi trơn POE PAG")

    assert res["source"] == "mock"
    assert "fallback_reason" in res
    assert len(res["citations"]) > 0


@pytest.mark.asyncio
async def test_rag_live_mode_mapping():
    mock_response_data = {
        "response": "Theo cẩm nang DENSO, cần vệ sinh dàn ngưng định kỳ.",
        "references": [
            {
                "reference_id": "ref-123",
                "file_path": "/workspace/docs/AC-Condenser-Installation-Manual-Multilingual_web.pdf",
                "content": ["Check condenser fins and fan motor."],
            }
        ],
        "response_time": 0.42,
        "llm_generated": True,
    }

    client = RAGClient(mode="live", timeout=2.0, gateway_url="")  # LightRAG /query directly
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = mock_response_data

    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        res = await client.search_manual("vệ sinh dàn ngưng")
        assert res["source"] == "live"
        assert res["answer"] == mock_response_data["response"]
        assert len(res["citations"]) == 1
        cit = res["citations"][0]
        assert cit["documentName"] == "AC-Condenser-Installation-Manual-Multilingual_web.pdf"
        assert cit["pages"] is None  # LightRAG does not fabricate page numbers


@pytest.mark.asyncio
async def test_rag_live_mode_asks_the_denso_gateway():
    gateway_reply = {
        "content": "Siết bu-lông SCV 6,9-10,8 Nm.",
        "citations": [{"id": "cit-1", "documentId": "Diesel_SCV", "documentName": "Diesel_SCV",
                       "pages": "4", "excerpt": "Fit the bolts and tighten them with 6.9 to 10.8 [Nm]."}],
        "grounded": True,
    }
    client = RAGClient(mode="live", timeout=2.0, gateway_url="http://gw:9700", gateway_token="tok")
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = gateway_reply

    with patch("httpx.AsyncClient.post", return_value=mock_resp) as post:
        res = await client.search_manual("mô-men siết SCV")
    url = post.call_args.args[0]
    kwargs = post.call_args.kwargs
    assert url == "http://gw:9700/agent/chat"
    assert kwargs["headers"] == {"Authorization": "Bearer tok"}
    assert kwargs["json"]["message"] == "mô-men siết SCV"
    assert kwargs["json"]["conversationId"].startswith("iot-rag-")
    assert res["source"] == "live" and res["grounded"] is True
    assert res["answer"] == gateway_reply["content"]
    assert res["citations"][0]["pages"] == "4"  # the gateway cites pages


@pytest.mark.asyncio
async def test_each_gateway_lookup_is_its_own_conversation():
    client = RAGClient(mode="live", timeout=2.0, gateway_url="http://gw:9700", gateway_token="")
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"content": "x", "citations": []}
    with patch("httpx.AsyncClient.post", return_value=mock_resp) as post:
        await client.search_manual("a")
        await client.search_manual("b")
    ids = [c.kwargs["json"]["conversationId"] for c in post.call_args_list]
    assert ids[0] != ids[1]
    assert post.call_args.kwargs["headers"] == {}  # no token: the gateway's guest level
