"""Minimal real test: one LLM rewrite through the full pipeline."""

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

ICAP_PORT = 11347
SSE_PORT = 18083

NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
NVIDIA_KEY = "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"
NVIDIA_MODEL = "minimaxai/minimax-m2.7"

sse_manager = SSEManager()
llm = AsyncOpenAI(base_url=NVIDIA_BASE, api_key=NVIDIA_KEY)
icap_loop = asyncio.new_event_loop()

def build_respmod(html_body: bytes) -> bytes:
    http_hdr = (
        f"HTTP/1.1 200 OK\r\n"
        f"Content-Type: text/html; charset=utf-8\r\n"
        f"Content-Length: {len(html_body)}\r\n"
    ).encode()
    chunk = f"{len(html_body):x}\r\n".encode() + html_body + b"\r\n0\r\n\r\n"
    offset = len(http_hdr) + 2
    return (
        b"RESPMOD icap://127.0.0.1/squidcode ICAP/1.0\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Connection: close\r\n"
        + f"Encapsulated: res-hdr=0, res-body={offset}\r\n".encode()
        + b"\r\n"
        + http_hdr + b"\r\n"
        + chunk
    )

def icap_send(raw):
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

async def rewrite_one(text: str) -> str:
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
    return resp.choices[0].message.content.strip()

async def rewrite_fn(body: bytes) -> bytes | None:
    html = body.decode("utf-8", errors="replace")
    page = parse_html(html)
    if not page.text_nodes:
        return None

    session_id = generate_session_id()
    sse_manager.create_session(session_id)
    modified = inject_runtime(page.modified_html, session_id, f"http://127.0.0.1:{SSE_PORT}")

    async def process():
        for node in page.text_nodes:
            try:
                t0 = time.time()
                rewritten = await rewrite_one(node.original_text)
                elapsed = time.time() - t0
                if not check_quality(node.original_text, rewritten):
                    rewritten = node.original_text
                await sse_manager.push_update(session_id, node.ai_id, rewritten)
                sys.stdout.write(f"\n  >> [{node.ai_id}] {elapsed:.1f}s DONE\n")
                sys.stdout.flush()
            except Exception as e:
                sys.stdout.write(f"\n  >> [{node.ai_id}] ERROR: {e}\n")
                sys.stdout.flush()
                await sse_manager.push_update(session_id, node.ai_id, node.original_text)

    asyncio.ensure_future(process(), loop=icap_loop)
    return modified.encode("utf-8")


print("=" * 70)
print("  SQUIDCODE — REAL PROXY TEST (single paragraph)")
print("  Model: minimaxai/minimax-m2.7 @ NVIDIA")
print("=" * 70)

# Only one paragraph to keep test fast
html = """<html>
<head><title>Test</title></head>
<body>
  <p>Researchers at the Massachusetts Institute of Technology have announced a groundbreaking discovery in the field of quantum physics that could revolutionize computing and telecommunications as we know them today.</p>
</body>
</html>"""

page = parse_html(html)
orig = page.text_nodes[0].original_text
print(f"\n  ORIGINAL:")
print(f"  {orig}")
print()

# Start servers
icap = ICAPServer(host="127.0.0.1", port=ICAP_PORT, rewrite_fn=rewrite_fn)

def run_icap():
    asyncio.set_event_loop(icap_loop)
    icap_loop.run_until_complete(icap.start())
    icap_loop.run_forever()

threading.Thread(target=run_icap, daemon=True).start()
time.sleep(0.5)

app = create_sse_app(sse_manager)
config = uvicorn.Config(app, host="127.0.0.1", port=SSE_PORT, log_level="error")
sse_server = uvicorn.Server(config)
threading.Thread(target=sse_server.run, daemon=True).start()
for _ in range(40):
    try:
        r = httpx.get(f"http://127.0.0.1:{SSE_PORT}/squidcode/health", timeout=1)
        if r.status_code == 200:
            break
    except Exception:
        pass
    time.sleep(0.1)

# Send through ICAP
print("  Sending through ICAP proxy...")
t0 = time.time()
icap_resp = icap_send(build_respmod(html.encode()))
icap_time = time.time() - t0

session_id = extract_session(icap_resp)
print(f"  ICAP responded in {icap_time:.2f}s")
print(f"  Session: {session_id}")
print(f"  data-ai-id: {'present' if 'data-ai-id' in icap_resp else 'missing'}")
print(f"  EventSource: {'present' if 'EventSource' in icap_resp else 'missing'}")
print()

# Read SSE for the LLM rewrite (wait up to 5 minutes)
print("  Waiting for LLM rewrite via SSE...")
print("-" * 70)

result = None
with httpx.stream(
    "GET",
    f"http://127.0.0.1:{SSE_PORT}/squidcode/sse/{session_id}",
    timeout=300,
) as r:
    deadline = time.time() + 280
    for line in r.iter_lines():
        if line.startswith("data: "):
            ev = json.loads(line[6:])
            result = ev["text"]
            break
        if time.time() > deadline:
            break

total_time = time.time() - t0

if result:
    print()
    print("=" * 70)
    print("  REWRITE COMPLETE")
    print("=" * 70)
    print()
    print(f"  BEFORE ({len(orig)} chars):")
    print(f"  {orig}")
    print()
    print(f"  AFTER ({len(result)} chars):")
    print(f"  {result}")
    print()
    delta = (len(result) - len(orig)) / max(len(orig), 1) * 100
    print(f"  Size change: {delta:+.0f}%")
    print(f"  ICAP latency: {icap_time:.2f}s (page render)")
    print(f"  LLM + SSE:    {total_time - icap_time:.1f}s")
    print(f"  Total:        {total_time:.1f}s")
    print("=" * 70)
else:
    print("  No rewrite received (timeout or error)")

icap_loop.call_soon_threadsafe(icap_loop.stop)
sse_server.should_exit = True
