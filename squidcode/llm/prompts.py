"""LLM prompt templates, keyed by rewrite_style."""

from __future__ import annotations

from squidcode.rag.retriever import RAGContext

SYSTEM_BASE = (
    "You are a professional text rewriter. "
    "Rewrite the provided text according to the specified style. "
    "PRESERVE the original meaning completely. "
    "Output ONLY the rewritten text — no explanations, no commentary, no labels. "
    "Do not add introductory phrases like 'Here is the rewritten text'."
)

STYLE_INSTRUCTIONS = {
    "clarity": (
        "Rewrite for maximum clarity. Use simple, direct language. "
        "Shorten long sentences. Replace jargon with plain language. "
        "Active voice preferred."
    ),
    "simplify": (
        "Simplify the text for a general audience. "
        "Use shorter words and shorter sentences. "
        "Remove unnecessary complexity."
    ),
    "formal": (
        "Rewrite in a formal, professional tone. "
        "Use precise vocabulary. Maintain gravitas. "
        "Avoid colloquialisms and contractions."
    ),
    "eli5": (
        "Explain this text as if the reader is five years old. "
        "Use very simple words and analogies. "
        "Keep it brief and fun."
    ),
}


def build_system_prompt(style: str, rag_context: RAGContext | None = None) -> str:
    """Build the system prompt with style instructions and optional RAG context."""
    parts = [SYSTEM_BASE]

    style_instruction = STYLE_INSTRUCTIONS.get(style, STYLE_INSTRUCTIONS["clarity"])
    parts.append(f"\nStyle: {style_instruction}")

    if rag_context and not rag_context.is_empty():
        if rag_context.style_guides:
            parts.append("\nStyle guidelines to follow:")
            for guide in rag_context.style_guides:
                parts.append(f"- {guide}")

        if rag_context.glossary_terms:
            parts.append("\nTerm definitions:")
            for term in rag_context.glossary_terms:
                parts.append(f"- {term}")

        if rag_context.examples:
            parts.append("\nSimilar rewrite examples:")
            for ex in rag_context.examples:
                parts.append(f"- {ex}")

    return "\n".join(parts)


def build_user_prompt(texts: list[str], ids: list[str]) -> str:
    """Build the user prompt with batched text nodes.

    Uses sentinel delimiter format for parsing streaming output:
    ---ID:sq-N---
    Rewritten text
    """
    parts = []
    for text, ai_id in zip(texts, ids):
        parts.append(f"---ID:{ai_id}---")
        parts.append(text)
    return "\n".join(parts)
