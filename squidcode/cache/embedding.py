"""Shared sentence-transformers embedding model wrapper."""

from __future__ import annotations

import threading
from typing import Optional

import structlog

logger = structlog.get_logger("squidcode.embedding")


class EmbeddingModel:
    """Singleton wrapper around sentence-transformers model.

    Loaded once at startup, reused across all requests.
    """

    _instance: Optional[EmbeddingModel] = None
    _lock = threading.Lock()

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None

    @classmethod
    def get(cls, model_name: str = "all-MiniLM-L6-v2") -> EmbeddingModel:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = cls(model_name)
                    inst._load()
                    cls._instance = inst
        return cls._instance

    def _load(self):
        logger.info("embedding.loading", model=self.model_name)
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(self.model_name)
        logger.info("embedding.loaded")

    def embed(self, text: str) -> list[float]:
        """Embed a single text string. Returns a list of floats."""
        result = self._model.encode(text, normalize_embeddings=True)
        return result.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts. Returns list of float lists."""
        results = self._model.encode(texts, normalize_embeddings=True)
        return [r.tolist() for r in results]
