import asyncio
import json
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.security import RequestContext
from app.rag.embedding import EmbeddingError, FakeEmbeddingProvider, OpenAICompatibleEmbedding, validate_vectors
from app.rag.ingestion import chunk_document
from app.rag.retrieval import fuse_ranks
from app.rag.schemas import KnowledgeInput
from app.tools.registry import get_tool
from scripts.ingest_knowledge import load_documents


def config(**kwargs):
    return Settings(_env_file=None, database_url="postgresql+asyncpg://localhost/unit_test", **kwargs)


def test_chunk_locator_complete_rule_overlap_and_oversized_paragraph():
    content = "条件一：完整规则。\n\n条件二：另一条完整规则。\n\n条件三：第三条规则。"
    chunks = chunk_document(content, size=28, overlap=14)
    assert len(chunks) == 2 and "条件二" in chunks[0].content and "条件二" in chunks[1].content
    for c in chunks:
        left, right = map(int, c.locator.split(";")[0][6:].split("-"))
        assert content[left:right] == c.content
    long = "条件：" + "完整规则" * 100
    assert chunk_document(long, size=100, overlap=0)[0].content == long
    with pytest.raises(ValueError):
        chunk_document(content, size=10, overlap=10)


@pytest.mark.parametrize("change", [
    {"version":0}, {"version":True}, {"content":" "}, {"scope_type":"product"},
    {"scope_type":"category"}, {"scope_type":"global", "category_code":"food"},
    {"valid_to":"2025-01-01T00:00:00Z"}, {"valid_from":"2026-01-01T00:00:00"}, {"actor_id":"fake"},
])
def test_document_validation(change):
    with pytest.raises(ValidationError):
        KnowledgeInput.model_validate({**load_documents()[0].model_dump(), **change})


async def test_fake_determinism_and_rrf():
    fake = FakeEmbeddingProvider()
    assert await fake.embed(["退货", "换货"]) == await fake.embed(["退货", "换货"])
    a, b, c = (UUID(int=i) for i in (1, 2, 3))
    scores = fuse_ranks([a, b], [b, c])
    assert scores[0] == (b, 1 / 62 + 1 / 61)
    assert fuse_ranks([], []) == [] and fuse_ranks([a, a], []) == [(a, 1 / 61)]


async def test_embedding_protocol_order_dimension_and_no_secret_echo():
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        assert request.url.path == "/v1/embeddings"
        return httpx.Response(200, json={"model":"model", "data":[
            {"index":1,"embedding":[0,1,0]}, {"index":0,"embedding":[1,0,0]}]})
    provider = OpenAICompatibleEmbedding(config(embedding_base_url="https://fake.invalid/v1", embedding_model="model",
        embedding_api_key="private-test-key", embedding_dim=3), transport=httpx.MockTransport(handler))
    assert await provider.embed(["a","b"]) == [[1,0,0],[0,1,0]]
    assert seen == [{"model":"model", "input":["a","b"], "encoding_format":"float"}]


@pytest.mark.parametrize("payload", [
    {}, {"data":[]}, {"data":[{"index":0,"embedding":[0,0]}]},
    {"data":[{"index":0,"embedding":[1,0,0]}]},
    {"data":[{"index":1,"embedding":[1,0]}]},
    {"data":[{"index":True,"embedding":[1,0]}]},
    {"data":[{"index":0,"embedding":[True,0]}]},
    {"model":"other", "data":[{"index":0,"embedding":[1,0]}]},
])
async def test_bad_embedding_response(payload):
    provider = OpenAICompatibleEmbedding(config(embedding_base_url="https://fake.invalid/v1", embedding_api_key="secret",
        embedding_model="model", embedding_dim=2), transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
    with pytest.raises(EmbeddingError) as exc:
        await provider.embed(["query"])
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize("status", [302, 400, 401, 429, 503])
async def test_embedding_http_failure_is_safe(status):
    provider = OpenAICompatibleEmbedding(config(embedding_base_url="https://fake.invalid/v1", embedding_api_key="secret",
        embedding_model="model"), transport=httpx.MockTransport(lambda request: httpx.Response(status, text="private-response")))
    with pytest.raises(EmbeddingError, match="embedding_unavailable"):
        await provider.embed(["query"])


async def test_timeout_missing_configuration_and_cancellation():
    with pytest.raises(EmbeddingError, match="not_configured"):
        await OpenAICompatibleEmbedding(config()).embed(["q"])
    async def handler(request):
        await asyncio.sleep(1)
    s = config(embedding_base_url="https://fake.invalid", embedding_model="model", embedding_api_key="secret", embedding_timeout_seconds=.01)
    with pytest.raises(EmbeddingError, match="unavailable"):
        await OpenAICompatibleEmbedding(s, transport=httpx.MockTransport(handler)).embed(["q"])
    async def cancel(request):
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await OpenAICompatibleEmbedding(s, transport=httpx.MockTransport(cancel)).embed(["q"])
    for vectors in ([[float("nan")]], [[float("inf")]], [[1],[1,2]], [[0]], [[1e100]]):
        with pytest.raises(EmbeddingError):
            validate_vectors(vectors, len(vectors))


@pytest.mark.parametrize("args", [{}, {"query":" "}, {"query":"q", "limit":0}, {"query":"q", "limit":True},
    {"query":"q", "product_id":"bad"}, {"query":"q", "relevant_date":"2026-01-01"}, {"query":"q", "sql":"SELECT 1"}])
async def test_policy_tool_invalid_argument(args):
    service = AsyncMock()
    result = await replace(get_tool("search_after_sales_policy"), service=service).invoke(args, session=AsyncMock(),
        context=RequestContext(uuid4(), frozenset(), uuid4()))
    assert result.status == "invalid_argument"
    service.assert_not_awaited()


@pytest.mark.parametrize("error", [EmbeddingError("safe"), TimeoutError(), ConnectionError()])
async def test_policy_tool_temporary(error):
    result = await replace(get_tool("search_after_sales_policy"), service=AsyncMock(side_effect=error)).invoke(
        {"query":"退货"}, session=AsyncMock(), context=RequestContext(uuid4(), frozenset(), uuid4()))
    assert result.status == "temporarily_unavailable" and result.data is None
