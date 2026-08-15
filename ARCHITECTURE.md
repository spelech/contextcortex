# Architecture: Notes & Code RAG MCP Server (v2.0.0)

The Notes & Code RAG MCP Server provides fast, local, syntax-aware semantic and hybrid search over codebases, git repositories, markdown notes, and system documentation.

## Core Components

### 1. AST Code & Documentation Parsing Engine (`chunker.py`)
- **Tree-sitter AST Parser**: Extracts logical functions, methods, classes, and structs across Python, TypeScript/JavaScript, Go, Rust, C#, C++, Java, Ruby, PHP, and more.
- **Contextual Markdown Chunker**: Chunks documentation files by header hierarchies (`#`, `##`, `###`) with breadcrumb enrichment.
- **Line & Symbol Tracking**: Preserves exact start/end line numbers, symbol names, and signatures for instant navigation.

### 2. Hybrid Embedding & Vector Engine (`embeddings.py`)
- **Named Multi-Vectors**: Uses Qdrant collections configured with both **Dense** vectors (`BAAI/bge-small-en-v1.5`, 384 dimensions) and **Sparse BM25** vectors (`Qdrant/bm25` via FastEmbed).
- **Reciprocal Rank Fusion (RRF)**: Merges conceptual dense vector similarity with exact keyword matching in a single query execution.
- **In-Process ONNX**: Zero external API costs, running locally on CPU.

### 3. Ephemeral Git Repository Ingestion (`git_manager.py`)
- **Shallow Cloning**: Clones repositories with `git clone --depth 1 --branch <branch> --single-branch` into temporary storage.
- **Commit SHA Tracking**: Records remote commit SHAs and supports `git ls-remote` checks to avoid redundant clones.
- **Zero Disk Bloat**: Prunes cloned directories immediately after vector upserts.
- **GitHub Permalinks**: Formats clickable GitHub line range links (`https://github.com/owner/repo/blob/<sha>/src/file.py#L10-L30`).
- **Token Management**: Resolves tokens from per-repo overrides, internal SQLite database, or `GITHUB_TOKEN` environment variables, boosting rate limits to 5,000 req/hr.

### 4. Database & Symbol Index (`db.py`)
- **SQLite Registry**:
  - `git_repositories`: Registered remote Git repos, branches, and commit SHAs.
  - `indexed_paths`: Monitored local directories and files.
  - `ast_symbols`: Indexed symbol table (classes, functions, methods, line numbers) for instant `find_symbol` and `get_file_outline`.
  - `indexed_files` & `file_summaries`: File metadata, mtime change detection, and topic tags.
  - `system_metadata`: Key-value storage for tokens and timestamps.

### 5. Specialized MCP Agent Tools (`server.py`)
- `search_code`: Hybrid semantic + BM25 search over code blocks with line numbers and GitHub links.
- `search_docs`: Dedicated search across markdown notes and architecture runbooks.
- `find_symbol`: Instant exact/fuzzy symbol lookup from AST index.
- `get_file_outline`: File symbol hierarchy without full token context costs.
- `list_repositories`: Summary of all indexed Git repos and local paths.
- `sync_repository`: On-demand re-sync for a specific repo or all sources.
- `index_status`: Global vector stats and GitHub rate limits.

### 6. Modern Web Admin Dashboard (`www/`)
- Multi-tab UI for Overview, Git Repositories, Local Paths, Live Search & RRF Inspector, and Settings.
