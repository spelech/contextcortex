import json
import logging
from typing import List, Dict, Any, Optional, Annotated
from pydantic import Field

from app.services.database import get_db_connection, extract_host_from_url, get_adr, list_adrs, create_adr, update_adr, supersede_adr, upsert_adr
from app.services.search import execute_hybrid_search, trace_symbol_path
from app.services.indexing import get_dynamic_catalog_description, sync_single_git_repo, run_full_indexing
from app.services.vector_store import get_vector_store_config
from app.services.git_manager import format_git_permalink, format_git_commit_url
from app.services.chunking import match_route_and_call, normalize_path_pattern
from app.models.schemas import SearchRequest, FindSymbolRequest, GetFileOutlineRequest, SyncRequest

logger = logging.getLogger("contextcortex")
import sys

def _get_tools_attr(name, default):
    t_mod = sys.modules.get("app.mcp.tools")
    return getattr(t_mod, name, default) if t_mod else default


async def handle_list_repositories() -> str:
    """Lists all indexed local paths and remote Git repositories, including active branches, commit SHAs, and file counts."""
    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)
        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            git_repos = conn.execute("SELECT id, name, url, branch, commit_sha, provider, auth_user, status, last_synced FROM git_repositories").fetchall()
            local_paths = conn.execute("SELECT path, repo, category FROM indexed_paths WHERE enabled = 1").fetchall()
            counts = conn.execute("SELECT repo, count(*) as cnt FROM indexed_files GROUP BY repo").fetchall()
            file_count_map = {c["repo"]: c["cnt"] for c in counts}

        repos_list = []
        for gr in git_repos:
            repos_list.append({
                "id": gr["id"],
                "name": gr["name"],
                "url": gr["url"],
                "branch": gr["branch"],
                "commit_sha": gr["commit_sha"],
                "provider": (gr["provider"] or "git").lower(),
                "status": gr["status"],
                "files": file_count_map.get(gr["name"], 0),
                "last_synced": gr["last_synced"],
            })

        monitored_list = []
        for lp in local_paths:
            monitored_list.append({
                "repo": lp["repo"],
                "path": lp["path"],
                "category": lp["category"],
                "files": file_count_map.get(lp["repo"], 0),
            })

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
    repo: Annotated[Optional[str], Field(description="Repository name to sync (or omit to sync all).")] = None
) -> str:
    """Trigger an immediate re-fetch and re-indexing of a registered Git repo or local path."""
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
                sync_fn = idx_mod.sync_single_git_repo
                threading.Thread(
                    target=sync_fn,
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

        full_fn = idx_mod.run_full_indexing
        threading.Thread(target=full_fn, daemon=True).start()
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
    """Get global index health, vector counts, Git provider auth sources, and active embedding models."""
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
        stats = vs_cfg.get("stats", {})
        points_count = stats.get("points_count", 0)

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


async def handle_catalog_summary() -> str:
    """Catalog of indexed repositories, documentation files, and AST symbol distributions."""
    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)
        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            git_repos = conn.execute("SELECT name, url, branch, commit_sha, status, last_synced FROM git_repositories").fetchall()
            files = conn.execute("SELECT filepath, repo, doc_type, language FROM indexed_files").fetchall()
            symbols_count = conn.execute("SELECT count(*) FROM ast_symbols").fetchone()[0]
            try:
                sym_by_repo_rows = conn.execute("SELECT repo, count(*) as cnt FROM ast_symbols GROUP BY repo").fetchall()
                sym_by_repo = {r["repo"]: r["cnt"] for r in sym_by_repo_rows}
            except Exception:
                sym_by_repo = {}

        repo_file_counts: Dict[str, int] = {}
        repo_lang_counts: Dict[str, Dict[str, int]] = {}
        for f in files:
            r_name = f["repo"] or "unknown"
            lang = f["language"] or "text"
            repo_file_counts[r_name] = repo_file_counts.get(r_name, 0) + 1
            lang_map = repo_lang_counts.setdefault(r_name, {})
            lang_map[lang] = lang_map.get(lang, 0) + 1

        repos_data = []
        for gr in git_repos:
            r_name = gr["name"]
            repos_data.append({
                "name": r_name,
                "url": gr["url"],
                "branch": gr["branch"],
                "commit_sha": gr["commit_sha"],
                "status": gr["status"],
                "last_synced": gr["last_synced"],
                "files": repo_file_counts.get(r_name, 0),
                "symbols": sym_by_repo.get(r_name, 0),
                "languages": repo_lang_counts.get(r_name, {}),
            })

        files_data = []
        for f in files[:40]:
            fp = f["filepath"]
            clean_fp = (fp.split("://", 1)[1] if "://" in fp else fp).replace("\\", "/")
            files_data.append({
                "repo": f["repo"],
                "file": clean_fp,
                "doc_type": f["doc_type"],
                "language": f["language"],
            })

        return json.dumps({
            "total_files": len(files),
            "total_symbols": symbols_count,
            "git_repositories": repos_data,
            "files": files_data,
            "truncated_files": max(0, len(files) - 40),
        }, default=str)
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_catalog_summary: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        return json.dumps({"error": f"Error generating catalog resource: {str(e)}"})


def handle_search_infrastructure_docs(
    topic: Annotated[str, Field(description="The specific infrastructure topic to search for")]
) -> str:
    """Workflow to search system infrastructure documentation, container mappings, or network routes."""
    from app.services.auth import enforce_tool_permission, Role
    enforce_tool_permission(Role.VIEWER)
    return json.dumps({
        "prompt": "search_infrastructure_docs",
        "topic": topic,
        "recommended_tools": ["search_docs", "manage_adr", "read_file", "grep_code"],
        "instructions": (
            f"1. Call search_docs(query='{topic}', search_mode='hybrid') to locate relevant architecture notes, runbooks, and container configs.\n"
            f"2. Call manage_adr(action='search', query='{topic}') to check if any Architectural Decision Records govern '{topic}'.\n"
            f"3. For the top matching files, call read_file(path=..., repo=..., start_line=..., end_line=...) to verify exact port mappings, environment variables, or reverse proxy routes before summarizing."
        ),
    })


def handle_onboard_repository(
    repo: Annotated[str, Field(description="Repository name to onboard and map out")]
) -> str:
    """Structured workflow to rapidly understand a repository's architecture, entry points, API routes, and recent activity."""
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
    issue_text: Annotated[str, Field(description="Stack trace, exception message, or failing HTTP route")],
    repo: Annotated[Optional[str], Field(description="Optional target repository name")] = None
) -> str:
    """Forensic workflow to diagnose an error, stack trace, or failing endpoint down to root-cause lines and recent commits."""
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
    symbol: Annotated[str, Field(description="Function, method, or class name being modified")],
    repo: Annotated[Optional[str], Field(description="Optional repository name")] = None
) -> str:
    """Blast-radius workflow to identify all internal callers, cross-repo API consumers, and tests affected by changing a symbol."""
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
    repo: Annotated[str, Field(description="Repository name to inspect recent commits for.")],
    filepath: Annotated[Optional[str], Field(description="Optional relative file path filter to only return commits touching this file.")] = None,
    symbol: Annotated[Optional[str], Field(description="Optional AST symbol name; resolves symbol's file path and filters commits touching that file.")] = None,
    limit: Annotated[int, Field(description="Max commits to return (default 10, max 50).")] = 10,
) -> str:
    """Returns recent commit history for a repository, optionally filtered by file path or symbol name."""
    try:
        from app.services.auth import enforce_tool_permission, Role
        enforce_tool_permission(Role.VIEWER)

        safe_limit = max(1, min(limit if limit is not None else 10, 50))

        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            repo_row = conn.execute(
                "SELECT id, name, url, provider, retain_commits_count FROM git_repositories WHERE name = ?",
                (repo,)
            ).fetchone()

            retained_limit = (
                int(repo_row["retain_commits_count"])
                if repo_row and "retain_commits_count" in repo_row.keys() and repo_row["retain_commits_count"] is not None
                else 20
            )

            # Check if repository has commits in git_commits
            stored_count = 0
            if repo_row:
                count_row = conn.execute("SELECT count(*) as c FROM git_commits WHERE repo = ?", (repo,)).fetchone()
                stored_count = count_row["c"] if count_row else 0

            # If retain_commits_count == 0 or no commits are stored
            if not repo_row or retained_limit == 0 or stored_count == 0:
                fallback_resp = {
                    "repo": repo,
                    "retained": False,
                    "retained_limit": retained_limit if repo_row else 0,
                    "commits": [],
                    "message": f"Commit history is not retained for repository '{repo}' (retain_commits_count={retained_limit if repo_row else 0}). Retrieve commit history directly from the Git repository."
                }
                return json.dumps(fallback_resp, separators=(",", ":"), default=str)

            git_url = repo_row["url"]
            provider = repo_row["provider"]

            # Resolve filter filepath
            target_filepath = None
            if filepath and filepath.strip():
                clean_fp = filepath.strip().replace("\\", "/").lstrip("/")
                target_filepath = clean_fp
            elif symbol and symbol.strip():
                sym_row = conn.execute(
                    "SELECT filepath FROM ast_symbols WHERE repo = ? AND (name = ? OR full_symbol = ?) LIMIT 1",
                    (repo, symbol.strip(), symbol.strip())
                ).fetchone()
                if sym_row:
                    raw_fp = sym_row["filepath"]
                    if "://" in raw_fp:
                        target_filepath = raw_fp.split("://", 1)[1].replace("\\", "/")
                    else:
                        target_filepath = raw_fp.replace("\\", "/")

            # Query commits from git_commits
            rows = conn.execute(
                "SELECT commit_sha, author, committed_at, message, files_changed FROM git_commits WHERE repo = ? ORDER BY committed_at DESC, id DESC",
                (repo,)
            ).fetchall()

            matched_commits = []
            for r in rows:
                files_raw = r["files_changed"]
                try:
                    files_list = [f.replace("\\", "/") for f in (json.loads(files_raw) if files_raw else [])]
                except Exception:
                    files_list = []

                if target_filepath:
                    norm_target = target_filepath.replace("\\", "/").lstrip("/")
                    matched = False
                    for f in files_list:
                        norm_f = f.replace("\\", "/").lstrip("/")
                        if norm_f == norm_target or norm_f.endswith("/" + norm_target) or norm_target.endswith("/" + norm_f):
                            matched = True
                            break
                    if not matched:
                        continue

                commit_url = format_git_commit_url(git_url, r["commit_sha"], provider=provider)
                matched_commits.append({
                    "sha": r["commit_sha"],
                    "short_sha": r["commit_sha"][:7],
                    "author": r["author"],
                    "date": r["committed_at"],
                    "message": r["message"],
                    "files_changed": files_list,
                    "commit_url": commit_url,
                })

                if len(matched_commits) >= safe_limit:
                    break

            result = {
                "repo": repo,
                "retained_limit": retained_limit,
                "commits": matched_commits,
            }
            if target_filepath:
                result["filter_filepath"] = target_filepath

            return json.dumps(result, separators=(",", ":"), default=str)

    except Exception as e:
        logger.error(f"Error in handle_get_recent_changes: {e}")
        return json.dumps({"error": str(e), "repo": repo, "commits": []}, separators=(",", ":"))
