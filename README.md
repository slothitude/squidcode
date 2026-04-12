# SquidCode v0.1

**Streaming Semantic Proxy** — AI-powered text rewriting through an ICAP-compatible Squid proxy. Every webpage your browser loads is rewritten in real-time by an LLM, with RAG-augmented context and semantic caching.

```
┌─────────┐    ┌──────────────┐    ┌──────────────┐    ┌─────────────┐
│ Browser │───▶│ Squid Proxy  │───▶│ ICAP Server  │───▶│  HTML Parser │
│  + SSE  │◀───│ (SSL bump)   │    │  (port 1344) │    │  + Injector  │
└────┬────┘    └──────────────┘    └──────┬───────┘    └──────┬──────┘
     │                                     │                    │
     │  SSE: rewritten text                │                    ▼
     │  (data-ai-id match)                 │            ┌──────────────┐
     │                                     │            │ Rewrite Pipe │
     │                                     │            │  RAG │ Cache  │
     │                                     │            └──────┬───────┘
     │                                     │                   │
     │                                     │                   ▼
     │                                     │            ┌──────────────┐
     └─────────────────────────────────────┘            │  LLM Client  │
                                                        │ (OpenAI API) │
                                                        └──────────────┘
```

## How It Works

1. **Browser** sends HTTP/HTTPS request through Squid proxy
2. **Squid** intercepts the response and forwards it to the ICAP server via `RESPMOD`
3. **ICAP handler** parses the HTML, tags each `<p>` with a `data-ai-id` attribute, injects an SSE client runtime, and returns the modified page
4. **Rewrite pipeline** runs asynchronously — each text node is checked against the semantic cache, enriched with RAG context, sent to the LLM, validated, and pushed to the SSE queue
5. **Browser runtime** receives SSE events and swaps DOM text in real-time

## Features

- **Real-time rewriting** — text updates live in the browser via Server-Sent Events
- **ICAP protocol** — standards-compliant; works with any ICAP-capable proxy
- **SSL bump** — HTTPS interception via Squid with auto-generated certificates
- **RAG-augmented** — style guides and glossaries improve rewrite quality
- **Semantic caching** — ChromaDB + `all-MiniLM-L6-v2` embeddings; 0.85 similarity threshold avoids redundant LLM calls
- **Quality validation** — rejects rewrites that drift more than 30% in length or contain artifacts
- **Batch processing** — nodes are batched (default 5) for throughput
- **Hot-swap** — rewritten text appears without a page reload

## Quick Start

```bash
# Install
git clone https://github.com/yourname/squidcode.git
cd squidcode
pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env — set LLM_API_KEY, LLM_BASE_URL, and LLM_MODEL

# Start the servers
python -m squidcode
```

This launches both the ICAP server (port 1344) and the SSE endpoint (port 8080). Point Squid at the ICAP server, configure your browser to use the proxy, and browse as normal.

## Configuration

All settings are environment variables (or `.env` file):

| Variable | Default | Description |
|---|---|---|
| `ICAP_HOST` | `0.0.0.0` | ICAP server bind address |
| `ICAP_PORT` | `1344` | ICAP server port |
| `SSE_HOST` | `0.0.0.0` | SSE server bind address |
| `SSE_PORT` | `8080` | SSE server port |
| `LLM_API_KEY` | — | OpenAI-compatible API key |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | LLM API base URL |
| `LLM_MODEL` | `gpt-4o-mini` | Model identifier |
| `LLM_TEMPERATURE` | `0.3` | Sampling temperature |
| `REWRITE_STYLE` | `clarity` | Default rewrite style |
| `BATCH_SIZE` | `5` | Nodes per rewrite batch |
| `CACHE_SIMILARITY_THRESHOLD` | `0.85` | Cosine similarity for cache hit |
| `CACHE_TTL_HOURS` | `24` | Cache entry lifetime |
| `CACHE_PERSIST_DIR` | `./cache_db` | ChromaDB storage path |
| `RAG_DATA_DIR` | `./data` | RAG source data directory |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformers model |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

## Rewrite Styles

| Style | Effect |
|---|---|
| `clarity` | Simple, direct language. Active voice. Jargon replaced with plain language. |
| `simplify` | Shorter words and sentences for a general audience. |
| `formal` | Professional tone, precise vocabulary, no contractions. |
| `eli5` | Explain like I'm five — simple words, analogies, brief and fun. |

Set the default via `REWRITE_STYLE` in `.env`.

## RAG Indexing

Index style guides and glossaries before starting the server:

```bash
# Index a directory of style guide markdown/text files
python -m squidcode.rag.indexer --type style_guide --dir ./data/style_guides

# Index a JSON glossary file
python -m squidcode.rag.indexer --type glossary --file ./data/glossaries/general.json
```

Glossary JSON format:

```json
[
  {"term": "API", "definition": "Application Programming Interface"},
  {"term": "ICAP", "definition": "Internet Content Adaptation Protocol"}
]
```

## Squid Integration

### SSL Bump (HTTPS support)

Generate a CA certificate and import it into your browser:

```bash
./squid/generate_cert.sh
# Import squid/ssl_cert/ca.crt into your browser's trusted root certificates
```

### Squid Configuration

Key directives in `squid/squid.conf`:

```squid
# Enable SSL bump
http_port 3128 ssl-bump generate-host-certificates=on
sslcrtd_program /usr/lib/squid/security_file_certgen -s /var/lib/ssl_db -M 4MB

ssl_bump peek step1
ssl_bump stare step2
ssl_bump bump step3

# Enable ICAP
icap_enable on
icap_service squidcode respmod_precache icap://127.0.0.1:1344/squidcode
adaptation_access squidcode allow all
```

Then start Squid:

```bash
squid -z                # initialize cache directories
squid -f squid/squid.conf
```

## Project Structure

```
squidcode/
├── __init__.py              # Package root (v0.1.0)
├── __main__.py              # Entry point (python -m squidcode)
├── main.py                  # Starts ICAP + SSE servers
├── config.py                # Pydantic settings from env vars
├── icap/
│   ├── server.py            # Async TCP ICAP server
│   ├── handler.py           # RESPMOD / OPTIONS handling
│   └── protocol.py          # ICAP frame parser
├── llm/
│   ├── client.py            # OpenAI-compatible streaming client
│   └── prompts.py           # Style-specific system prompts
├── rag/
│   ├── indexer.py           # CLI: index style guides & glossaries
│   ├── retriever.py         # ChromaDB similarity search
│   └── store.py             # Collection management
├── rewriter/
│   ├── html_parser.py       # BeautifulSoup text node extraction
│   ├── pipeline.py          # Async rewrite orchestration
│   ├── script_injector.py   # Inject SSE runtime into HTML
│   └── text_batcher.py      # Batch nodes for LLM calls
├── cache/
│   ├── embedding.py         # Sentence-transformers singleton
│   └── semantic_cache.py    # ChromaDB-backed cache (TTL + similarity)
├── sse/
│   ├── endpoint.py          # FastAPI SSE route
│   └── manager.py           # Per-session event queues
├── runtime/
│   └── client.js            # Browser JS: SSE consumer + DOM swapper
└── utils/
    ├── quality.py           # Length delta + artifact checks
    └── session.py           # UUID session ID generation

squid/
├── squid.conf               # Squid proxy configuration
└── generate_cert.sh         # Self-signed CA for SSL bump

data/
├── style_guides/default.md  # Default writing style guide
└── glossaries/general.json  # Technical term definitions

tests/
├── test_html_parser.py      # HTML parsing and tagging
├── test_icap_protocol.py    # ICAP frame parsing
├── test_llm_client.py       # Prompt construction
├── test_pipeline.py         # Full pipeline with mocks
├── test_rag_retriever.py    # RAG retrieval
├── test_script_injector.py  # Runtime injection
├── test_semantic_cache.py   # Cache hit/miss/expiry
└── test_hotswap.py          # Integration: live servers + SSE
```

## Architecture

### ICAP Server
An async TCP server listening on port 1344. Handles `OPTIONS` (capability discovery) and `RESPMOD` (response modification). Non-HTML responses get a `204 No Modification` pass-through. HTML responses are parsed, tagged with `data-ai-id` attributes on eligible `<p>` nodes (10+ chars, not inside `<script>`/`<style>`/`<code>`/`<pre>`), injected with the SSE runtime, and returned to Squid.

### Rewrite Pipeline
Runs as a background `asyncio.Task` per request. Nodes are batched (headings first, then paragraphs). For each node the pipeline:
1. Checks the semantic cache (cosine similarity >= threshold)
2. Retrieves RAG context (style guides + glossaries)
3. Calls the LLM with a style-specific system prompt and context
4. Validates output quality (length within 30%, no suspicious tokens)
5. Stores in cache and pushes to the SSE queue

### SSE Endpoint
A FastAPI server on port 8080. Each browsing session gets a UUID. The browser runtime connects to `GET /squidcode/sse/{session_id}` and receives JSON events `{"id": "sq-N", "text": "..."}`. CORS-enabled for cross-origin access. Keepalive comments sent every 30 seconds.

### Browser Runtime
Zero-dependency JavaScript injected into every page. Reads the session ID from a `<meta>` tag, opens an SSE connection, and swaps DOM text by matching `data-ai-id` selectors. Includes a brief highlight animation for visual feedback.

## Testing

```bash
# Run all 49 tests (41 unit + 8 hotswap integration)
pytest tests/ -v

# Unit tests only (fast, no network)
pytest tests/ -v --ignore=tests/test_hotswap.py

# Run with a real LLM (requires .env with API key)
python test_llm_direct.py
```

## API Reference

### SSE Stream

```
GET /squidcode/sse/{session_id}
```

Returns `text/event-stream`. Events:

```
data: {"id": "sq-1", "text": "Rewritten paragraph content"}
```

### Health Check

```
GET /squidcode/health
```

Returns `{"status": "ok"}`.

### ICAP Service

```
OPTIONS icap://host:1344/squidcode
RESPMOD icap://host:1344/squidcode
```

## License

[MIT](LICENSE)
