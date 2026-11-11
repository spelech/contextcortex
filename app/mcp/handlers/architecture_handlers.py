import json
import logging
from typing import List, Dict, Any, Optional, Annotated
from pydantic import Field

from app.services.database import get_db_connection, extract_host_from_url, get_adr, list_adrs, create_adr, update_adr, supersede_adr, upsert_adr
from app.services.search import execute_hybrid_search, trace_symbol_path
from app.services.indexing import get_dynamic_catalog_description, sync_single_git_repo, run_full_indexing
from app.services.vector_store import get_vector_store_config
from app.services.git_manager import format_git_permalink
from app.services.chunking import match_route_and_call, normalize_path_pattern
from app.models.schemas import SearchRequest, FindSymbolRequest, GetFileOutlineRequest, SyncRequest

logger = logging.getLogger("contextcortex")
import sys

def _get_tools_attr(name, default):
    t_mod = sys.modules.get("app.mcp.tools")
    return getattr(t_mod, name, default) if t_mod else default


async def handle_get_architecture(
    repo: Annotated[Optional[str], Field(description="Specific repository name. If omitted, returns an overview of all registered repositories.")] = None
) -> str:
    """Synthesizes language distributions, key entry points, primary framework modules, route counts, and active ADRs into a concise summary."""
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


async def handle_manage_adr(
    action: Annotated[str, Field(description="Action to perform: 'list', 'get', 'create', 'update', 'supersede'.")],
    repo: Annotated[str, Field(description="Repository identifier.")],
    id: Annotated[Optional[str], Field(description="ADR ID (e.g. 'ADR-001'). Optional for create, required for get/update/supersede.")] = None,
    title: Annotated[Optional[str], Field(description="Title of the ADR.")] = None,
    status: Annotated[Optional[str], Field(description="Status: 'PROPOSED', 'ACCEPTED', 'REJECTED', 'SUPERSEDED', 'DEPRECATED'.")] = None,
    context: Annotated[Optional[str], Field(description="Context and problem statement.")] = None,
    decision: Annotated[Optional[str], Field(description="Decision and changes made.")] = None,
    consequences: Annotated[Optional[str], Field(description="Consequences and trade-offs.")] = None,
    superseded_by: Annotated[Optional[str], Field(description="ID of superseding ADR.")] = None
) -> str:
    """Manage Architecture Decision Records (ADRs): read, create, update, supersede, or search records across repositories."""
    action_clean = action.lower().strip() if action else ""
    if not repo or not repo.strip():
        return json.dumps({"error": "repo parameter is required."})

    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        required_role = Role.EDITOR if action_clean in ("create", "update", "supersede") else Role.VIEWER
        enforce_tool_permission(required_role)
        from app.services.database import list_adrs, get_adr, create_adr, update_adr, supersede_adr

        if action_clean == "list":
            records = _get_tools_attr("list_adrs", list_adrs)(repo=repo, status=status)
            adrs = []
            for r in (records or []):
                adrs.append({
                    "id": r.get("id"),
                    "repo": r.get("repo", repo),
                    "title": r.get("title"),
                    "status": r.get("status"),
                    "superseded_by": r.get("superseded_by"),
                })
            return json.dumps({
                "action": "list",
                "repo": repo,
                "adrs": adrs,
            })

        elif action_clean == "get":
            if not id:
                return json.dumps({"error": "'id' parameter is required for action 'get'."})
            r = _get_tools_attr("get_adr", get_adr)(adr_id=id, repo=repo)
            if not r:
                return json.dumps({"error": f"ADR '{id}' not found in repo '{repo}'.", "found": False})
            return json.dumps({
                "action": "get",
                "found": True,
                "adr": {
                    "id": r.get("id"),
                    "repo": r.get("repo", repo),
                    "title": r.get("title"),
                    "status": r.get("status"),
                    "superseded_by": r.get("superseded_by"),
                    "created_at": r.get("created_at"),
                    "updated_at": r.get("updated_at"),
                    "context": r.get("context"),
                    "decision": r.get("decision"),
                    "consequences": r.get("consequences"),
                }
            })

        elif action_clean == "create":
            if not title:
                return json.dumps({"error": "'title' parameter is required for action 'create'."})
            res = _get_tools_attr("create_adr", create_adr)(
                repo=repo,
                title=title,
                status=status or "PROPOSED",
                context=context or "Context pending.",
                decision=decision or "Decision pending.",
                consequences=consequences,
                superseded_by=superseded_by,
                adr_id=id
            )
            return json.dumps({
                "action": "create",
                "status": "success",
                "repo": repo,
                "id": res.get("id"),
                "adr_status": res.get("status"),
                "adr": res,
            })

        elif action_clean == "update":
            if not id:
                return json.dumps({"error": "'id' parameter is required for action 'update'."})
            res = _get_tools_attr("update_adr", update_adr)(
                adr_id=id,
                repo=repo,
                title=title,
                status=status,
                context=context,
                decision=decision,
                consequences=consequences,
                superseded_by=superseded_by
            )
            return json.dumps({
                "action": "update",
                "status": "success",
                "repo": repo,
                "id": res.get("id"),
                "adr": res,
            })

        elif action_clean == "supersede":
            if not id:
                return json.dumps({"error": "'id' parameter is required for action 'supersede' (ID of old ADR to be superseded)."})
            if not superseded_by:
                return json.dumps({"error": "'superseded_by' parameter is required for action 'supersede' (ID of newer ADR)."})
            res = _get_tools_attr("supersede_adr", supersede_adr)(old_id=id, new_id=superseded_by, repo=repo)
            return json.dumps({
                "action": "supersede",
                "status": "success",
                "repo": repo,
                "id": id,
                "superseded_by": superseded_by,
                "adr": res,
            })

        else:
            return json.dumps({"error": f"Invalid action '{action}'. Supported actions: list, get, create, update, supersede."})

    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_manage_adr ({action_clean}): {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        logger.error(f"manage_adr error ({action_clean}): {e}")
        return json.dumps({"error": f"Error executing manage_adr action '{action}': {str(e)}"})
