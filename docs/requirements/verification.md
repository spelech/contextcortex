# Verification and Test Matrix

ContextCortex is verified by an extensive automated test suite comprising **923 automated tests**:
- **611 Backend Tests** (Python Pytest suite with 88% code coverage baseline).
- **266 Frontend Tests** (React 19 / TypeScript Vitest unit and integration suite).
- **46 End-to-End Tests** (Playwright automated browser suite and Layout Inspector audits).

---

## Requirements Verification Traceability Matrix

| Requirement ID | Requirement Title | Verification Method | Associated Test Modules |
| :--- | :--- | :--- | :--- |
| **FR-01** | AST Code Chunking | Automated Unit Test | `tests/backend/test_chunking.py`, `test_tree_sitter.py` |
| **FR-02** | Hybrid Dense + Sparse Search | Automated Integration Test | `tests/backend/test_search.py`, `test_rrf.py` |
| **FR-03** | Dual Relational Storage | Automated Integration Test | `tests/backend/test_database.py`, `test_sqlite_wal.py` |
| **FR-04** | Pluggable Vector Backends | Automated Integration Test | `tests/backend/test_vector_store.py`, `test_vector_health.py` |
| **FR-05** | Universal Git Ingestion | Automated Integration Test | `tests/backend/test_git_manager.py`, `test_shallow_clone.py` |
| **FR-06** | Managed Local Storage | Automated Unit & Integration | `tests/backend/test_local_storage.py`, `test_storage_api.py` |
| **FR-07** | PDF Ingestion & Vision OCR | Automated Integration Test | `tests/backend/test_pdf_extractor.py`, `test_pdf_storage_api.py` |
| **FR-08** | FastMCP 2.0 & 14 Tools | Automated End-to-End Test | `tests/backend/test_mcp_server.py`, `test_mcp_tools.py` |
| **FR-09** | RFC 9728 OAuth 2.1 & RBAC | Automated Unit & Security | `tests/backend/test_auth.py`, `test_rbac.py`, `test_oauth_metadata.py`|
| **FR-10** | 3-Pane Codebase Navigator | Automated Component & E2E | `frontend/src/tests/Navigator.test.tsx`, `e2e/navigator.spec.ts` |
| **FR-11** | Dynamic Model Discovery | Automated Integration Test | `tests/backend/test_litellm_service.py`, `test_model_metadata.py` |
| **FR-12** | Diagnostic Ring Buffer | Automated Unit Test | `tests/backend/test_logger.py`, `test_logs_api.py` |
| **FR-13** | Unified Ingestion Catalog | Automated Integration Test | `tests/backend/test_catalog.py`, `frontend/src/tests/Catalog.test.tsx`|
| **FR-14** | Architecture ADR Management | Automated Integration Test | `tests/backend/test_adr.py` |
| **FR-15** | Multi-Theme Responsive UI | Automated E2E & Layout | `frontend/src/tests/Theme.test.tsx`, `e2e/layout-inspector.spec.ts` |
| **NFR-01** | Sub-500 LOC Maintainability | Automated Linter / CI | `oxlint`, `ruff`, repository file size audits |
| **NFR-04** | Path Traversal Protection | Automated Security Test | `tests/backend/test_local_storage.py::test_path_traversal` |
| **NFR-07** | Zero Horizontal Overflow | Automated E2E Layout Test | `e2e/layout-inspector.spec.ts` |

---

## Executing Automated Verification Suites

### 1. Running Backend Pytest Verification
Execute the full Python test suite:
```bash
pytest -v
```

To run with statement and branch coverage metrics:
```bash
pytest -v --cov=app --cov-report=term-missing
```

### 2. Running Frontend Vitest Verification
Execute React component tests:
```bash
npm --prefix frontend run test
```

### 3. Running Playwright Layout Inspector Audits
Execute viewport and layout overflow audits:
```bash
npm --prefix frontend run test:layout
```
