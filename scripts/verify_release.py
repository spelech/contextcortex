#!/usr/bin/env python3
"""
Release and Version Verification Engine for ContextCortex.
Validates version consistency across manifests, markdown relative links, and test integrity.
Conforms to Steven T. Pelech's Engineering Archetype standards.
"""

import os
import re
import sys
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def check_markdown_links(root_dir: Path) -> bool:
    print("🔍 Checking markdown relative links...")
    has_errors = False
    excluded_parts = {
        "node_modules",
        ".node_modules_root",
        "venv",
        ".venv",
        ".vitepress",
        "dist",
        "htmlcov",
        ".pytest_cache",
        "coverage",
        ".git"
    }

    checked_count = 0
    for md_file in root_dir.glob("**/*.md"):
        if any(part in excluded_parts for part in md_file.parts):
            continue

        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            print(f"⚠️  Could not read {md_file.relative_to(root_dir)}: {e}")
            continue

        # Match markdown links [text](target)
        links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', content)
        for text, link in links:
            link = link.strip()
            # Ignore absolute URLs, mailto, in-page anchors, and file:// URIs
            if (
                link.startswith("http://")
                or link.startswith("https://")
                or link.startswith("#")
                or link.startswith("mailto:")
                or link.startswith("file://")
            ):
                continue

            # Strip query params and in-page anchor
            target_path = link.split("?")[0].split("#")[0]
            if not target_path:
                continue

            # For VitePress absolute doc paths like /guide/user-guide or /assets/...
            if target_path.startswith("/"):
                # Check under docs/ or docs/public/
                rel_candidate = target_path.lstrip("/")
                candidates = [
                    root_dir / "docs" / f"{rel_candidate}.md",
                    root_dir / "docs" / rel_candidate / "index.md",
                    root_dir / "docs" / "public" / rel_candidate,
                    root_dir / "docs" / rel_candidate,
                ]
                if any(c.exists() for c in candidates):
                    checked_count += 1
                    continue
                print(f"❌ Broken site link in {md_file.relative_to(root_dir)}: [{text}]({link})")
                has_errors = True
                continue

            # Normal relative filesystem path
            resolved = (md_file.parent / target_path).resolve()
            # If path ends without extension, check if target.md or target/index.md exists (VitePress routing)
            if not resolved.exists():
                alt_md = md_file.parent / f"{target_path}.md"
                alt_idx = md_file.parent / target_path / "index.md"
                if alt_md.exists() or alt_idx.exists():
                    checked_count += 1
                    continue

                print(f"❌ Broken relative link in {md_file.relative_to(root_dir)}: [{text}]({link})")
                has_errors = True
            else:
                checked_count += 1

    if not has_errors:
        print(f"✅ Verified {checked_count} markdown relative links successfully.")
    return not has_errors


def check_version_sync(root_dir: Path) -> bool:
    print("🔍 Checking version consistency across project manifests...")
    versions: Dict[str, str] = {}

    # 1. main.py
    main_py = root_dir / "main.py"
    if main_py.exists():
        match = re.search(r'version=["\']([^"\']+)["\']', main_py.read_text(encoding="utf-8"))
        if match:
            versions["main.py"] = match.group(1).strip()

    # 2. root package.json
    root_pkg = root_dir / "package.json"
    if root_pkg.exists():
        match = re.search(r'"version":\s*"([^"]+)"', root_pkg.read_text(encoding="utf-8"))
        if match:
            versions["package.json"] = match.group(1).strip()

    # 3. frontend/package.json
    fe_pkg = root_dir / "frontend" / "package.json"
    if fe_pkg.exists():
        match = re.search(r'"version":\s*"([^"]+)"', fe_pkg.read_text(encoding="utf-8"))
        if match:
            versions["frontend/package.json"] = match.group(1).strip()

    # 4. README.md
    readme = root_dir / "README.md"
    if readme.exists():
        match = re.search(r'#\s+ContextCortex\s+\(v([^)]+)\)', readme.read_text(encoding="utf-8"))
        if match:
            versions["README.md"] = match.group(1).strip()

    # 5. ARCHITECTURE.md
    arch = root_dir / "ARCHITECTURE.md"
    if arch.exists():
        match = re.search(r'#\s+Architecture:\s+ContextCortex\s+\(v([^)]+)\)', arch.read_text(encoding="utf-8"))
        if match:
            versions["ARCHITECTURE.md"] = match.group(1).strip()

    # 6. REQUIREMENTS.md
    req = root_dir / "REQUIREMENTS.md"
    if req.exists():
        match = re.search(r'#\s+Software Requirements Specification:\s+ContextCortex\s+\(v([^)]+)\)', req.read_text(encoding="utf-8"))
        if match:
            versions["REQUIREMENTS.md"] = match.group(1).strip()

    # 7. DEVELOPER_DOCS.md
    devdocs = root_dir / "DEVELOPER_DOCS.md"
    if devdocs.exists():
        match = re.search(r'#\s+Developer Documentation:\s+ContextCortex\s+\(v([^)]+)\)', devdocs.read_text(encoding="utf-8"))
        if match:
            versions["DEVELOPER_DOCS.md"] = match.group(1).strip()

    for manifest, ver in versions.items():
        print(f"   • {manifest:26}: {ver}")

    unique_versions = set(versions.values())
    if len(unique_versions) > 1:
        print(f"❌ Version mismatch detected across manifests: {unique_versions}")
        return False

    if not unique_versions:
        print("❌ No version declarations found.")
        return False

    version = next(iter(unique_versions))
    print(f"✅ Version consistency check passed (v{version} across {len(versions)} manifests).")
    return True


def main():
    parser = argparse.ArgumentParser(description="Release Verification Engine")
    parser.add_argument("--skip-tests", action="store_true", help="Skip test suite execution")
    parser.add_argument("--ci", action="store_true", help="Run in CI mode")
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parent.parent
    links_ok = check_markdown_links(root_dir)
    versions_ok = check_version_sync(root_dir)

    success = links_ok and versions_ok
    if not success:
        sys.exit(1)
    print("🎉 All Stage 1 Release & Link Integrity checks passed successfully.")
    sys.exit(0)


if __name__ == "__main__":
    main()
