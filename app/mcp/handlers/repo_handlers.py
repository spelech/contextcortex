import json
import logging
import sys
from typing import Dict, Any, Optional, Annotated
from pydantic import Field

from app.services.database import get_db_connection
from app.services.vector_store import get_vector_store_config
from app.services.git_manager import format_git_commit_url
from app.mcp.handlers.resource_handlers import handle_catalog_summary

logger = logging.getLogger("contextcortex")

MAX_COMMIT_FILES_CHANGED = 25


def _get_tools_attr(name, default):
    t_mod = sys.modules.get("app.mcp.tools")
    return getattr(t_mod, name, default) if t_mod else default


async def handle_list_repositories() -> str:
    """List all registered Git repositories and monitored local directory paths with branches, commit SHAs, sync status, and file counts."""
    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)
        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            git_repos = conn.execute(
                "SELECT id, name, url, branch, commit_sha, provider, auth_user, status, last_synced FROM git_repositories"
            ).fetchall()
            local_paths = conn.execute(
                "SELECT path, repo, category FROM indexed_paths WHERE enabled = 1"
            ).fetchall()
            counts = conn.execute("SELECT repo, count(*) as cnt FROM indexed_files GROUP BY repo").fetchall()
            file_count_map = {c["repo"]: c["cnt"] for c in counts}

        repos_list = [
            {
                "id": gr["id"],
                "name": gr["name"],
                "url": gr["url"],
                "branch": gr["branch"],
                "commit_sha": gr["commit_sha"],
                "provider": (gr["provider"] or "git").lower(),
                "status": gr["status"],
                "files": file_count_map.get(gr["name"], 0),
                "last_synced": gr["last_synced"],
            }
            for gr in git_repos
        ]

        monitored_list = [
            {
                "repo": lp["repo"],
                "path": lp["path"],
                "category": lp["category"],
                "files": file_count_map.get(lp["repo"], 0),
            }
            for lp in local_paths
        ]

        return json.dumps({
            "git_repositories": repos_list,
            "local_paths": monitored_list,
        }, default=str)
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_list_repositories: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        return json.dumps({"error": f"Error listing repositories: {str(e)}"})


async def handle_sync_repository(
    repo: Annotated[Optional[str], Field(description="Optional registered Git repository name to re-fetch and delta-index. Omit to trigger a full background re-indexing run across all sources (requires editor role).")] = None,
) -> str:
    """Trigger an asynchronous background Git delta fetch or full repository re-indexing run."""
    target_repo = repo
    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.EDITOR)
        import app.services.indexing as idx_mod
        import threading
        if target_repo:
            with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
                row = conn.execute("SELECT id FROM git_repositories WHERE name = ?", (target_repo,)).fetchone()
            if row:
                threading.Thread(
                    target=idx_mod.sync_single_git_repo,
                    args=(row["id"],),
                    kwargs={"force": True},
                    daemon=True,
                ).start()
                return json.dumps({
                    "status": "triggered",
                    "scope": "repository",
                    "repo": target_repo,
                    "message": f"Triggered background sync for repo: '{target_repo}'",
                })

        threading.Thread(target=idx_mod.run_full_indexing, daemon=True).start()
        return json.dumps({
            "status": "triggered",
            "scope": "full",
            "repo": target_repo,
            "message": "Triggered full background re-indexing.",
        })
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_sync_repository: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        return json.dumps({"error": f"Failed to trigger sync: {str(e)}"})


async def handle_index_status() -> str:
    """Inspect global vector store health, point counts, active dense/sparse embedding models, and Git provider auth status."""
    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)
        from app.services.git_manager import check_github_rate_limit, mask_token
        from app.services.database import get_effective_git_token, list_git_host_credentials
        from app.services.embeddings import EMBEDDING_PROVIDER, DENSE_MODEL_NAME, SPARSE_MODEL_NAME, get_embedding_config

        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            files_count = conn.execute("SELECT count(*) FROM indexed_files").fetchone()[0]
            symbols_count = conn.execute("SELECT count(*) FROM ast_symbols").fetchone()[0]
            git_count = conn.execute("SELECT count(*) FROM git_repositories").fetchone()[0]

        vs_cfg = _get_tools_attr("get_vector_store_config", get_vector_store_config)()
        provider = vs_cfg.get("provider", "qdrant").upper()
        mode_val = vs_cfg.get("mode", "embedded")
        mode_str = "Remote" if mode_val == "remote" else "Embedded Disk"
        storage_loc = vs_cfg.get("url") if mode_val == "remote" else vs_cfg.get("storage_path")
        collection_name = vs_cfg.get("collection", "knowledge_rag_v1")
        points_count = vs_cfg.get("stats", {}).get("points_count", 0)

        emb_cfg = get_embedding_config()
        effective_sparse = (
            "PostgreSQL Full-Text Search (tsvector + GIN)"
            if provider == "PGVECTOR"
            else emb_cfg.get("effective_sparse_model") or SPARSE_MODEL_NAME
        )

        gh_tok, _, gh_src = get_effective_git_token("https://github.com", provider="github")
        gl_tok, _, gl_src = get_effective_git_token("https://gitlab.com", provider="gitlab")
        gt_tok, _, gt_src = get_effective_git_token("https://gitea.com", provider="gitea")
        vault_failed = False
        try:
            vault_creds = list_git_host_credentials()
        except Exception as e:
            logger.error(f"Failed to list vault credentials for status: {e}")
            vault_creds = []
            vault_failed = True
        rate_info = check_github_rate_limit(gh_tok)

        vault_status = "[Unavailable - Query Failed]" if vault_failed else len(vault_creds)
        payload: Dict[str, Any] = {
            "vector_store": {
                "provider": provider,
                "mode": mode_val,
                "mode_label": mode_str,
                "location": storage_loc,
                "collection": collection_name,
                "total_vectors": points_count,
            },
            "embeddings": {
                "provider": EMBEDDING_PROVIDER.upper(),
                "dense_model": DENSE_MODEL_NAME,
                "sparse_model": effective_sparse,
            },
            "counts": {
                "indexed_files": files_count,
                "ast_symbols": symbols_count,
                "git_repositories": git_count,
            },
            "git_auth": {
                "github": {"source": gh_src, "token": mask_token(gh_tok)},
                "gitlab": {"source": gl_src},
                "gitea": {"source": gt_src},
                "host_vaults": vault_status,
            },
        }
        if gh_tok:
            payload["github_rate_limit"] = {
                "remaining": rate_info.get("remaining", 0),
                "limit": rate_info.get("limit", 60),
            }

        return json.dumps(payload, default=str)
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_index_status: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        return json.dumps({"error": f"Failed to get status: {str(e)}"})


def handle_search_infrastructure_docs(
    topic: Annotated[str, Field(description="Infrastructure topic, network route, or deployment subsystem to investigate.")],
) -> str:
    """Workflow prompt to search infrastructure documentation, ADRs, container mappings, and network routes."""
    from app.services.auth import enforce_tool_permission, Role
    enforce_tool_permission(Role.VIEWER)
    return json.dumps({
        "prompt": "search_infrastructure_docs",
        "topic": topic,
        "recommended_tools": ["search_docs", "manage_adr", "read_file", "grep_code"],
        "instructions": (
            f"1. Call search_docs(query='{topic}', mode='hybrid') to locate relevant architecture notes, runbooks, and container configs.\n"
            f"2. Call manage_adr(action='search', query='{topic}') to check if any Architectural Decision Records govern '{topic}'.\n"
            f"3. For the top matching files, call read_file(path=..., repo=..., start_line=..., end_line=...) to verify exact port mappings, environment variables, or reverse proxy routes before summarizing."
        ),
    })


def handle_onboard_repository(
    repo: Annotated[str, Field(description="Repository name to map out and onboard.")],
) -> str:
    """Structured workflow prompt to map a repository's architecture, routes, outlines, and recent commits."""
    from app.services.auth import enforce_tool_permission, Role
    enforce_tool_permission(Role.VIEWER)
    return json.dumps({
        "prompt": "onboard_repository",
        "repo": repo,
        "recommended_tools": ["get_architecture", "find_routes", "get_file_outline", "get_recent_changes"],
        "instructions": (
            f"1. Call get_architecture(repo='{repo}') to inspect language distribution, manifests, entry points, primary modules, hub symbols, and active ADRs.\n"
            f"2. Call find_routes(repo='{repo}') to enumerate exposed HTTP/API endpoints and their handler symbols.\n"
            f"3. For each entry point or hub symbol file, call get_file_outline(filepath=..., repo='{repo}') to map its classes and functions without reading entire files.\n"
            f"4. Call get_recent_changes(repo='{repo}', limit=10) to review recent commits and active development areas."
        ),
    })


def handle_triage_error(
    issue_text: Annotated[str, Field(description="Stack trace, exception message, or failing HTTP endpoint.")],
    repo: Annotated[Optional[str], Field(description="Optional target repository name.")] = None,
) -> str:
    """Forensic workflow prompt to diagnose stack traces or failing endpoints down to root-cause lines and recent commits."""
    from app.services.auth import enforce_tool_permission, Role
    enforce_tool_permission(Role.VIEWER)
    return json.dumps({
        "prompt": "triage_error",
        "issue_text": issue_text,
        "repo": repo,
        "recommended_tools": ["diagnose_issue", "trace_path", "read_file", "get_recent_changes"],
        "instructions": (
            f"1. Call diagnose_issue(issue_text={json.dumps(issue_text)}, repo={json.dumps(repo)}) to resolve stack frames, error string literals, matching routes, and semantic candidates.\n"
            f"2. For the primary resolved symbol, call trace_path(symbol=..., repo={json.dumps(repo)}, direction='both', depth=2) to inspect upstream callers and downstream callees.\n"
            f"3. Call read_file(path=..., repo=..., start_line=..., end_line=...) around the suspect lines to inspect error handling and state mutations.\n"
            f"4. Call get_recent_changes(repo=..., filepath=...) on the suspect file to check for recent regressions."
        ),
    })


def handle_investigate_change_impact(
    symbol: Annotated[str, Field(description="Function, method, or class name being modified.")],
    repo: Annotated[Optional[str], Field(description="Optional repository name.")] = None,
) -> str:
    """Blast-radius workflow prompt to identify callers, cross-repo API consumers, and tests affected by modifying a symbol."""
    from app.services.auth import enforce_tool_permission, Role
    enforce_tool_permission(Role.VIEWER)
    return json.dumps({
        "prompt": "investigate_change_impact",
        "symbol": symbol,
        "repo": repo,
        "recommended_tools": ["find_symbol", "trace_path", "find_api_callers", "grep_code"],
        "instructions": (
            f"1. Call find_symbol(name='{symbol}', repo={json.dumps(repo)}, exact=True) to locate the symbol's exact file and line range.\n"
            f"2. Call trace_path(symbol='{symbol}', repo={json.dumps(repo)}, direction='callers', depth=3) to map all direct and transitive callers.\n"
            f"3. If the symbol handles or invokes an API route, call find_api_callers(path=...) to discover cross-repository client callers.\n"
            f"4. Call grep_code(pattern='{symbol}', repo={json.dumps(repo)}) to catch dynamic references, configuration bindings, and unit tests."
        ),
    })


async def handle_get_recent_changes(
    repo: Annotated[str, Field(description="Registered Git repository name to inspect retained commit history for.")],
    filepath: Annotated[Optional[str], Field(description="Optional relative file path filter returning only commits touching that file.")] = None,
    symbol: Annotated[Optional[str], Field(description="Optional AST symbol name (Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, C/C++); resolves its file path and filters commits touching it.")] = None,
    limit: Annotated[int, Field(description="Maximum commits returned per page, clamped to 1..50 (default 10). Each commit caps files_changed to 25 entries.")] = 10,
    offset: Annotated[int, Field(description="0-based commit offset for pagination (default 0). Advance via next_offset when has_more is True.")] = 0,
) -> str:
    """Inspect retained Git commit history filtered by file path or AST symbol with bounded file-change lists and pagination."""
    try:
        from app.services.auth import enforce_tool_permission, Role
        enforce_tool_permission(Role.VIEWER)

        safe_limit = max(1, min(int(limit if limit is not None else 10), 50))
        safe_offset = max(0, int(offset if offset is not None else 0))

        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            repo_row = conn.execute(
                "SELECT id, name, url, provider, retain_commits_count FROM git_repositories WHERE name = ?",
                (repo,),
            ).fetchone()

            retained_limit = (
                int(repo_row["retain_commits_count"])
                if repo_row and "retain_commits_count" in repo_row.keys() and repo_row["retain_commits_count"] is not None
                else 20
            )

            stored_count = 0
            if repo_row:
                count_row = conn.execute("SELECT count(*) as c FROM git_commits WHERE repo = ?", (repo,)).fetchone()
                stored_count = count_row["c"] if count_row else 0

            if not repo_row or retained_limit == 0 or stored_count == 0:
                fallback_resp = {
                    "repo": repo,
                    "retained": False,
                    "retained_limit": retained_limit if repo_row else 0,
                    "total": 0,
                    "offset": safe_offset,
                    "limit": safe_limit,
                    "has_more": False,
                    "next_offset": None,
                    "commits": [],
                    "message": (
                        f"Commit history is not retained for repository '{repo}' "
                        f"(retain_commits_count={retained_limit if repo_row else 0}). "
                        "Retrieve commit history directly from the Git repository."
                    ),
                }
                return json.dumps(fallback_resp, separators=(",", ":"), default=str)

            git_url = repo_row["url"]
            provider = repo_row["provider"]

            target_filepath = None
            if filepath and filepath.strip():
                target_filepath = filepath.strip().replace("\\", "/").lstrip("/")
            elif symbol and symbol.strip():
                sym_row = conn.execute(
                    "SELECT filepath FROM ast_symbols WHERE repo = ? AND (name = ? OR full_symbol = ?) LIMIT 1",
                    (repo, symbol.strip(), symbol.strip()),
                ).fetchone()
                if sym_row:
                    raw_fp = sym_row["filepath"]
                    target_filepath = (raw_fp.split("://", 1)[1] if "://" in raw_fp else raw_fp).replace("\\", "/")

            rows = conn.execute(
                "SELECT commit_sha, author, committed_at, message, files_changed FROM git_commits WHERE repo = ? ORDER BY committed_at DESC, id DESC",
                (repo,),
            ).fetchall()

            all_matched = []
            for r in rows:
                files_raw = r["files_changed"]
                try:
                    files_list = [f.replace("\\", "/") for f in (json.loads(files_raw) if files_raw else [])]
                except Exception:
                    files_list = []

                if target_filepath:
                    norm_target = target_filepath.replace("\\", "/").lstrip("/")
                    matched = any(
                        (nf := f.replace("\\", "/").lstrip("/")) == norm_target
                        or nf.endswith("/" + norm_target)
                        or norm_target.endswith("/" + nf)
                        for f in files_list
                    )
                    if not matched:
                        continue

                files_total = len(files_list)
                files_truncated = files_total > MAX_COMMIT_FILES_CHANGED
                commit_url = format_git_commit_url(git_url, r["commit_sha"], provider=provider)
                all_matched.append({
                    "sha": r["commit_sha"],
                    "short_sha": r["commit_sha"][:7],
                    "author": r["author"],
                    "date": r["committed_at"],
                    "message": r["message"],
                    "files_changed": files_list[:MAX_COMMIT_FILES_CHANGED],
                    "files_changed_total": files_total,
                    "files_changed_truncated": files_truncated,
                    "commit_url": commit_url,
                })

            total = len(all_matched)
            paged_commits = all_matched[safe_offset : safe_offset + safe_limit]
            has_more = (safe_offset + safe_limit) < total
            next_offset = (safe_offset + safe_limit) if has_more else None

            result: Dict[str, Any] = {
                "repo": repo,
                "retained_limit": retained_limit,
                "total": total,
                "offset": safe_offset,
                "limit": safe_limit,
                "has_more": has_more,
                "next_offset": next_offset,
                "commits": paged_commits,
            }
            if target_filepath:
                result["filter_filepath"] = target_filepath

            return json.dumps(result, separators=(",", ":"), default=str)

    except Exception as e:
        logger.error(f"Error in handle_get_recent_changes: {e}")
        return json.dumps({"error": str(e), "repo": repo, "commits": []}, separators=(",", ":"))
