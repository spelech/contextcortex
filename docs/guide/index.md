# Overview of ContextCortex

ContextCortex is a Model Context Protocol (MCP) server for syntax-aware code search and repository intelligence. It connects AI coding assistants to local codebases, documentation, and architecture records.

ContextCortex uses the official Model Context Protocol Python SDK 2.0 (`FastMCP`). The server provides dual communication channels: Server-Sent Events (SSE) and streamable HTTP.

## Purpose

Artificial intelligence agents require fast and accurate context to write good code. Traditional search methods do not understand code syntax or relationship structures.

ContextCortex solves this problem. It parses source files into Abstract Syntax Trees (AST) with Tree-sitter. It extracts functions, classes, API routes, and relationships. It stores text and code chunks in vector databases with dense and sparse embeddings.

## Key Capabilities

- **Syntax-Aware Code Search**:
  The system chunks code along function and class boundaries. It indexes exact line numbers and symbol names.
- **Dual Relational Architecture**:
  The system supports PostgreSQL 16 with pgvector for production deployments. It also supports SQLite with Write-Ahead Logging (WAL) for zero-dependency local use.
- **Multi-Vector Retrieval**:
  ContextCortex connects to Qdrant, ChromaDB, and PostgreSQL pgvector. It combines dense semantic vectors with BM25 lexical keywords using Reciprocal Rank Fusion (RRF).
- **Universal Git Ingestion**:
  The system indexes repositories from GitHub, GitLab, Gitea, Forgejo, Bitbucket, and generic Git hosts. It uses shallow clones and removes files after indexing to save disk space.
- **Managed Local Storage**:
  Users can upload files and PDF documents directly to the system. The system indexes text immediately and extracts text from images with optical character recognition (OCR).
- **3-Pane Codebase Navigator**:
  A web interface provides file trees, symbol outlines, and caller-callee relationship graphs.
- **Security and Access Control**:
  The server supports OAuth 2.1 (RFC 9728) and database-backed API keys. It enforces role-based access control with three privilege levels: Viewer, Editor, and Admin.

## Writing Standard Compliance

This documentation complies with the ASD-STE100 Simplified Technical English standard (Issue 9). ASD-STE100 establishes clear writing rules:

1. Sentences contain a maximum of 20 words in procedural instructions.
2. Sentences contain a maximum of 25 words in descriptive explanations.
3. Instructions use the imperative mood (command form).
4. Passive voice is avoided. Active voice is used.
5. Technical terms are clear and unambiguous. Contractions are not permitted.
6. Safety information uses standard alert levels (WARNING, CAUTION, NOTE).
