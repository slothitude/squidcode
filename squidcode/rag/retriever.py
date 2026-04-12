"""RAG retriever: query collections, build context for prompt injection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import structlog

from squidcode.rag.store import RAGStore

logger = structlog.get_logger("squidcode.rag")

SIMILARITY_THRESHOLD = 0.7


@dataclass
class RAGContext:
    style_guides: list[str] = field(default_factory=list)
    glossary_terms: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.style_guides and not self.glossary_terms and not self.examples


class Retriever:
    """Query all RAG collections and return merged context."""

    def __init__(self, store: RAGStore, top_k: int = 3, embedding_model=None):
        self.store = store
        self.top_k = top_k
        self._embedding_model = embedding_model

    async def retrieve(self, text: str) -> RAGContext:
        """Retrieve relevant context for input text."""
        if self._embedding_model is None:
            from squidcode.cache.embedding import EmbeddingModel
            self._embedding_model = EmbeddingModel.get()

        embedding = self._embedding_model.embed(text)

        context = RAGContext()

        # Style guides
        context.style_guides = self._query_collection(
            self.store.style_guides, embedding
        )

        # Glossaries
        context.glossary_terms = self._query_collection(
            self.store.glossaries, embedding
        )

        # Examples
        context.examples = self._query_collection(
            self.store.examples, embedding
        )

        logger.debug(
            "rag.retrieved",
            style_guides=len(context.style_guides),
            glossary=len(context.glossary_terms),
            examples=len(context.examples),
        )

        return context

    def _query_collection(
        self, collection, embedding: list[float]
    ) -> list[str]:
        """Query a single collection and return matching documents."""
        if collection.count() == 0:
            return []

        results = collection.query(
            query_embeddings=[embedding],
            n_results=min(self.top_k, collection.count()),
            include=["documents", "distances"],
        )

        if not results["documents"] or not results["documents"][0]:
            return []

        docs = []
        for doc, dist in zip(results["documents"][0], results["distances"][0]):
            similarity = 1.0 - dist
            if similarity >= SIMILARITY_THRESHOLD:
                docs.append(doc)

        return docs
