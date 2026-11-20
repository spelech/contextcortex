# Configuration and Environment Variables

This document defines all configuration variables and runtime parameters for ContextCortex.

## Environment Variables Reference

Configure the application by setting these environment variables in the system environment or in a `.env` file.

| Variable Name | Description | Default Value | Example |
| :--- | :--- | :--- | :--- |
| `HOST` | Listen address. `localhost` binds both loopback addresses (`127.0.0.1` and `::1`). | `0.0.0.0` (Docker) / `localhost` (Windows portable) | `127.0.0.1` |
| `PORT` | HTTP server port for FastAPI, Web Admin Dashboard, and MCP endpoints. | `3000` | `3000` |
| `LOG_LEVEL` | Application log verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). | `INFO` | `INFO` |
| `DATABASE_URL` | SQLAlchemy connection string for relational data. | `sqlite:////app/data/index_cache.db` | `postgresql+psycopg://user:pass@postgres:5432/contextcortex` |
| `DATA_DIR` | Root directory for persistent application data. | `/app/data` | `/app/data` |
| `CACHE_DB_PATH` | File path for the SQLite relational database when `DATABASE_URL` is unset. | `/app/data/index_cache.db` | `/app/data/index_cache.db` |
| `LOCAL_STORAGE_PATH` | Host directory for managed file and document uploads. | `/app/data/storage` | `/drives/storage` |
| `VAULT_PATH` | Default path to the Markdown documentation directory seeded on first startup. | `/docs` | `/docs` |
| `TMP_REPOS_DIR` | Temporary directory for ephemeral shallow Git clones (`keep_shallow=false`). | `/tmp/contextcortex_repos` | `/tmp/contextcortex_repos` |
| `PERSISTENT_REPOS_DIR` | Storage directory for retained shallow Git clones (`keep_shallow=true`). | `/app/data/repos` | `/app/data/repos` |
| `GIT_CLONE_TIMEOUT_SECONDS` | Timeout in seconds for `git clone` and `git fetch` commands. | `300` | `600` |
| `VECTOR_STORE_PROVIDER` | Active vector search engine (`pgvector` or `qdrant`). | `pgvector` (PostgreSQL) / `qdrant` (SQLite) | `pgvector` |
| `VECTOR_STORE_MODE` | Qdrant deployment mode (`embedded` local disk or `remote` server). | `embedded` | `remote` |
| `VECTOR_STORE_STORAGE_PATH` | On-disk storage directory for embedded Qdrant (`QDRANT_STORAGE_PATH` alias). | `/app/data/qdrant_storage` | `/app/data/qdrant_storage` |
| `VECTOR_STORE_COLLECTION` | Name of the primary vector collection (`COLLECTION_NAME` alias). | `knowledge_rag_v1` | `knowledge_rag_v1` |
| `QDRANT_URL` | URL of the remote Qdrant service when `VECTOR_STORE_MODE=remote`. | `http://localhost:6333` | `http://10.0.0.10:6333` |
| `HYBRID_DENSE_WEIGHT` | Default dense semantic weight (`0.0` to `1.0`) for hybrid search fusion. | `0.5` | `0.7` |
| `OPENAI_API_URL` | OpenAI-compatible gateway base URL. The OpenAI SDK appends `/embeddings`, `/chat/completions`, and `/models`. | `http://litellm:4000/v1` | `https://gateway.example.com/api/v3` |
| `OPENAI_API_KEY` | API key or Bearer token for the OpenAI-compatible gateway. | `dummy` | `sk-xxxxxxxxxxxx` |
| `LLM_EXTRA_HEADERS` | JSON object of extra HTTP headers sent on every gateway request. | None | `{"X-User-Agent":"contextcortex","X-User-Name":"jdoe"}` |
| `EMBEDDING_PROVIDER` | Dense embedding execution backend: `local` (FastEmbed ONNX on CPU) or `api` (OpenAI-compatible `/embeddings` gateway). | `local` | `api` |
| `EMBEDDING_MODEL` | Active dense embedding model identifier. | `BAAI/bge-small-en-v1.5` (`local`) / `text-embedding-3-small` (`api`) | `text-embedding-3-small` |
| `SPARSE_MODEL` | Local FastEmbed sparse lexical model used for BM25 keyword weights. | `Qdrant/bm25` | `Qdrant/bm25` |
| `EMBEDDING_ALLOW_FALLBACK` | Allow fallback to a local FastEmbed dense model if API embedding initialization fails. | `false` | `true` |
| `EMBEDDING_FALLBACK_DENSE_MODEL` | Local dense model loaded when `EMBEDDING_ALLOW_FALLBACK=true`. | `BAAI/bge-small-en-v1.5` | `BAAI/bge-small-en-v1.5` |
| `EMBEDDING_NUM_THREADS` | Maximum CPU worker threads per local FastEmbed ONNX model (`EMBEDDING_PROVIDER=local` only). Has **no effect** on dense embeddings when `EMBEDDING_PROVIDER=api`. | `min(2, system_cpus)` | `4` |
| `EMBEDDING_BATCH_SIZE` | Number of text chunks sent per embedding call across files (clamped to `256` per API request). | `32` (`local`) / `128` (`api`) | `128` |
| `EMBEDDING_API_CONCURRENCY` | Maximum concurrent in-flight HTTP `/embeddings` requests during indexing when `EMBEDDING_PROVIDER=api`. | `4` | `8` |
| `EMBEDDING_MAX_TOKENS_PER_REQUEST` | Estimated token budget cap per API embedding request batch before splitting. | `100000` | `100000` |
| `EMBEDDING_MAX_TOKENS_PER_INPUT` | Estimated per-input token cap before truncating oversized chunks prior to batching. | `8000` | `8000` |
| `EMBEDDING_TPM_LIMIT` | Optional client-side tokens-per-minute pacing limit (`0` disables proactive pacing and relies on automatic HTTP `429` backoff). | `0` | `1000000` |
| `VISION_OCR_MODEL` | Multimodal vision model used for scanned PDF and diagram OCR fallback. | `gpt-4o-mini` | `gpt-4o-mini` |
| `CHAT_MODEL` | Default chat completion model used for large-file executive summarization. | `gpt-4o-mini` | `gpt-4o-mini` |
| `EXTRA_CA_CERTS_DIR` | Folder of private CA certificates (`*.crt`) added to the trust store at container start. | `/certs` | `/certs` |
| `MCP_ENABLE_WRITE_TOOLS` | Expose the state-mutating `manage` MCP tool (`sync_repo`, `upload`, `replace`, `delete`). | `false` | `true` |
| `CODE_MODE_ENABLED` | Enable the sandboxed `execute_script` Code Mode MCP tool. | `true` | `true` |
| `CODE_MODE_TIMEOUT_SECONDS` | Maximum wall-clock execution time in seconds for a single `execute_script` call. | `10.0` | `15.0` |
| `CODE_MODE_MAX_TOOL_CALLS` | Maximum inner `tools.*()` invocations allowed per `execute_script` run. | `50` | `50` |
| `CODE_MODE_MAX_MEMORY_MB` | Maximum QuickJS heap memory in megabytes per `execute_script` sandbox. | `64` | `64` |
| `AUTH_ENABLED` | Enable MCP OAuth 2.1 authentication and `cc_` API key validation. | `false` | `true` |
| `AUTH_OIDC_ISSUER` | OpenID Connect Identity Provider issuer URL. | None | `https://auth.company.com/realms/master` |
| `AUTH_JWKS_URI` | Custom JSON Web Key Set URL override for token verification. | None | `https://auth.company.com/realms/master/protocol/openid-connect/certs` |
| `AUTH_RESOURCE_INDICATOR` | RFC 8707 / RFC 9728 Resource Indicator URI for ContextCortex. | `https://contextcortex.local` | `https://contextcortex.example.com` |
| `ADMIN_INITIAL_KEY` | Bootstrap Admin API key seeded during container initialization. | None | `cc_admin_initial_secret` |
| `GLOBAL_WEBHOOK_SECRET` | Fallback HMAC secret for `/api/webhooks/git` when a repository has no per-repo secret. | None | `whsec_xxxxxxxxxxxx` |
| `GITHUB_TOKEN` | Global GitHub personal access token for higher API limits and private repositories. | None | `ghp_xxxxxxxxxxxx` |
| `GITLAB_TOKEN` | Global GitLab personal access token. | None | `glpat-xxxxxxxxxxxx` |
| `GITEA_TOKEN` | Global Gitea or Forgejo access token. | None | `xxxxxxxxxxxxxxxx` |
| `BITBUCKET_TOKEN` | Global Bitbucket App Password or repository access token. | None | `ATBBxxxxxxxxxxxxxxxx` |

> **Note on Auto-Sync Polling Interval:** Background repository polling (`auto_sync_interval_mins`, default `15` minutes) is stored in `system_metadata` and configured at runtime via **Settings → Repository Auto-Sync** or `POST /admin/api/settings/auto-sync`.

---

## Large Repositories

Indexing a large repository (`10,000+` files or `100,000+` AST chunks) behaves differently depending on whether dense embeddings run locally on CPU (`EMBEDDING_PROVIDER=local`) or through an external gateway (`EMBEDDING_PROVIDER=api`).

### 1. Why Adding CPU Cores or RAM Does Not Speed Up API Embedding
- When `EMBEDDING_PROVIDER=api`, dense vector generation is network-bound and rate-limit-bound on the upstream OpenAI-compatible gateway (`/v1/embeddings`), not CPU-bound on the ContextCortex host.
- `EMBEDDING_NUM_THREADS` controls ONNX Runtime threads **only** for local FastEmbed models (`EMBEDDING_PROVIDER=local` and local sparse BM25 tokenization). Changing `EMBEDDING_NUM_THREADS` has no effect on remote API embedding latency or concurrency.
- The Windows standalone portable bundle runs directly as native Win32 processes (`python.exe` and `postgres.exe`) without a hypervisor or container cgroup limit. It already has access to all host CPU cores and system memory.

### 2. Cross-File Chunk Batching and Parallel Requests
- ContextCortex does not issue one HTTP `/embeddings` call per file. During repository synchronization, the indexer parses files in super-batches, collects all resulting AST and document chunks across files into a unified buffer, and packs them into large request batches.
- Each API request packs up to `EMBEDDING_BATCH_SIZE` chunks (default `128` for `api`, `32` for `local`, capped at `256` per request) while keeping estimated tokens below `EMBEDDING_MAX_TOKENS_PER_REQUEST` (default `100000` tokens).
- When `EMBEDDING_PROVIDER=api`, the embedding engine dispatches up to `EMBEDDING_API_CONCURRENCY` (default `4`) batches in parallel across a thread pool and reassembles vectors in deterministic chunk order before upserting to PostgreSQL `pgvector` or Qdrant.

### 3. Automatic HTTP `429` Rate-Limit Handling and Sync Telemetry
- Enterprise gateways (such as Azure OpenAI standard tiers or LiteLLM proxies) enforce Tokens-Per-Minute (TPM) and Requests-Per-Minute (RPM) quotas and return HTTP `429 Too Many Requests` when saturated.
- ContextCortex handles HTTP `429` responses automatically:
  1. **Header-Aware Backoff**: Reads `Retry-After-ms`, `Retry-After`, or `x-ratelimit-reset-tokens` / `x-ratelimit-reset-requests` headers from the gateway response (falling back to exponential backoff with jitter when no header is present).
  2. **Adaptive Concurrency (AIMD)**: Halves the active in-flight request limit immediately upon a `429` response and gradually scales concurrency back up to `EMBEDDING_API_CONCURRENCY` after consecutive successful batches.
  3. **Optional Proactive Pacing**: Set `EMBEDDING_TPM_LIMIT` (for example `EMBEDDING_TPM_LIMIT=1000000`) to enable a client-side token bucket that paces requests before hitting gateway `429` responses.
- **Inspecting Live Throughput and `429` Wait Time**: Query `GET /admin/api/repos/{repo_id}/sync-status` (or watch the live progress banner in the **Git Repositories** tab) to inspect real-time indexing metrics:
  - `chunks_embedded` and `chunks_per_sec`: Rolling embedding throughput in chunks per second.
  - `embed_batches_completed` / `embed_batches_total` and `in_flight_requests`: Active batch pipeline progress and current concurrency window.
  - `rate_limit_429_count` and `rate_limit_wait_seconds`: Total HTTP `429` responses encountered and cumulative seconds spent waiting on gateway rate limits during the sync job.

---

## Database Profile Selection

ContextCortex supports two primary database profiles:

### 1. SQLite Profile (Default Development Mode)
- **Zero Configuration**: Requires no external database container.
- **Write-Ahead Logging (WAL)**: Automatically enabled for concurrent read and write operations.
- **Connection Timeout**: Set to 15000 milliseconds to avoid disk lock errors.
- **Relational Cache**: Stored on disk at `/app/data/index_cache.db`.

### 2. PostgreSQL 16 + pgvector Profile (Production Mode)
- **Enterprise Concurrency**: Full ACID transaction support across multiple worker threads.
- **Native Vector & Lexical Indexing**: Creates `vector` columns with HNSW cosine distance indexing (`vector_cosine_ops`) and GIN Full-Text Search (`tsvector`) indexes for hybrid retrieval.
- **Connection Pooling**: Uses `psycopg3` pooled connections with automatic retry loops.
- **Configuration**:
  ```bash
  export DATABASE_URL="postgresql+psycopg://contextcortex:cortexsecret@postgres:5432/contextcortex"
  export VECTOR_STORE_PROVIDER="pgvector"
  ```

---

## Vector Store Configuration

### Qdrant Mode
ContextCortex connects to Qdrant for dense and sparse BM25 hybrid search.
- When `QDRANT_URL` is specified, the system connects to the remote Qdrant service.
- If no remote service is specified, the system operates in local embedded disk mode at `/app/data/qdrant_storage`.

### PostgreSQL / pgvector Mode

Initialization creates or migrates the vector table and its indexes in one transaction.
Legacy rows without a collection are assigned to `knowledge_rag_v1`; the primary key
becomes `(collection_name, id)`, allowing the same document ID in separate collections.
Initialization failures raise an explicit error and roll back schema changes rather
than leaving a partially migrated store. If `vector` is already installed, startup
does not attempt extension creation; otherwise the database role needs permission
to install it (or an administrator must install it first).

All collections in a table share one embedding dimension. Initialization never drops
a populated table to resolve a dimension mismatch. Coordinate an explicit rebuild
with every affected collection owner, clear their vectors and indexing metadata,
then initialize the empty table with the new dimension and reindex. Changing the
dimension of an empty table preserves its schema and does not clear unrelated
relational metadata.

Native regression tests require `TEST_POSTGRES_URL` pointing to a **disposable**
PostgreSQL database with pgvector available. They create a unique schema per test
and remove only that schema; do not use the application database. Run
`python -m pytest tests/test_pgvector_native.py`. Without that variable, the native
tests skip. Search tests use a deterministic loopback HTTP embedding service; no
embedding model downloads are required.

---

## OpenAI-Compatible AI Gateway & Dynamic Model Discovery

To connect any OpenAI-compatible gateway (internal gateway, LiteLLM, vLLM, Ollama, or OpenAI) and discover models in the UI:

1. Configure your gateway endpoint and API key:
   ```bash
   export OPENAI_API_URL="http://litellm:4000/v1"
   export OPENAI_API_KEY="sk-your-gateway-key"
   ```

2. Open the **Settings → AI & Model Gateway** tab in the Web Dashboard.
3. Click **Test Connection & Discover Models** to query your gateway's `/models` endpoint.
4. Select your preferred **API Embedding Model**, **Chat Completion Model**, and **Vision OCR Model** from the discovered dropdowns and click **Save AI Gateway Settings**.

> **Database priority:** On first startup, ContextCortex seeds the initial gateway URL (`OPENAI_API_URL`) into `system_metadata`. Once saved in the **Settings** UI, database values take priority across restarts.

### Model discovery URL

Model discovery calls `{OPENAI_API_URL}/models`. If the URL has no path (for example `http://litellm:4000`), discovery calls `/v1/models`.

| `OPENAI_API_URL` | Discovery endpoint |
| :--- | :--- |
| `http://litellm:4000` | `http://litellm:4000/v1/models` |
| `http://litellm:4000/v1` | `http://litellm:4000/v1/models` |
| `https://gateway.example.com/api/v3` | `https://gateway.example.com/api/v3/models` |

### Gateways that need extra headers

Some gateways need headers in addition to `Authorization`, for example an identity header. Set `LLM_EXTRA_HEADERS` to a JSON object. ContextCortex sends these headers on embedding, summary, OCR, and model discovery requests:

```bash
export LLM_EXTRA_HEADERS='{"X-User-Agent":"contextcortex","X-User-Name":"jdoe"}'
```

If the value is not a valid JSON object, ContextCortex logs a warning and sends no extra headers.

---

## Private CA Certificates

For private package mirrors, 30-day package quarantine, and image-overlay builds,
see [Restricted-network builds and local deployment](enterprise-build.md#private-trust-and-configuration).

If your LLM gateway, your Git server, or a TLS-inspecting proxy uses a certificate from a private certificate authority, put the PEM-encoded CA certificates (`*.crt`) in the `certs/` folder:

- **Build time:** `docker compose build` adds the certificates to the trust store of the image, so `npm ci` and `pip install` trust them.
- **Run time:** `docker-compose.yml` mounts `./certs` at `/certs`. At container start, `docker-entrypoint.sh` adds each `*.crt` file to the system trust store. This also works with the pre-built image.

Python (`httpx`, `openai`, `requests`) and Git use `/etc/ssl/certs/ca-certificates.crt` through `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, and `GIT_SSL_CAINFO`. Git does not track the `*.crt` files in `certs/`.
