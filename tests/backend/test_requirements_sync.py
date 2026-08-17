"""Test to ensure REQUIREMENTS.md is continuously synchronized with the test suite."""

import sys
from pathlib import Path
from scripts.generate_requirements import parse_python_tests, parse_frontend_tests, parse_e2e_tests, generate_markdown

def test_requirements_parsed_from_all_tests():
    """Verify that the requirements generator successfully parses all backend, frontend, and E2E tests."""
    py_tests = parse_python_tests()
    fe_tests = parse_frontend_tests()
    e2e_tests = parse_e2e_tests()

    assert len(py_tests) >= 13, "Should parse at least 13 backend test modules"
    assert sum(len(t) for t in py_tests.values()) >= 120, "Should parse at least 120 backend test cases"
    assert len(fe_tests) >= 7, "Should parse at least 7 frontend test modules"
    assert sum(len(t) for t in fe_tests.values()) >= 40, "Should parse at least 40 frontend test cases"
    assert len(e2e_tests) >= 13, "Should parse all 13 Playwright E2E journey specs"

def test_requirements_file_up_to_date():
    """Verify that REQUIREMENTS.md matches generated specification content and docs/ is symlinked."""
    root_dir = Path(__file__).resolve().parent.parent.parent
    req_path = root_dir / "REQUIREMENTS.md"
    docs_req_path = root_dir / "docs" / "REQUIREMENTS.md"

    assert req_path.exists(), "REQUIREMENTS.md must exist in repository root"
    assert docs_req_path.exists(), "docs/REQUIREMENTS.md must exist"
    assert docs_req_path.resolve() == req_path.resolve(), "docs/REQUIREMENTS.md must resolve to root REQUIREMENTS.md (single source of truth)"

    expected_content = generate_markdown()
    actual_content = req_path.read_text(encoding="utf-8")

    # Verify key sections exist and match
    assert "## 1. System Vision & Architecture Scope" in actual_content
    assert "## 2. Mermaid Data Models & Entity Relationship Diagrams (ERD)" in actual_content
    assert "## 5. Requirement-to-Test Traceability Matrix" in actual_content
    assert "## 6. Parsed Test Suite Inventory" in actual_content
    assert actual_content == expected_content, "REQUIREMENTS.md is out of sync. Run python3 scripts/generate_requirements.py"
