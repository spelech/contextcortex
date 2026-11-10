# System Settings and Model Discovery

The **Settings** view allows administrators to manage vector database engines, embedding models, LiteLLM proxy discovery, file thresholds, and domain-level Git credentials.

---

![Settings](/assets/desktop_settings.png)

## 1. Vector Database Management

ContextCortex supports dynamic switching between vector database engines:

- **Supported Backends**:
  - `PostgreSQL (pgvector)`: PostgreSQL 16 relational database with `pgvector` HNSW cosine search and GIN Full-Text Search (`tsvector`) lexical/hybrid fusion.
  - `Qdrant`: High-performance embedded disk or remote vector database with native dense + sparse BM25 hybrid fusion.
- **Connection Testing**: Click **Test Connection** to verify host connectivity, port reachability, and collection state before applying changes.
- **Operating Modes**: Use **PostgreSQL Server** (`DATABASE_URL` or custom DSN) for `pgvector`, or toggle between **Embedded Disk Storage** and **Remote Server URL** for `Qdrant`.

---

## 2. AI & Model Gateway (OpenAI-Compatible Discovery)

The **AI & Model Gateway** panel configures your OpenAI-compatible endpoint (`/admin/api/settings/ai-gateway` and `/admin/api/settings/embedding`). All active models are discovered and selected directly in the UI:

1. Enter your **API Endpoint URL** (`OPENAI_API_URL`, e.g. `http://litellm:4000/v1` or `https://gateway.example.com/api/v3`) and **API Key** (`OPENAI_API_KEY`).
2. Click **Test Connection & Discover Models** (`/admin/api/models/discover`) to query the upstream `/models` catalog and populate the model selectors.
3. Choose your **API Embedding Model**, **Chat Completion Model**, and **Vision OCR Model** from the discovered dropdowns and click **Save AI Gateway Settings**:
   - **API Embedding Models**: Filtered by embedding capabilities (e.g. `text-embedding-3-small`, `gemini-embedding-2`, `BAAI/bge-small-en-v1.5`).
   - **Vision OCR Models**: Multi-modal vision models used to perform automated OCR on diagrams and scanned pages in PDF uploads (e.g. `flash-latest`, `qwen3-vl`). If left unconfigured, PDF ingestion extracts native digital text and skips vision OCR fallback.
   - **Chat & Summarization Models**: Reasoning models used to generate structured executive summaries for large files (e.g. `flash-latest`, `gpt-4o-mini`). If left unconfigured, automated LLM file summarization is skipped until a model is selected.
- **Versioned Gateway Base URLs**: Custom gateway paths (such as `https://gateway.example.com/api/v3`) are preserved verbatim across model discovery (`/api/v3/models`), embeddings (`/api/v3/embeddings`), file summarization, and PDF vision OCR.
- **Custom Request Headers & Private CA Trust**: Gateways requiring identity or routing headers in addition to `Authorization` can be configured via the `LLM_EXTRA_HEADERS` JSON environment variable, and internal TLS certificates placed in `certs/*.crt` (`EXTRA_CA_CERTS_DIR`) are trusted automatically at container startup. See [Configuration](/guide/configuration) and [Restricted-Network Builds](/guide/enterprise-build) for details.

---

## 3. Files & Large File Summarization Settings

Configure file access ceilings and LLM summarization thresholds:

| Setting | Default | Description |
|---|---|---|
| **Enable Large File Summarization** | `true` | When enabled, files larger than the threshold are auto-summarized rather than omitted or raw-chunked. |
| **Auto-Summarize Threshold (KB)** | `500 KB` | File size threshold beyond which ingestion triggers automated LLM summarization. |
| **Maximum File Size (MB)** | `10 MB` | Absolute hard ceiling above which files are skipped entirely. |
| **Max Lines Per Read** | `2,000 lines` | Line range ceiling returned by the `read_file` tool to protect agent context windows. |
| **Summary Chat Model** | Configured via Model Discovery | Dedicated LLM model identifier selected from discovered gateway models for generating executive file summaries. |

---

## 4. Git Host Credential Vault

Store domain-level credentials for internal and enterprise Git instances:

1. Scroll to the **Git Host Credentials** table.
2. Click **+ Add Host Credential**.
3. **Host Domain**: Enter the domain name (e.g. `gitlab.internal.company.com` or `git.selfhosted.net`).
4. **Auth User & Token**: Enter the service user and personal access token (PAT).
5. All repositories matching that host domain inherit these credentials automatically without needing individual tokens.

---

## Next Steps

- Inspect system health and operational traces in [Diagnostics and System Logs](/guide/user-guide/diagnostics).
- Customize dashboard palettes in [Appearance and Theme Customization](/guide/user-guide/themes).
