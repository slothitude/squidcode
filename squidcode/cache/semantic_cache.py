"""ChromaDB-backed semantic cache for rewrite results."""

from __future__ import annotations

import time
from typing import Optional

import chromadb
import structlog

from squidcode.cache.embedding import EmbeddingModel
from squidcode.config import settings

logger = structlog.get_logger("squidcode.cache")


class SemanticCache:
    """Semantic cache: embed text → query ChromaDB → return if similar enough."""

    def __init__(
        self,
        embedding_model: EmbeddingModel,
        persist_dir: str | None = None,
        threshold: float | None = None,
        ttl_hours: int | None = None,
    ):
        self.embedding = embedding_model
        self.threshold = threshold if threshold is not None else settings.cache_similarity_threshold
        self.ttl_hours = ttl_hours if ttl_hours is not None else settings.cache_ttl_hours

        client = chromadb.PersistentClient(path=persist_dir or settings.cache_persist_dir)
        self.collection = client.get_or_create_collection(
            name="semantic_cache",
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("cache.initialized", docs=self.collection.count())

    async def lookup(self, text: str) -> Optional[str]:
        """Check if a similar text has been cached. Returns rewrite or None."""
        embedding = self.embedding.embed(text)

        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=1,
            include=["metadatas", "distances"],
        )

        if not results["distances"] or not results["distances"][0]:
            return None

        distance = results["distances"][0][0]
        similarity = 1.0 - distance  # cosine distance → similarity

        if similarity < self.threshold:
            return None

        metadata = results["metadatas"][0][0]

        # TTL check
        timestamp = metadata.get("timestamp", 0)
        age_hours = (time.time() - timestamp) / 3600
        if age_hours >= self.ttl_hours:
            # Expired — delete and return miss
            doc_id = metadata.get("doc_id", "")
            if doc_id:
                self.collection.delete(ids=[doc_id])
            return None

        logger.debug("cache.hit", similarity=similarity)
        return metadata.get("rewritten", "")

    async def store(self, original_text: str, rewritten_text: str):
        """Store a rewrite in the semantic cache."""
        import hashlib

        doc_id = hashlib.sha256(original_text.encode()).hexdigest()[:16]
        embedding = self.embedding.embed(original_text)

        self.collection.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[original_text],
            metadatas=[{
                "rewritten": rewritten_text,
                "timestamp": time.time(),
                "doc_id": doc_id,
            }],
        )
        logger.debug("cache.stored", id=doc_id)

    def clear(self):
        """Wipe the cache."""
        all_ids = self.collection.get()["ids"]
        if all_ids:
            self.collection.delete(ids=all_ids)
        logger.info("cache.cleared")
