"""Text node batcher: group nodes for LLM, prioritize headings."""

from __future__ import annotations

from squidcode.rewriter.html_parser import TextNode

# Tags considered headings (higher priority)
HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})


def batch_nodes(
    text_nodes: list[TextNode],
    batch_size: int = 5,
) -> list[list[TextNode]]:
    """Group text nodes into batches, with headings first.

    Returns batches where headings are in earlier batches.
    """
    if not text_nodes:
        return []

    headings = [n for n in text_nodes if n.tag_name in HEADING_TAGS]
    paragraphs = [n for n in text_nodes if n.tag_name not in HEADING_TAGS]

    ordered = headings + paragraphs
    batches = []

    for i in range(0, len(ordered), batch_size):
        batches.append(ordered[i : i + batch_size])

    return batches
