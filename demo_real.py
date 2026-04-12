"""Real end-to-end test with NVIDIA MiniMax LLM.

Flow:
  1. Test LLM connectivity
  2. Parse HTML, tag nodes
  3. Send each paragraph to MiniMax for rewriting
  4. Push rewrites to SSE
  5. Read SSE stream and show live results
  6. Then send same HTML through the full ICAP proxy
"""

import asyncio
import json
import socket
import threading
import time
import re
import sys

import httpx
import uvicorn
from openai import AsyncOpenAI

from squidcode.icap.server import ICAPServer
from squidcode.sse.endpoint import create_sse_app
from squidcode.sse.manager import SSEManager
from squidcode.rewriter.html_parser import parse_html
from squidcode.rewriter.script_injector import inject_runtime
from squidcode.utils.session import generate_session_id
from squidcode.llm.prompts import build_system_prompt
from squidcode.utils.quality import check_quality

ICAP_PORT = 11346
SSE_PORT = 18082

NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
NVIDIA_KEY = "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"
NVIDIA_MODEL = "minimaxai/minimax-m2.7"

sse_manager = SSEManager()
llm = AsyncOpenAI(base_url=NVIDIA_BASE, api_key=NVIDIA_KEY)


# ── LLM call ─────────────────────────────────────────────────────────────────

async def rewrite_paragraph(text: str) -> str:
    """Rewrite a single paragraph for clarity using MiniMax."""
    system = build_system_prompt("clarity")
    resp = await llm.chat.completions.create(
        model=NVIDIA_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        temperature=0.3,
        max_tokens=512,
    )
    result = resp.choices[0].message.content.strip()
    # Strip any sentinel delimiters the model might add
    result = re.sub(r'---ID:sq-\d+---\s*', '', result).strip()
    return result


# ── ICAP helpers ─────────────────────────────────────────────────────────────

def build_respmod(html_body: bytes) -> bytes:
    http_hdr = (
        f"HTTP/1.1 200 OK\r\n"
        f"Content-Type: text/html; charset=utf-8\r\n"
        f"Content-Length: {len(html_body)}\r\n"
    ).encode()
    chunk = f"{len(html_body):x}\r\n".encode() + html_body + b"\r\n0\r\n\r\n"
    offset = len(http_hdr) + 2
    return (
        b"RESPMOD icap://127.0.0.1:13446/squidcode ICAP/1.0\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Connection: close\r\n"
        + f"Encapsulated: res-hdr=0, res-body={offset}\r\n".encode()
        + b"\r\n"
        + http_hdr + b"\r\n"
        + chunk
    )

def icap_send(raw: bytes) -> str:
    sock = socket.create_connection(("127.0.0.1", ICAP_PORT), timeout=15)
    sock.sendall(raw)
    data = b""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            break
        data += chunk
    sock.close()
    return data.decode("utf-8", errors="replace")

def extract_session(resp):
    m = re.search(r'squidcode-session.*?content="([^"]+)"', resp)
    if not m:
        m = re.search(r'content="([^"]+)".*?squidcode-session', resp)
    return m.group(1) if m else None


# ── ICAP rewrite handler ────────────────────────────────────────────────────

icap_loop = asyncio.new_event_loop()

async def rewrite_fn(body: bytes) -> bytes | None:
    html = body.decode("utf-8", errors="replace")
    page = parse_html(html)
    if not page.text_nodes:
        return None

    session_id = generate_session_id()
    sse_manager.create_session(session_id)
    modified = inject_runtime(page.modified_html, session_id, f"http://127.0.0.1:{SSE_PORT}")

    # Fire-and-forget: rewrite nodes in background on this event loop
    async def process():
        for node in page.text_nodes:
            try:
                t0 = time.time()
                rewritten = await rewrite_paragraph(node.original_text)
                elapsed = time.time() - t0
                if not check_quality(node.original_text, rewritten):
                    rewritten = node.original_text
                await sse_manager.push_update(session_id, node.ai_id, rewritten)
                preview = rewritten[:70] + "..." if len(rewritten) > 70 else rewritten
                sys.stdout.write(f"\n    [{node.ai_id}] {elapsed:.1f}s >> {preview}\n")
                sys.stdout.flush()
            except Exception as e:
                sys.stdout.write(f"\n    [{node.ai_id}] ERROR: {e}\n")
                sys.stdout.flush()
                await sse_manager.push_update(session_id, node.ai_id, node.original_text)

    asyncio.ensure_future(process(), loop=icap_loop)
    return modified.encode("utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

print("=" * 70)
print("  SQUIDCODE v0.1 — REAL LLM PROXY TEST")
print("  Model: minimaxai/minimax-m2.7 @ NVIDIA API")
print("=" * 70)

# ── Step 1: Test LLM ────────────────────────────────────────────────────────

print("\n  [1/5] Testing LLM connection...")
t0 = time.time()
try:
    resp = asyncio.run(rewrite_paragraph("Say 'ready' in exactly one word."))
    print(f"        OK ({time.time()-t0:.1f}s): {resp[:60]}")
except Exception as e:
    print(f"        FAILED: {e}")
    sys.exit(1)

# ── Step 2: Start servers ───────────────────────────────────────────────────

print("\n  [2/5] Starting servers...")

icap = ICAPServer(host="127.0.0.1", port=ICAP_PORT, rewrite_fn=rewrite_fn)

def run_icap():
    asyncio.set_event_loop(icap_loop)
    icap_loop.run_until_complete(icap.start())
    icap_loop.run_forever()

icap_thread = threading.Thread(target=run_icap, daemon=True)
icap_thread.start()
time.sleep(0.5)

app = create_sse_app(sse_manager)
config = uvicorn.Config(app, host="127.0.0.1", port=SSE_PORT, log_level="error")
sse_server = uvicorn.Server(config)
sse_thread = threading.Thread(target=sse_server.run, daemon=True)
sse_thread.start()

for _ in range(40):
    try:
        r = httpx.get(f"http://127.0.0.1:{SSE_PORT}/squidcode/health", timeout=1)
        if r.status_code == 200:
            break
    except Exception:
        pass
    time.sleep(0.1)

print(f"        ICAP @ 127.0.0.1:{ICAP_PORT}")
print(f"        SSE  @ 127.0.0.1:{SSE_PORT}")

# ── Step 3: Parse HTML and show what we're sending ──────────────────────────

html_page = """<html>
<head><title>Tech News</title></head>
<body>
  <h1>Quantum Computing Reaches New Milestone</h1>
  <p>Researchers at the Massachusetts Institute of Technology have announced a groundbreaking discovery in the field of quantum physics that could revolutionize computing and telecommunications as we know them today.</p>
  <p>The team, led by Dr. Sarah Chen, observed a previously unknown type of entanglement between particles that were separated by distances exceeding one hundred kilometers, challenging existing theoretical frameworks.</p>
  <p>This discovery has significant implications for the development of quantum networks and could pave the way for unhackable communication systems that would transform cybersecurity across industries worldwide.</p>
  <p>The findings were published in the journal Nature and have already garnered attention from leading research institutions around the globe, with many calling it the most important physics breakthrough of the decade.</p>
</body>
</html>"""

page = parse_html(html_page)
print(f"\n  [3/5] HTML parsed: {len(page.text_nodes)} nodes to rewrite")
for n in page.text_nodes:
    preview = n.original_text[:65] + "..." if len(n.original_text) > 65 else n.original_text
    print(f"        [{n.ai_id}] {preview}")

# ── Step 4: Send through ICAP proxy ─────────────────────────────────────────

print(f"\n  [4/5] Sending HTML through ICAP proxy...")
print("-" * 70)

t_start = time.time()
icap_resp = icap_send(build_respmod(html_page.encode()))
t_icap = time.time() - t_start

session_id = extract_session(icap_resp)
tags = re.findall(r'data-ai-id="(sq-\d+)"', icap_resp)

print(f"\n  ICAP response in {t_icap:.2f}s")
print(f"  Session:  {session_id}")
print(f"  Tagged:   {len(tags)} nodes")
print(f"  Injected: script={'EventSource' in icap_resp}, meta={'squidcode-session' in icap_resp}")
print(f"\n  LLM rewrites streaming in (watch live):")

# ── Step 5: Read SSE stream for live results ────────────────────────────────

print("-" * 70)

events = {}
with httpx.stream(
    "GET",
    f"http://127.0.0.1:{SSE_PORT}/squidcode/sse/{session_id}",
    timeout=90,
) as r:
    deadline = time.time() + 85
    for line in r.iter_lines():
        if line.startswith("data: "):
            ev = json.loads(line[6:])
            events[ev["id"]] = ev["text"]
            if len(events) >= len(tags):
                break
        if time.time() > deadline:
            break

t_total = time.time() - t_start

# ── Results ──────────────────────────────────────────────────────────────────

originals = {n.ai_id: n.original_text for n in page.text_nodes}

print(f"\n\n  [5/5] BEFORE vs AFTER (real LLM rewrites)")
print("=" * 70)

for aid in tags:
    orig = originals.get(aid, "?")
    new = events.get(aid, "(not received)")
    orig_s = orig[:75] + "..." if len(orig) > 75 else orig
    new_s = new[:75] + "..." if len(new) > 75 else new
    delta = (len(new) - len(orig)) / max(len(orig), 1) * 100
    print(f"\n  [{aid}]")
    print(f"  BEFORE: {orig_s}")
    print(f"  AFTER:  {new_s}")
    print(f"  ({len(orig)} -> {len(new)} chars, {delta:+.0f}%)")

print(f"\n{'=' * 70}")
print(f"  DONE: {len(events)}/{len(tags)} rewrites in {t_total:.1f}s total")
print(f"  Avg:  {t_total/max(len(events),1):.1f}s per paragraph")
print(f"  ICAP latency (page render): {t_icap:.2f}s")
print(f"  LLM rewrite (background):   {t_total - t_icap:.1f}s")
print("=" * 70)

# Cleanup
icap_loop.call_soon_threadsafe(icap_loop.stop)
sse_server.should_exit = True
