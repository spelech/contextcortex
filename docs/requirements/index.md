# Software Requirements Specification (SRS)

This document establishes the Software Requirements Specification for ContextCortex (`v2.18.0`).

---

## 1. Scope and System Purpose

ContextCortex is a Model Context Protocol (MCP) server that provides syntax-aware code retrieval and repository intelligence for artificial intelligence agents and software engineers.

The system connects AI coding agents (such as Cursor, Claude Desktop, Antigravity, and Windsurf) and MCP gateways to local codebases, documentation repositories, and architectural records.

ContextCortex provides:
- Abstract Syntax Tree (AST) code chunking across 10 programming languages.
- Dual relational storage engines (PostgreSQL 16 and SQLite WAL).
- Pluggable vector database backends (Qdrant, `pgvector`, and ChromaDB).
- Calibrated hybrid semantic and lexical retrieval (`dense_weight`, `mode`) with score decomposition and AST signature enrichment.
- Universal Git repository synchronization with configurable ephemeral or persistent shallow clones (`keep_shallow`).
- Managed local storage with automated PDF text extraction, AI vision OCR fallback, and large-file executive summarization.
- Hero split-view Codebase Navigator with `Ctrl+K` Omni-Search, syntax-highlighted code viewer, and caller/callee impact tracing.
- Zero-allocation JSON-RPC `ping` health interception, RFC 9728 OAuth 2.1 authentication, and 3-tier role-based access control.

---

## 2. Requirements Structure

The requirements are organized into three primary sections:

1. **[Functional Requirements](/requirements/functional)**:
   Specifies the functional behavior, data operations, all 16 MCP tools, and user interface capabilities.

2. **[Non-Functional Requirements](/requirements/non-functional)**:
   Defines performance targets, security standards, maintainability limits (sub-500 LOC per file), and reliability constraints.

3. **[Verification and Test Matrix](/requirements/verification)**:
   Traces each requirement directly to the automated test suite comprising **1,037 automated tests** (**684 Backend Pytest + 303 Frontend Vitest + 50 Playwright E2E**).
