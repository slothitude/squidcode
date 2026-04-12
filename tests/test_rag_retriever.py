"""Tests for RAG retriever."""

import pytest
import tempfile

from squidcode.rag.retriever import Retriever, RAGContext
from squidcode.rag.store import RAGStore


class MockEmbedding:
    """Deterministic mock embedding for testing — produces 10-dim vectors."""

    def embed(self, text: str) -> list[float]:
        import hashlib
        h = hashlib.sha256(text.encode()).hexdigest()
        return [int(h[i:i+2], 16) / 255.0 for i in range(0, 20, 2)]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


@pytest.fixture
def mock_embedding():
    return MockEmbedding()


@pytest.fixture
def rag_store(tmp_path, mock_embedding):
    store = RAGStore(mock_embedding, persist_dir=str(tmp_path / "rag"))
    # Index some test data
    store.style_guides.add(
        ids=["sg-0"],
        embeddings=[mock_embedding.embed("Use active voice in technical writing")],
        documents=["Use active voice in technical writing"],
        metadatas=[{"source": "test", "type": "style_guide"}],
    )
    store.glossaries.add(
        ids=["gl-0"],
        embeddings=[mock_embedding.embed("API: Application Programming Interface")],
        documents=["API: Application Programming Interface"],
        metadatas=[{"source": "test", "type": "glossary"}],
    )
    return store


@pytest.fixture
def retriever(rag_store, mock_embedding):
    r = Retriever(rag_store, top_k=3)
    r._embedding_model = mock_embedding  # inject mock for retrieve()
    return r


class TestRetriever:
    @pytest.mark.asyncio
    async def test_retrieve_returns_context(self, retriever):
        ctx = await retriever.retrieve("Some random query about web development")
        assert isinstance(ctx, RAGContext)

    @pytest.mark.asyncio
    async def test_empty_context_check(self):
        ctx = RAGContext()
        assert ctx.is_empty()

    @pytest.mark.asyncio
    async def test_non_empty_context(self):
        ctx = RAGContext(style_guides=["some guide"])
        assert not ctx.is_empty()
