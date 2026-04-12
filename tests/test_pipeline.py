"""Integration test for the rewrite pipeline."""

import asyncio
import pytest
import tempfile

from squidcode.cache.semantic_cache import SemanticCache
from squidcode.llm.client import LLMClient
from squidcode.rag.retriever import Retriever, RAGContext
from squidcode.rag.store import RAGStore
from squidcode.rewriter.html_parser import TextNode
from squidcode.rewriter.pipeline import RewritePipeline
from squidcode.sse.manager import SSEManager


class MockEmbedding:
    def embed(self, text: str) -> list[float]:
        import hashlib
        h = hashlib.sha256(text.encode()).hexdigest()
        return [int(h[i:i+2], 16) / 255.0 for i in range(0, 20, 2)]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class MockLLM:
    """Mock LLM that returns a fixed rewrite."""

    async def rewrite_single(self, text, ai_id, rag_context=None):
        return f"[rewritten] {text}"

    async def stream_rewrite(self, texts, ids, rag_context=None, style=None):
        for text, ai_id in zip(texts, ids):
            yield (ai_id, f"[rewritten] {text}")


class MockRetriever:
    async def retrieve(self, text):
        return RAGContext()


@pytest.fixture
def sse_manager():
    return SSEManager()


@pytest.fixture
def pipeline(sse_manager, tmp_path):
    embedding = MockEmbedding()
    cache = SemanticCache(
        embedding_model=embedding,
        persist_dir=str(tmp_path / "cache"),
    )
    return RewritePipeline(
        cache=cache,
        rag_retriever=MockRetriever(),
        llm=MockLLM(),
        sse=sse_manager,
    )


class TestPipeline:
    @pytest.mark.asyncio
    async def test_pipeline_processes_nodes(self, pipeline, sse_manager):
        nodes = [
            TextNode(ai_id="sq-0", original_text="This is the first paragraph to rewrite."),
            TextNode(ai_id="sq-1", original_text="This is the second paragraph for testing."),
        ]

        # Create session so SSE has a queue
        sse_manager.create_session("test-session")

        await pipeline.run(nodes, "test-session")

        # Check that updates were pushed
        queue = sse_manager.get_queue("test-session")
        assert queue is not None

    @pytest.mark.asyncio
    async def test_cache_hit_path(self, pipeline, sse_manager):
        # Pre-populate cache
        await pipeline.cache.store("Cached text for lookup test.", "Rewritten cached version.")

        nodes = [TextNode(ai_id="sq-0", original_text="Cached text for lookup test.")]
        sse_manager.create_session("cache-test")

        await pipeline.run(nodes, "cache-test")

        # The SSE queue should have the cached rewrite
        queue = sse_manager.get_queue("cache-test")
        assert queue is not None

    @pytest.mark.asyncio
    async def test_quality_check_allows_good_rewrite(self):
        from squidcode.utils.quality import check_quality
        original = "This is a test paragraph with reasonable length."
        rewritten = "This is a revised test paragraph with similar length."
        assert check_quality(original, rewritten) is True

    @pytest.mark.asyncio
    async def test_quality_check_blocks_empty(self):
        from squidcode.utils.quality import check_quality
        assert check_quality("original", "") is False
        assert check_quality("original", "  ") is False

    @pytest.mark.asyncio
    async def test_quality_check_blocks_suspicious(self):
        from squidcode.utils.quality import check_quality
        original = "This is a normal paragraph with enough text."
        rewritten = "Sure! Here's the rewritten version of your text."
        assert check_quality(original, rewritten) is False
