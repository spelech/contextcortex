# Managed Local Storage and PDF Ingestion

The **Local Storage** view provides a browser-based file management and document ingestion portal directly on the server filesystem (`/app/data/storage`).

---

## Supported File Formats

ContextCortex supports ingestion across three primary document formats:

- **Markdown & Structured Text**: `.md`, `.txt`, `.json`, `.yaml`, `.csv`
- **Source Code**: `.py`, `.ts`, `.tsx`, `.js`, `.cs`, `.go`, `.rs`, `.java`, `.cpp`
- **PDF Documents**: `.pdf` up to 50 MB with native text extraction and automated AI vision OCR fallback.

---

## PDF Ingestion & OCR Preview Workflow

When uploading PDF files, ContextCortex provides an interactive inspection modal before ingesting content into the vector database:

1. In **Local Storage**, click **Upload File** and select your PDF file.
2. The **PDF Preview Modal** opens automatically:
   - **Page Browser**: Navigate through individual pages with thumbnail previews.
   - **Extracted Text Preview**: Review the extracted text stream.
   - **AI Vision OCR Status**: If native text density is low (scanned document or diagram), ContextCortex flags the page and invokes LiteLLM vision models (e.g. `gemini-2.5-flash` or `qwen3-vl`) to extract textual descriptions of diagrams and graphics.
3. Click **Confirm & Ingest to Vector DB**.
4. The document is chunked, embedded, and indexed into the vector store.

---

## Upload and Replacement Failures

Vector store initialization, deletion, or upsert failures return an error rather
than reporting the file as indexed. A failed new upload is removed from disk;
a failed replacement restores the previous file contents.

Once vector replacement starts, the previous index metadata is invalidated.
If indexing fails, the restored file is **not considered indexed**: retry the
upload or reindex the restored file after resolving the backend failure.
Incomplete vectors are cleaned up where possible; if the backend is unavailable,
the next successful retry deletes any remaining vectors before indexing.
Replacing a file with empty content succeeds with zero chunks and removes its
previous vectors.

---

## Large File Auto-Summarization

For large source code or documentation files exceeding the configured threshold (default: 500 KB):

- **Ceiling Protection**: ContextCortex bypasses raw multi-chunk embedding to preserve token budgets and search performance.
- **Structured LLM Summaries**: Automatically invokes LiteLLM to generate an executive structured markdown summary highlighting architecture, primary exported symbols, dependencies, and responsibilities.
- **Search Integration**: The executive summary is indexed into the vector store (`doc_type="summary"`) and cached in SQLite, keeping the large file completely discoverable.
- **Full & Sliced Reading**: MCP clients can retrieve bounded line ranges or full content using the [`read_file`](/reference/mcp-tools#15-read-file) tool and generate or refresh executive summaries on demand using [`summarize_file`](/reference/mcp-tools#16-summarize-file).

---

## Next Steps

- Configure thresholds and model discovery in [System Settings and Model Discovery](/guide/user-guide/settings).
- Monitor live server logs and ingestion events in [Diagnostics and System Logs](/guide/user-guide/diagnostics).
