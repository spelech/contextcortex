"""Automated AgenticEngineeringToolbelt guardrails for repo structure, <= 500 LOC caps, and semantic naming."""

import ast
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAX_SOURCE_LOC = 500

# Frozen pre-existing legacy module/component filenames retained strictly for import/API compatibility.
# Zero new *Manager, *Helper, *Util, *Utils, or *Data modules/classes may be added anywhere in the repo.
LEGACY_FILENAME_ALLOWLIST = {
    "app/services/git_manager.py",
    "app/services/memory_utils.py",
    "app/services/topology/helpers.py",
    "app/services/vector_store/manager.py",
    "frontend/src/GitRepoManager.tsx",
    "frontend/src/LocalPathManager.tsx",
    "frontend/src/LocalStorageManager.tsx",
    "frontend/src/tests/GitRepoManager.test.tsx",
    "frontend/src/tests/LocalPathManager.test.tsx",
    "frontend/src/tests/LocalStorageManager.test.tsx",
    "tests/backend/test_git_manager.py",
    "tests/backend/test_vector_store_manager.py",
}

LEGACY_SYMBOL_ALLOWLIST = {
    "GitManagerService",
    "PortablePostgresManager",
    "VectorStoreManager",
    "GitRepoManager",
    "LocalPathManager",
    "LocalStorageManager",
    "TestGitManager",
    "TestVectorStoreManager",
}

BANNED_NAMING_PATTERN = re.compile(r"(?:manager|managers|helper|helpers|util|utils|data)$", re.IGNORECASE)


def test_repository_root_structure_hygiene():
    """Verify repository root contains required living docs, no stray test_*.py files, and synced www/ overlay."""
    stray_root_tests = [
        p.name for p in sorted(PROJECT_ROOT.iterdir())
        if p.is_file() and (p.name.startswith("test_") or p.name.endswith("_test.py"))
    ]
    assert not stray_root_tests, f"Stray test files at repository root (move to tests/): {stray_root_tests}"

    required_docs = ["README.md", "ARCHITECTURE.md", "REQUIREMENTS.md", "CHANGELOG.md", "DEVELOPER_DOCS.md"]
    missing_docs = [doc for doc in required_docs if not (PROJECT_ROOT / doc).is_file()]
    assert not missing_docs, f"Missing required root living documentation files: {missing_docs}"

    dist_index = PROJECT_ROOT / "frontend" / "dist" / "index.html"
    www_index = PROJECT_ROOT / "www" / "index.html"
    if dist_index.is_file() and www_index.is_file():
        assert dist_index.read_text(encoding="utf-8") == www_index.read_text(encoding="utf-8"), (
            "www/index.html is out of sync with frontend/dist/index.html (required by Dockerfile.overlay)"
        )


def test_all_python_files_and_classes_under_500_loc():
    """Verify every Python file and class across main.py, app/, scripts/, and tests/ stays <= 500 LOC."""
    py_files = [PROJECT_ROOT / "main.py", PROJECT_ROOT / "conftest.py"]
    for folder in ("app", "scripts", "tests"):
        py_files.extend(sorted((PROJECT_ROOT / folder).rglob("*.py")))

    oversized_files = []
    oversized_classes = []

    for py_file in py_files:
        if "__pycache__" in py_file.parts or not py_file.is_file():
            continue
        source = py_file.read_text(encoding="utf-8")
        line_count = len(source.splitlines())
        rel_path = py_file.relative_to(PROJECT_ROOT).as_posix()
        if line_count > MAX_SOURCE_LOC:
            oversized_files.append(f"{rel_path} ({line_count} LOC)")

        tree = ast.parse(source, filename=rel_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.end_lineno is not None:
                span = node.end_lineno - node.lineno + 1
                if span > MAX_SOURCE_LOC:
                    oversized_classes.append(f"{rel_path}:{node.name} ({span} LOC)")

    assert not oversized_files, f"Python files exceed {MAX_SOURCE_LOC} LOC: {oversized_files}"
    assert not oversized_classes, f"Python classes exceed {MAX_SOURCE_LOC} LOC: {oversized_classes}"


def test_all_frontend_and_script_files_under_500_loc():
    """Verify every TypeScript, TSX, CSS, shell, and PowerShell file in source/tests/scripts stays <= 500 LOC."""
    oversized = []
    fe_dirs = [
        PROJECT_ROOT / "frontend" / "src",
        PROJECT_ROOT / "frontend" / "scripts",
        PROJECT_ROOT / "frontend" / "e2e",
        PROJECT_ROOT / "scripts",
    ]
    for directory in fe_dirs:
        if not directory.exists():
            continue
        for fp in sorted(directory.rglob("*")):
            if not fp.is_file() or fp.name.endswith(".d.ts"):
                continue
            if fp.suffix not in {".ts", ".tsx", ".css", ".sh", ".ps1"}:
                continue
            line_count = len(fp.read_text(encoding="utf-8").splitlines())
            rel_path = fp.relative_to(PROJECT_ROOT).as_posix()
            if line_count > MAX_SOURCE_LOC:
                oversized.append(f"{rel_path} ({line_count} LOC)")

    for root_script in sorted(PROJECT_ROOT.glob("*.sh")) + sorted(PROJECT_ROOT.glob("*.ps1")):
        line_count = len(root_script.read_text(encoding="utf-8").splitlines())
        if line_count > MAX_SOURCE_LOC:
            oversized.append(f"{root_script.name} ({line_count} LOC)")

    assert not oversized, f"Frontend/script/CSS files exceed {MAX_SOURCE_LOC} LOC: {oversized}"


def test_semantic_naming_bans_junk_drawer_modules_and_classes():
    """Verify case-insensitively that no new *Manager, *Helper, *Util, *Utils, or *Data modules/classes exist."""
    bad_files = []
    bad_classes = []

    scan_roots = [
        PROJECT_ROOT / "app",
        PROJECT_ROOT / "scripts",
        PROJECT_ROOT / "tests",
        PROJECT_ROOT / "frontend" / "src",
        PROJECT_ROOT / "frontend" / "scripts",
        PROJECT_ROOT / "frontend" / "e2e",
    ]
    for root in scan_roots:
        if not root.exists():
            continue
        for fp in sorted(root.rglob("*")):
            if not fp.is_file() or "__pycache__" in fp.parts:
                continue
            if fp.suffix not in {".py", ".ts", ".tsx"} or fp.name.endswith(".d.ts"):
                continue
            rel_path = fp.relative_to(PROJECT_ROOT).as_posix()
            stem = re.sub(r"\.(?:test|spec)$", "", fp.stem)
            stem_clean = re.sub(r"[_-]", "", stem)
            if BANNED_NAMING_PATTERN.search(stem) or BANNED_NAMING_PATTERN.search(stem_clean):
                if rel_path not in LEGACY_FILENAME_ALLOWLIST:
                    bad_files.append(rel_path)

            if fp.suffix == ".py":
                tree = ast.parse(fp.read_text(encoding="utf-8"), filename=rel_path)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef) and BANNED_NAMING_PATTERN.search(node.name):
                        if node.name not in LEGACY_SYMBOL_ALLOWLIST:
                            bad_classes.append(f"{rel_path}:{node.name}")

    assert not bad_files, f"Banned junk-drawer module filenames found: {bad_files}"
    assert not bad_classes, f"Banned junk-drawer Python class names found: {bad_classes}"
