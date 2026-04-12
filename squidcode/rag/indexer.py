"""CLI tool to index documents into RAG collections.

Usage:
    python -m squidcode.rag.indexer --type style_guide --dir ./data/style_guides
    python -m squidcode.rag.indexer --type glossary --file ./data/glossaries/general.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import chromadb

from squidcode.cache.embedding import EmbeddingModel
from squidcode.config import settings
from squidcode.rag.store import RAGStore


def chunk_text(text: str, chunk_size: int = 300, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks of roughly chunk_size characters."""
    paragraphs = re.split(r'\n\s*\n', text)
    chunks = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current) + len(para) > chunk_size and current:
            chunks.append(current.strip())
            # Keep overlap
            words = current.split()
            overlap_words = words[-overlap // 5:] if len(words) > overlap // 5 else words
            current = " ".join(overlap_words) + " " + para
        else:
            current = current + " " + para if current else para

    if current.strip():
        chunks.append(current.strip())

    return chunks if chunks else [text]


def index_style_guides(store: RAGStore, directory: Path):
    """Index markdown/text style guide files."""
    embedding_model = EmbeddingModel.get(settings.embedding_model)

    files = list(directory.glob("*.md")) + list(directory.glob("*.txt"))
    if not files:
        print(f"No .md or .txt files found in {directory}")
        return

    for filepath in files:
        print(f"Indexing: {filepath.name}")
        text = filepath.read_text(encoding="utf-8")
        chunks = chunk_text(text)

        if not chunks:
            continue

        embeddings = embedding_model.embed_batch(chunks)
        ids = [f"sg-{filepath.stem}-{i}" for i in range(len(chunks))]

        store.style_guides.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=[{"source": filepath.name, "type": "style_guide"}] * len(chunks),
        )
        print(f"  Indexed {len(chunks)} chunks")

    print(f"Style guides collection: {store.style_guides.count()} total documents")


def index_glossary(store: RAGStore, filepath: Path):
    """Index a glossary JSON file. Format: [{"term": "...", "definition": "..."}, ...]"""
    embedding_model = EmbeddingModel.get(settings.embedding_model)

    data = json.loads(filepath.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        print("Expected JSON array of {term, definition} objects")
        return

    docs = [f"{item['term']}: {item['definition']}" for item in data if 'term' in item and 'definition' in item]
    if not docs:
        print("No valid glossary entries found")
        return

    embeddings = embedding_model.embed_batch(docs)
    ids = [f"gl-{i}" for i in range(len(docs))]

    store.glossaries.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=docs,
        metadatas=[{"source": filepath.name, "type": "glossary"}] * len(docs),
    )
    print(f"Indexed {len(docs)} glossary terms from {filepath.name}")


def main():
    parser = argparse.ArgumentParser(description="Index documents for RAG")
    parser.add_argument("--type", choices=["style_guide", "glossary"], required=True)
    parser.add_argument("--dir", type=Path, help="Directory of files to index")
    parser.add_argument("--file", type=Path, help="Single file to index")

    args = parser.parse_args()

    embedding_model = EmbeddingModel.get(settings.embedding_model)
    store = RAGStore(embedding_model)

    if args.type == "style_guide":
        directory = args.dir or Path(settings.rag_data_dir) / "style_guides"
        index_style_guides(store, directory)
    elif args.type == "glossary":
        filepath = args.file or Path(settings.rag_data_dir) / "glossaries" / "general.json"
        index_glossary(store, filepath)


if __name__ == "__main__":
    main()
