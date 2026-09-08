# Software Requirements Specification (SRS)

This document establishes the Software Requirements Specification for ContextCortex (version 2.12.0).

This specification is written in accordance with the **ASD-STE100 Simplified Technical English (Issue 9)** standard and ISO/IEC/IEEE 29148 requirements engineering standards.

---

## 1. Scope and System Purpose

ContextCortex is a Model Context Protocol (MCP) server that provides syntax-aware code retrieval and repository intelligence for artificial intelligence agents and human software engineers.

The system connects AI coding agents (such as Cursor, Claude Desktop, Antigravity, and Windsurf) to local codebases, documentation repositories, and architectural records.

ContextCortex provides:
- Abstract Syntax Tree (AST) code chunking across 10 programming languages.
- Dual relational storage engines (PostgreSQL 16 and SQLite WAL).
- Pluggable vector database backends (Qdrant, pgvector, and ChromaDB).
- Hybrid semantic and lexical retrieval using Reciprocal Rank Fusion (RRF).
- Universal Git repository synchronization with ephemeral shallow clones.
- Managed local storage with automated PDF text extraction and vision OCR fallback.
- High-performance 3-pane codebase navigation and call graph tracing.
- RFC 9728 OAuth 2.1 authentication and 3-tier role-based access control.

---

## 2. Requirements Structure

The requirements are organized into three primary sections:

1. **[Functional Requirements](/requirements/functional)**:
   Specifies the functional behavior, data operations, MCP tools, and user interface capabilities.

2. **[Non-Functional Requirements](/requirements/non-functional)**:
   Defines performance targets, security standards, maintainability floors (sub-500 LOC per file), and reliability constraints.

3. **[Verification and Test Matrix](/requirements/verification)**:
   Traces each requirement directly to the automated test suite comprising **923 automated tests** (611 Backend Pytest + 266 Frontend Vitest + 46 Playwright E2E).
