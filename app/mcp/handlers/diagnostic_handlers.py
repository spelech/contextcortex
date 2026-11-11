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
    issue_text: Annotated[str, Field(description="Raw stack trace, error log, user symptom report, or combination to triage.")],
    repo: Annotated[Optional[str], Field(description="Optional repository identifier to scope diagnostics and resolution.")] = None,
    context_lines: Annotated[int, Field(description="Number of surrounding code lines for stack frames (clamped 1..15, default 5).")] = 5,
    limit: Annotated[int, Field(description="Maximum number of semantic code candidate blocks to retrieve (clamped 1..20, default 5).")] = 5
) -> str:
    """Accepts any combination of stack traces, error logs, and user bug descriptions, returning a unified compact JSON forensic payload."""
    try:
        enforce_tool_permission(Role.VIEWER)

        text = (issue_text or "").strip()
        if not text:
            return json.dumps({
                "resolved_frames": [],
                "matched_routes": [],
                "matched_symbols": [],
                "semantic_candidates": []
            })

        diag_fn = _get_tools_attr("diagnose_issue", diagnose_issue)
        result = diag_fn(
            issue_text=text,
            repo=repo,
            context_lines=context_lines,
            limit=limit
        )

        return json.dumps(result, indent=2)

    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_diagnose_issue: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}"})
    except Exception as e:
        logger.error(f"Error executing diagnose_issue triage: {e}", exc_info=True)
        return json.dumps({"error": f"Error executing diagnostics: {str(e)}"})
