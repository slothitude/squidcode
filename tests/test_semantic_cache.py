"""Tests for semantic cache."""

import pytest
import tempfile
import time

from squidcode.cache.semantic_cache import SemanticCache


class MockEmbedding:
    """Deterministic mock embedding for testing — produces 10-dim vectors."""

    def embed(self, text: str) -> list[float]:
        import hashlib
        h = hashlib.sha256(text.encode()).hexdigest()
        # sha256 gives 64 hex chars → 32 bytes → use first 10
        return [int(h[i:i+2], 16) / 255.0 for i in range(0, 20, 2)]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


@pytest.fixture
def cache(tmp_path):
    """Create a SemanticCache with mock embedding and temp directory."""
    embedding = MockEmbedding()
    return SemanticCache(
        embedding_model=embedding,
        persist_dir=str(tmp_path / "cache"),
        threshold=0.85,
        ttl_hours=24,
    )


class TestSemanticCache:
    @pytest.mark.asyncio
    async def test_store_and_lookup(self, cache):
        await cache.store("The quick brown fox", "The fast brown fox")
        result = await cache.lookup("The quick brown fox")
        assert result == "The fast brown fox"

    @pytest.mark.asyncio
    async def test_miss(self, cache):
        result = await cache.lookup("something never stored")
        assert result is None

    @pytest.mark.asyncio
    async def test_clear(self, cache):
        await cache.store("hello world test", "hi world test")
        cache.clear()
        result = await cache.lookup("hello world test")
        assert result is None

    @pytest.mark.asyncio
    async def test_ttl_expiry(self, tmp_path):
        embedding = MockEmbedding()
        c = SemanticCache(
            embedding_model=embedding,
            persist_dir=str(tmp_path / "cache_ttl"),
            threshold=0.85,
            ttl_hours=0,  # instant expiry
        )
        await c.store("expiry test text", "rewritten text")
        # TTL of 0 means it should expire immediately
        result = await c.lookup("expiry test text")
        assert result is None
