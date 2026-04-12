"""ChromaDB collections for RAG: style guides, glossaries, examples."""

from __future__ import annotations

import chromadb
import structlog

from squidcode.cache.embedding import EmbeddingModel
from squidcode.config import settings

logger = structlog.get_logger("squidcode.rag")


class RAGStore:
    """Manages RAG collections in ChromaDB."""

    def __init__(self, embedding_model: EmbeddingModel, persist_dir: str | None = None):
        self.embedding = embedding_model
        client = chromadb.PersistentClient(path=persist_dir or settings.cache_persist_dir)

        self.style_guides = client.get_or_create_collection(
            name="rag_style_guides",
            metadata={"hnsw:space": "cosine"},
        )
        self.glossaries = client.get_or_create_collection(
            name="rag_glossaries",
            metadata={"hnsw:space": "cosine"},
        )
        self.examples = client.get_or_create_collection(
            name="rag_examples",
            metadata={"hnsw:space": "cosine"},
        )

        logger.info(
            "rag.store_initialized",
            style_guides=self.style_guides.count(),
            glossaries=self.glossaries.count(),
            examples=self.examples.count(),
        )
