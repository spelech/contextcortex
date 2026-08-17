# Test Coverage Report

This document outlines the current test coverage metrics for the `knowledge-rag-mcp` project following the major modular refactoring (v2.0.0).

## Backend (Python)
Overall Coverage: **29%** (1082 statements)

| Module | Coverage | Missed/Total Stmts |
|--------|----------|--------------------|
| `app/mcp/tools.py` | 12% | 211 / 240 |
| `app/models/schemas.py` | 100% | 0 / 70 |
| `app/services/chunker.py` | 50% | 72 / 145 |
| `app/services/db.py` | 52% | 39 / 82 |
| `app/services/embeddings.py` | 39% | 53 / 87 |
| `app/services/git_manager.py` | 20% | 82 / 102 |
| `app/services/indexer.py` | 12% | 291 / 331 |
| `app/services/search.py` | 28% | 18 / 25 |
| **Total** | **29%** | 766 / 1082 |

## Frontend (React TypeScript)
Overall Unit Coverage: **~7%**

| Component | Coverage |
|-----------|----------|
| `App.tsx` | 68.42% |
| `Overview.tsx` | 12.5% |
| `GitRepoManager.tsx` | 0% |
| `WatchPathManager.tsx` | 0% |
| `SearchInspector.tsx` | 0% |
| `Settings.tsx` | 0% |
| **Total** | **6.79%** |

*(Note: Playwright end-to-end tests also provide coverage across these components which is not fully reflected in the Vitest V8 unit metrics above.)*
