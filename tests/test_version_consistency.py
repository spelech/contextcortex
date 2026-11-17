"""Every place that shows the release version agrees with the release-please manifest."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _manifest_version() -> str:
    return json.loads((ROOT / ".release-please-manifest.json").read_text(encoding="utf-8"))["."]


def test_backend_mcp_and_frontend_versions_match_the_release_manifest():
    from app.mcp.mcp_server import MCP_SERVER_VERSION

    version = _manifest_version()
    main_py = (ROOT / "main.py").read_text(encoding="utf-8")
    assert re.search(r'FastAPI\(title="ContextCortex", version="([^"]+)"', main_py).group(1) == version
    assert MCP_SERVER_VERSION == version
    for package in ("package.json", "frontend/package.json"):
        assert json.loads((ROOT / package).read_text(encoding="utf-8"))["version"] == version, package


def test_ui_source_has_no_hard_coded_version():
    """The header badge reads __APP_VERSION__ (from frontend/package.json at build time), not a literal."""
    hard_coded = [
        f"{path.relative_to(ROOT).as_posix()}: {match.group(0)}"
        for path in (ROOT / "frontend" / "src").rglob("*.tsx")
        if "tests" not in path.parts
        for match in re.finditer(r">\s*v\d+\.\d+\.\d+\s*<", path.read_text(encoding="utf-8"))
    ]
    assert hard_coded == []
    assert "v{__APP_VERSION__}" in (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "__APP_VERSION__: JSON.stringify(version)" in (ROOT / "frontend" / "vite.config.js").read_text(encoding="utf-8")
