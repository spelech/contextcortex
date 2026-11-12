#!/usr/bin/env python3
"""
Automated Software Requirements Specification (SRS) Generator & Validator.

This script parses test cases, docstrings, and structures from:
1. Python backend tests (tests/backend/test_*.py, tests/test_*.py, test_*.py) via Python AST.
2. Frontend Vitest unit/component tests (frontend/src/tests/*.test.tsx).
3. Playwright End-to-End user journeys (frontend/e2e/*.spec.ts).

It dynamically generates REQUIREMENTS.md and docs/REQUIREMENTS.md ensuring
the requirements documentation is always synchronized with the codebase.
"""

import ast
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.requirements_sections import DOCS_POINTER_CONTENT, build_srs_static_lines  # noqa: E402


def parse_python_tests() -> Dict[str, List[Tuple[str, str]]]:
    """Parse test function names and docstrings from all backend test locations."""
    results = {}
    py_files = []

    backend_tests_dir = PROJECT_ROOT / "tests" / "backend"
    if backend_tests_dir.exists():
        py_files.extend(sorted(backend_tests_dir.glob("test_*.py")))

    tests_root_dir = PROJECT_ROOT / "tests"
    if tests_root_dir.exists():
        py_files.extend(sorted(tests_root_dir.glob("test_*.py")))

    for py_file in py_files:
        if py_file.name == "test_requirements_sync.py":
            continue
        rel_path = str(py_file.relative_to(PROJECT_ROOT))
        tests = []
        try:
            with open(py_file, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(py_file))

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                    docstring = ast.get_docstring(node) or ""
                    tests.append((node.name, docstring.strip()))
                elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test_"):
                            docstring = ast.get_docstring(item) or ""
                            tests.append((f"{node.name}::{item.name}", docstring.strip()))
        except Exception as e:
            print(f"Warning parsing {py_file}: {e}")

        results[rel_path] = tests

    return results


def parse_frontend_tests() -> Dict[str, List[str]]:
    """Parse describe and it/test blocks from frontend/src/tests/."""
    fe_tests_dir = PROJECT_ROOT / "frontend" / "src" / "tests"
    results = {}

    test_pattern = re.compile(r"""(?:it|test)\s*\(\s*['"`](.*?)['"`]""")

    for tsx_file in sorted(fe_tests_dir.glob("*.test.tsx")):
        rel_path = tsx_file.name
        tests = []
        try:
            with open(tsx_file, "r", encoding="utf-8") as f:
                content = f.read()
                matches = test_pattern.findall(content)
                tests = [m.strip() for m in matches if m.strip()]
        except Exception as e:
            print(f"Warning parsing {tsx_file}: {e}")

        results[rel_path] = tests

    return results


def parse_e2e_tests() -> List[str]:
    """Parse E2E journey specifications from frontend/e2e/."""
    e2e_dir = PROJECT_ROOT / "frontend" / "e2e"
    tests = []
    if e2e_dir.exists():
        test_pattern = re.compile(r"""test\s*\(\s*['"`](.*?)['"`]""")
        for e2e_file in sorted(e2e_dir.glob("*.spec.ts")):
            try:
                with open(e2e_file, "r", encoding="utf-8") as f:
                    matches = test_pattern.findall(f.read())
                    tests.extend([m.strip() for m in matches if m.strip()])
            except Exception as e:
                print(f"Warning parsing E2E {e2e_file}: {e}")
    return tests


def generate_markdown() -> str:
    py_tests = parse_python_tests()
    fe_tests = parse_frontend_tests()
    e2e_tests = parse_e2e_tests()

    total_py_tests = sum(len(t) for t in py_tests.values())
    total_fe_tests = sum(len(t) for t in fe_tests.values())
    total_e2e_tests = len(e2e_tests)
    total_all_tests = total_py_tests + total_fe_tests + total_e2e_tests

    main_py = PROJECT_ROOT / "main.py"
    ver_match = re.search(r'version=["\']([^"\']+)["\']', main_py.read_text(encoding="utf-8")) if main_py.exists() else None
    app_version = ver_match.group(1).strip() if ver_match else "2.21.4"

    lines = build_srs_static_lines(
        app_version=app_version,
        total_all_tests=total_all_tests,
        total_py_tests=total_py_tests,
        total_fe_tests=total_fe_tests,
        total_e2e_tests=total_e2e_tests,
    )

    for filename, tests in py_tests.items():
        lines.append(f"#### `{filename}` ({len(tests)} tests)")
        for name, doc in tests:
            doc_str = f" - _{doc}_" if doc else ""
            lines.append(f"- `{name}`{doc_str}")
        lines.append("")

    lines.append("### 6.2 Frontend Vitest Tests (`frontend/src/tests/`)")
    lines.append("")
    for filename, tests in fe_tests.items():
        lines.append(f"#### `{filename}` ({len(tests)} tests)")
        for name in tests:
            lines.append(f"- {name}")
        lines.append("")

    lines.append("### 6.3 Playwright End-to-End User Journeys (`frontend/e2e/`)")
    lines.append("")
    for test in e2e_tests:
        lines.append(f"- {test}")
    lines.append("")

    return "\n".join(lines)


def main():
    content = generate_markdown()
    root_req_path = PROJECT_ROOT / "REQUIREMENTS.md"
    with open(root_req_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Generated {root_req_path}")

    docs_req_path = PROJECT_ROOT / "docs" / "REQUIREMENTS.md"
    docs_req_path.parent.mkdir(parents=True, exist_ok=True)
    with open(docs_req_path, "w", encoding="utf-8") as f:
        f.write(DOCS_POINTER_CONTENT)
    print(f"Generated {docs_req_path}")


if __name__ == "__main__":
    main()
