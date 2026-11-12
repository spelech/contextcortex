import json
import logging
import sys
from typing import Optional, Annotated
from pydantic import Field

from app.services.auth import enforce_tool_permission, Role, ForbiddenError
from app.services.diagnostics import diagnose_issue

logger = logging.getLogger("contextcortex.mcp.diagnostics")


def _get_tools_attr(name, default):
    t_mod = sys.modules.get("app.mcp.tools")
    return getattr(t_mod, name, default) if t_mod else default


async def handle_diagnose_issue(
    issue_text: Annotated[str, Field(description="Raw stack trace, exception log, HTTP failure payload, or bug symptom report across Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, and C/C++.")],
    repo: Annotated[Optional[str], Field(description="Optional repository name to scope stack frame, route, and semantic candidate resolution.")] = None,
    context_lines: Annotated[int, Field(description="Surrounding source lines returned per resolved stack frame, clamped to 1..15 (default 5).")] = 5,
    limit: Annotated[int, Field(description="Maximum semantic code candidates returned alongside resolved stack frames, clamped to 1..20 (default 5).")] = 5,
) -> str:
    """Forensic triage engine resolving stack frames, error string literals, HTTP routes, and semantic code candidates in one call."""
    try:
        enforce_tool_permission(Role.VIEWER)

        text = (issue_text or "").strip()
        if not text:
            return json.dumps({
                "resolved_frames": [],
                "matched_routes": [],
                "matched_symbols": [],
                "semantic_candidates": [],
            })

        safe_ctx = max(1, min(int(context_lines if context_lines is not None else 5), 15))
        safe_limit = max(1, min(int(limit if limit is not None else 5), 20))

        diag_fn = _get_tools_attr("diagnose_issue", diagnose_issue)
        result = diag_fn(
            issue_text=text,
            repo=repo,
            context_lines=safe_ctx,
            limit=safe_limit,
        )

        return json.dumps(result, indent=2, default=str)

    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_diagnose_issue: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        logger.error(f"Error executing diagnose_issue triage: {e}", exc_info=True)
        return json.dumps({"error": f"Error executing diagnostics: {str(e)}"})
