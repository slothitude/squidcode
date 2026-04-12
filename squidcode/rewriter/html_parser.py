"""HTML parser: extract text nodes, assign data-ai-id attributes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup, Tag

# Tags whose descendants should never be rewritten
SKIP_PARENTS = frozenset({"script", "style", "textarea", "noscript", "code", "pre"})

MIN_TEXT_LENGTH = 10


@dataclass
class TextNode:
    ai_id: str
    original_text: str
    tag_name: str = "p"


@dataclass
class ParsedPage:
    modified_html: str
    text_nodes: list[TextNode] = field(default_factory=list)


def parse_html(html: str) -> ParsedPage:
    """Parse HTML, tag text nodes with data-ai-id, return modified HTML + node list."""
    soup = BeautifulSoup(html, "lxml")

    # lxml wraps in <html>, may add <body> — that's fine
    nodes: list[TextNode] = []
    counter = 0

    # Find all <p> elements (MVP scope)
    for el in soup.find_all("p"):
        if _should_skip(el):
            continue

        text = el.get_text(strip=True)
        if len(text) < MIN_TEXT_LENGTH:
            continue

        ai_id = f"sq-{counter}"
        el["data-ai-id"] = ai_id
        nodes.append(TextNode(ai_id=ai_id, original_text=text, tag_name=el.name))
        counter += 1

    modified = str(soup)
    return ParsedPage(modified_html=modified, text_nodes=nodes)


def _should_skip(el: Tag) -> bool:
    """Check if this element should be skipped (inside script, style, etc.)."""
    for parent in el.parents:
        if isinstance(parent, Tag) and parent.name in SKIP_PARENTS:
            return True
    return False
