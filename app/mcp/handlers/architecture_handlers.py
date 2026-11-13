import json
import logging
import sys
from typing import Optional, Annotated
from pydantic import Field

logger = logging.getLogger("contextcortex")


def _get_tools_attr(name, default):
    t_mod = sys.modules.get("app.mcp.tools")
    return getattr(t_mod, name, default) if t_mod else default


async def handle_get_architecture(
    repo: Annotated[Optional[str], Field(description="Optional repository identifier. Omit to synthesize a high-level multi-repository catalog architecture overview across Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, and C/C++ sources.")] = None,
) -> str:
    """Synthesize language distributions, package manifests, entry points, core modules, hub symbols, route counts, and active ADRs."""
    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)
        from app.services.architecture import synthesize_architecture
        res = synthesize_architecture(repo=repo)
        if isinstance(res, dict):
            return json.dumps(res)
        if isinstance(res, str) and (res.strip().startswith("{") or res.strip().startswith("[")):
            return res
        return json.dumps({"repo": repo, "overview": res})
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_get_architecture: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        logger.error(f"get_architecture error: {e}")
        return json.dumps({"error": f"Error synthesizing architecture overview: {str(e)}"})
