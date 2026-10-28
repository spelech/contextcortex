"""Opt-in checks against the configured approved package index, never public PyPI."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = [
    line.strip()
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.lstrip().startswith("#")
]
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_APPROVED_MIRROR_TESTS") != "1",
    reason="Requires explicit opt-in and pip configured for the approved mirror only",
)


def resolve_direct(requirement, tmp_path, *, constrained=False):
    report_path = tmp_path / "report.json"
    command = [
        sys.executable, "-m", "pip", "install",
        "--disable-pip-version-check", "--no-cache-dir", "--dry-run",
        "--ignore-installed", "--no-deps", "--only-binary=:all:",
        "--retries", "0", "--timeout", "15",
        "--report", str(report_path), requirement,
    ]
    if constrained:
        command.extend(["--constraint", str(ROOT / "python-constraints.txt")])
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=120
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"Approved-mirror lookup timed out for {requirement}", pytrace=False)
    if result.returncode:
        # pip diagnostics and artifact URLs can contain registry credentials.
        pytest.fail(
            f"Approved-mirror resolution failed for {requirement} "
            f"(exit {result.returncode}); private pip output withheld",
            pytrace=False,
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert len(report["install"]) == 1
    return report["install"][0]["metadata"]


def test_checked_in_mcp_pin_resolves_from_approved_mirror(tmp_path):
    """Catch an unavailable exact MCP pin even when the declared range is satisfiable."""
    metadata = resolve_direct("mcp[cli]>=1.20.0,<2.0.0", tmp_path, constrained=True)
    assert metadata["name"].lower() == "mcp"


@pytest.mark.parametrize("requirement", REQUIREMENTS)
def test_direct_requirement_has_compatible_approved_wheel(requirement, tmp_path):
    """Distinguish unavailable project artifacts from overly restrictive candidate pins."""
    resolve_direct(requirement, tmp_path)
