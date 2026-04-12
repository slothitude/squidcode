"""Inject SSE client script and session meta tag into HTML."""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

_CLIENT_JS_PATH = Path(__file__).parent.parent / "runtime" / "client.js"


def inject_runtime(html: str, session_id: str, sse_origin: str) -> str:
    """Inject session meta tag and SSE client script into HTML.

    Args:
        html: HTML string (may already have data-ai-id attributes).
        session_id: UUID session identifier.
        sse_origin: e.g. http://localhost:8080

    Returns:
        Modified HTML string.
    """
    soup = BeautifulSoup(html, "lxml")

    # Inject meta tag for session ID
    head = soup.find("head")
    if head is None:
        head = soup.new_tag("head")
        if soup.html:
            soup.html.insert(0, head)
        else:
            soup.insert(0, head)

    meta = soup.new_tag(
        "meta",
        attrs={"name": "squidcode-session", "content": session_id},
    )
    head.insert(0, meta)

    # Inject client script
    js = _load_client_js()
    # Replace placeholder with actual SSE origin
    js = js.replace("{{SSE_ORIGIN}}", sse_origin)

    script_tag = soup.new_tag("script", type="text/javascript")
    script_tag.string = js

    # Insert as last element in <head>, or before </body>
    body = soup.find("body")
    if body:
        body.append(script_tag)
    else:
        head.append(script_tag)

    return str(soup)


def _load_client_js() -> str:
    """Load the browser runtime JS file."""
    if _CLIENT_JS_PATH.exists():
        return _CLIENT_JS_PATH.read_text(encoding="utf-8")
    # Fallback minimal script if file doesn't exist
    return """(function(){var m=document.querySelector('meta[name="squidcode-session"]');if(!m)return;var s=m.getAttribute('content');var e=new EventSource('{{SSE_ORIGIN}}/squidcode/sse/'+s);e.onmessage=function(ev){var d=JSON.parse(ev.data);var el=document.querySelector('[data-ai-id="'+d.id+'"]');if(el){el.textContent=d.text;}};})();"""
