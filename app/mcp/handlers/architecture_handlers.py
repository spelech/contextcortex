import json
import logging
import sys
from typing import List, Dict, Any, Optional, Annotated
from pydantic import Field

from app.services.database import get_db_connection, get_adr, list_adrs, create_adr, update_adr, supersede_adr

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


def _matches_adr_query(record: Dict[str, Any], needle: str) -> bool:
    if not needle:
        return True
    haystack = " ".join(
        str(record.get(field) or "")
        for field in ("id", "repo", "title", "status", "context", "decision", "consequences")
    ).lower()
    return needle in haystack


async def handle_manage_adr(
    action: Annotated[str, Field(description="ADR lifecycle action: 'list', 'search', 'get', 'create', 'update', or 'supersede'.")],
    repo: Annotated[Optional[str], Field(description="Repository identifier. Required for 'list', 'get', 'create', 'update', and 'supersede'; optional filter for 'search'.")] = None,
    id: Annotated[Optional[str], Field(description="ADR identifier (e.g. 'ADR-001'). Optional on 'create' (auto-generated if omitted); required on 'get', 'update', and 'supersede'.")] = None,
    title: Annotated[Optional[str], Field(description="Concise ADR decision title (required for 'create').")] = None,
    status: Annotated[Optional[str], Field(description="ADR status filter or value: 'PROPOSED', 'ACCEPTED', 'REJECTED', 'SUPERSEDED', or 'DEPRECATED'.")] = None,
    context: Annotated[Optional[str], Field(description="Architectural context and problem statement.")] = None,
    decision: Annotated[Optional[str], Field(description="Chosen architectural decision and design rationale.")] = None,
    consequences: Annotated[Optional[str], Field(description="Trade-offs, operational impact, and follow-up consequences.")] = None,
    superseded_by: Annotated[Optional[str], Field(description="Newer ADR ID replacing an older record (required on 'supersede').")] = None,
    query: Annotated[Optional[str], Field(description="Keyword filter across ADR id, title, context, decision, and consequences for 'search' or 'list'.")] = None,
    limit: Annotated[int, Field(description="Maximum ADRs returned per page on 'list' or 'search', clamped to 1..100 (default 25).")] = 25,
    offset: Annotated[int, Field(description="0-based ADR offset for 'list' or 'search' pagination (default 0). Advance via next_offset when has_more is True.")] = 0,
) -> str:
    """Manage Architecture Decision Records (ADRs): list, search, get, create, update, or supersede records with bounded pagination."""
    action_clean = action.lower().strip() if action else ""
    repo_clean = repo.strip() if repo and repo.strip() else None

    if action_clean != "search" and not repo_clean:
        return json.dumps({"error": "repo parameter is required."})

    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        required_role = Role.EDITOR if action_clean in ("create", "update", "supersede") else Role.VIEWER
        enforce_tool_permission(required_role)

        safe_limit = max(1, min(int(limit if limit is not None else 25), 100))
        safe_offset = max(0, int(offset if offset is not None else 0))

        if action_clean in ("list", "search"):
            if repo_clean:
                records = _get_tools_attr("list_adrs", list_adrs)(repo=repo_clean, status=status) or []
            else:
                with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
                    sql = "SELECT * FROM architecture_decision_records WHERE 1=1"
                    params: List[Any] = []
                    if status and status.strip():
                        sql += " AND status = ?"
                        params.append(status.upper().strip())
                    sql += " ORDER BY repo ASC, id ASC"
                    rows = conn.execute(sql, params).fetchall()
                    records = [dict(r) for r in rows]

            needle = (query or "").strip().lower()
            filtered = [r for r in records if _matches_adr_query(r, needle)]
            all_adrs = [
                {
                    "id": r.get("id"),
                    "repo": r.get("repo", repo_clean),
                    "title": r.get("title"),
                    "status": r.get("status"),
                    "superseded_by": r.get("superseded_by"),
                }
                for r in filtered
            ]

            total = len(all_adrs)
            paged_adrs = all_adrs[safe_offset : safe_offset + safe_limit]
            has_more = (safe_offset + safe_limit) < total
            next_offset = (safe_offset + safe_limit) if has_more else None

            resp: Dict[str, Any] = {
                "action": action_clean,
                "repo": repo_clean,
                "total": total,
                "offset": safe_offset,
                "limit": safe_limit,
                "has_more": has_more,
                "next_offset": next_offset,
                "adrs": paged_adrs,
            }
            if query is not None or action_clean == "search":
                resp["query"] = (query or "").strip() or None
            return json.dumps(resp)

        if action_clean == "get":
            if not id:
                return json.dumps({"error": "'id' parameter is required for action 'get'."})
            r = _get_tools_attr("get_adr", get_adr)(adr_id=id, repo=repo_clean)
            if not r:
                return json.dumps({"error": f"ADR '{id}' not found in repo '{repo_clean}'.", "found": False})
            return json.dumps({
                "action": "get",
                "found": True,
                "adr": {
                    "id": r.get("id"),
                    "repo": r.get("repo", repo_clean),
                    "title": r.get("title"),
                    "status": r.get("status"),
                    "superseded_by": r.get("superseded_by"),
                    "created_at": r.get("created_at"),
                    "updated_at": r.get("updated_at"),
                    "context": r.get("context"),
                    "decision": r.get("decision"),
                    "consequences": r.get("consequences"),
                },
            })

        if action_clean == "create":
            if not title:
                return json.dumps({"error": "'title' parameter is required for action 'create'."})
            res = _get_tools_attr("create_adr", create_adr)(
                repo=repo_clean,
                title=title,
                status=status or "PROPOSED",
                context=context or "Context pending.",
                decision=decision or "Decision pending.",
                consequences=consequences,
                superseded_by=superseded_by,
                adr_id=id,
            )
            return json.dumps({
                "action": "create",
                "status": "success",
                "repo": repo_clean,
                "id": res.get("id"),
                "adr_status": res.get("status"),
                "adr": res,
            })

        if action_clean == "update":
            if not id:
                return json.dumps({"error": "'id' parameter is required for action 'update'."})
            res = _get_tools_attr("update_adr", update_adr)(
                adr_id=id,
                repo=repo_clean,
                title=title,
                status=status,
                context=context,
                decision=decision,
                consequences=consequences,
                superseded_by=superseded_by,
            )
            return json.dumps({
                "action": "update",
                "status": "success",
                "repo": repo_clean,
                "id": res.get("id"),
                "adr": res,
            })

        if action_clean == "supersede":
            if not id:
                return json.dumps({"error": "'id' parameter is required for action 'supersede' (ID of old ADR to be superseded)."})
            if not superseded_by:
                return json.dumps({"error": "'superseded_by' parameter is required for action 'supersede' (ID of newer ADR)."})
            res = _get_tools_attr("supersede_adr", supersede_adr)(old_id=id, new_id=superseded_by, repo=repo_clean)
            return json.dumps({
                "action": "supersede",
                "status": "success",
                "repo": repo_clean,
                "id": id,
                "superseded_by": superseded_by,
                "adr": res,
            })

        return json.dumps({"error": f"Invalid action '{action}'. Supported actions: list, search, get, create, update, supersede."})

    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_manage_adr ({action_clean}): {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        logger.error(f"manage_adr error ({action_clean}): {e}")
        return json.dumps({"error": f"Error executing manage_adr action '{action}': {str(e)}"})
