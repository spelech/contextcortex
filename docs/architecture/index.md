# System Architecture: ContextCortex

ContextCortex provides fast, local, syntax-aware semantic and hybrid search over source code repositories, architecture documents, and notes. The system operates natively on the **Model Context Protocol (MCP) SDK 2.0.0+** using `FastMCP`.

All backend services and frontend components follow a modular architecture. Source code files maintain a strict **sub-500 LOC per file** maintainability limit.

---

## Architecture Principles

ContextCortex adheres to these core design principles:

1. **Syntax-Aware Parsing**:
   The system parses source code into Abstract Syntax Trees (AST) using Tree-sitter. It preserves semantic boundaries for functions, classes, and methods.

2. **Dual-Engine Relational Storage**:
   The relational layer supports both SQLite in Write-Ahead Logging (WAL) mode and PostgreSQL 16 with native pgvector indexing.

3. **Pluggable Vector Store Backends**:
   Vector storage adapters isolate search engines from application logic. Administrators can switch between Qdrant, pgvector, and ChromaDB without application restarts.

4. **Ephemeral Repository Ingestion**:
   To conserve disk storage, the system clones remote repositories using shallow clones (`--depth 1`). It extracts AST symbols and vector embeddings, then purges the cloned directory immediately.

5. **Security and Role-Based Access Control**:
   The server enforces RFC 9728 OAuth 2.1 authentication and cryptographically validated API keys across three permission levels (Viewer, Editor, and Admin).

---

## Architectural Documentation Map

- [System Design and Components](/architecture/system-design): Complete component diagram and runtime interaction flows.
- [Data Pipeline and Ingestion](/architecture/data-pipeline): AST chunking pipeline, vector embedding generation, and PDF processing.
- [MCP Protocol and Security](/architecture/mcp-protocol): Transports (SSE and Streamable HTTP), RFC 9728 discovery, and RBAC hierarchy.
- [Database and Storage Schema](/architecture/database-schema): Unified relational schema, entity relationships (ERD), and vector payload structures.
