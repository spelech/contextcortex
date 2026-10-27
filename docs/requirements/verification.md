# Verification and Test Matrix

ContextCortex is verified by an automated test suite comprising **1,051 automated tests**:
- **698 Backend Tests** (Python Pytest suite with 88% code coverage baseline).
- **303 Frontend Tests** (React 19 / TypeScript Vitest unit and component suite).
- **50 End-to-End Tests** (Playwright automated browser suite and Layout Inspector audits).

---

## Requirements Verification Traceability Matrix

| Requirement ID | Requirement Title | Verification Method | Associated Test Modules |
| :--- | :--- | :--- | :--- |
| **FR-01** | AST Code Chunking | Automated Unit Test | `tests/backend/test_chunker.py`, `tests/backend/test_chunker_languages.py` |
| **FR-02** | Calibrated Hybrid Search & AST Enrichment | Automated Integration Test | `tests/backend/test_search.py`, `tests/backend/test_vector_store_qdrant.py`, `frontend/src/tests/SearchInspector.test.tsx` |
| **FR-03** | Dual Relational Storage | Automated Integration Test | `tests/backend/test_db_and_tools.py`, `tests/backend/test_postgres_schema.py` |
| **FR-04** | Pluggable Vector Backends | Automated Integration Test | `tests/backend/test_vector_store_manager.py`, `tests/backend/test_api_vector_store.py` |
| **FR-05** | Universal Git Ingestion & Shallow Retention | Automated Integration Test | `tests/backend/test_multi_git_providers.py`, `tests/backend/test_git_manager.py`, `frontend/src/tests/GitRepoManager.test.tsx` |
| **FR-06** | Managed Local Storage, Read & Summarize | Automated Unit & Integration | `tests/backend/test_local_storage_service.py`, `tests/backend/test_file_reader_and_summarizer.py` |
| **FR-07** | PDF Ingestion & Vision OCR | Automated Integration Test | `tests/test_pdf_extractor.py`, `tests/test_pdf_storage_api.py`, `frontend/src/tests/PdfPreviewModal.test.tsx` |
| **FR-08** | FastMCP 2.0, 16 Tools & JSON-RPC Ping | Automated End-to-End Test | `tests/backend/test_mcp_v2.py`, `tests/test_mcp_ping.py`, `tests/backend/test_tools.py` |
| **FR-09** | RFC 9728 OAuth 2.1 & RBAC | Automated Unit & Security | `tests/backend/test_auth_jwt_and_keys.py`, `tests/backend/test_auth_middleware_and_rbac.py` |
| **FR-10** | Hero Split Codebase Navigator & Omni-Search | Automated Component & E2E | `frontend/src/tests/CodeNavigator.test.tsx`, `NavigatorOmniSearch.test.tsx`, `NavigatorCodeViewer.test.tsx`, `e2e/navigator.spec.ts` |
| **FR-11** | AI Gateway & Dynamic Model Discovery | Automated Integration Test | `tests/backend/test_ai_gateway_settings.py`, `tests/test_litellm_service.py`, `tests/test_llm_client.py`, `tests/test_model_discovery_api.py`, `frontend/src/tests/AIGatewaySettings.test.tsx` |
| **FR-12** | Diagnostic Ring Buffer | Automated Unit Test | `tests/backend/test_diagnostic_logger.py`, `frontend/src/tests/DiagnosticsViewer.test.tsx` |
| **FR-13** | Unified Ingestion Catalog | Automated Integration Test | `tests/backend/test_mcp_storage_tools.py`, `frontend/src/tests/IngestionCatalogViewer.test.tsx` |
| **FR-14** | Architecture ADR Management | Automated Integration Test | `tests/backend/test_architecture_adr.py` |
| **FR-15** | Multi-Theme Responsive UI | Automated E2E & Layout | `frontend/src/tests/App.test.tsx`, `frontend/e2e/dashboard.spec.ts` |
| **FR-16** | Enterprise Private-CA Trust & Mirror Builds | Automated Integration Test | `tests/test_docker_entrypoint.py`, `tests/test_docker_orchestration.py`, `tests/test_llm_client.py` |
| **NFR-01** | Sub-500 LOC Maintainability | Automated Linter / CI | Repository file size audits, `pytest`, `tsc` |
| **NFR-04** | Path Traversal Protection | Automated Security Test | `tests/backend/test_local_storage_service.py`, `tests/backend/test_file_reader_and_summarizer.py` |
| **NFR-07** | Zero Horizontal Overflow | Automated E2E Layout Test | `frontend/e2e/navigator.spec.ts`, `frontend/e2e/dashboard.spec.ts` |

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

### 3. Running Playwright End-to-End & Layout Audits
Execute browser E2E and layout overflow audits:
```bash
npm --prefix frontend run test:layout
```
