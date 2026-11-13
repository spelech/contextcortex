import json
import logging
import os
import sys
import threading
from typing import Any, Dict, List, Literal, Optional, Annotated
from pydantic import Field

from app.services.auth import enforce_tool_permission, Role, ForbiddenError
from app.services.database import get_db_connection
from app.services.local_storage import get_local_storage_service
from app.services.pdf_extractor import extract_pdf_pages
from app.services.vector_store import get_vector_store_config

logger = logging.getLogger("contextcortex.mcp")


def _get_tools_attr(name, default):
    t_mod = sys.modules.get("app.mcp.tools")
    return getattr(t_mod, name, default) if t_mod else default


def _strip_repo_prefix(filepath: Optional[str]) -> str:
    if not filepath:
        return ""
    res = filepath.split("://", 1)[1] if "://" in filepath else filepath
    return res.replace("\\", "/")


def build_source_file_slice(paths: List[str], offset: int, limit: int) -> Dict[str, Any]:
    total_files = len(paths)
    sliced = paths[offset : offset + limit]
    has_more = (offset + limit) < total_files
    return {
        "total_files": total_files,
        "offset": offset,
        "limit": limit,
        "has_more": has_more,
        "next_offset": (offset + limit) if has_more else None,
        "file_paths": sliced,
    }


def collect_local_storage_entry(
    per_repo_paths: Dict[str, List[str]],
    repo_file_counts: Dict[str, int],
    want_files: bool,
    path_prefix: Optional[str],
    file_extension: Optional[str],
    safe_offset: int,
    safe_limit: int,
) -> Dict[str, Any]:
    storage = _get_tools_attr("get_local_storage_service", get_local_storage_service)()
    s_root = storage.get_storage_root()
    tree = storage.get_file_tree(subfolder=path_prefix if path_prefix and not path_prefix.startswith("/") else None)
    ls_paths = list(per_repo_paths.get("local_storage") or [])
    if want_files and not ls_paths and s_root and os.path.isdir(s_root):
        for dpath, _, fnames in os.walk(s_root):
            for fn in sorted(fnames):
                rel_f = os.path.relpath(os.path.join(dpath, fn), s_root).replace("\\", "/")
                if path_prefix and path_prefix not in rel_f:
                    continue
                if file_extension and not rel_f.endswith(file_extension):
                    continue
                ls_paths.append(rel_f)
        ls_paths.sort()
    total_ls_files = repo_file_counts.get("local_storage", len(tree.get("files", [])))
    ls_entry: Dict[str, Any] = {
        "root_path": s_root,
        "total_files": len(ls_paths) if want_files else total_ls_files,
        "directories": [d["name"] for d in tree.get("directories", [])],
    }
    if want_files:
        ls_slice = build_source_file_slice(ls_paths, safe_offset, safe_limit)
        ls_entry.update(ls_slice)
        ls_entry["files"] = ls_slice["file_paths"]
    return ls_entry


def collect_index_status() -> Dict[str, Any]:
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
    return payload


async def handle_manage(
    action: Annotated[Literal["sync_repo", "upload", "replace", "delete", "read", "preview"], Field(description="Admin/storage operation: 'sync_repo' (re-fetch/index Git repo or all sources), 'upload', 'replace', 'delete' (editor role), or 'read', 'preview' (viewer role) on managed local storage.")],
    repo: Annotated[Optional[str], Field(description="Target Git repository name for 'sync_repo' (omit for full re-index), or storage namespace tag for file operations (default 'local_storage').")] = None,
    file_path: Annotated[Optional[str], Field(description="Safe relative path inside managed local storage (required for 'upload', 'replace', 'delete', 'read', and 'preview').")] = None,
    content: Annotated[Optional[str], Field(description="UTF-8 text payload to write when action is 'upload' or 'replace'.")] = None,
    category: Annotated[Optional[str], Field(description="Optional document category metadata tag (e.g. 'runbook', 'architecture').")] = None,
) -> str:
    """Manage repository synchronization and local storage files with RBAC enforcement and immediate indexing."""
    act = (action or "").strip().lower()
    try:
        if act in ("sync_repo", "upload", "replace", "delete"):
            enforce_tool_permission(Role.EDITOR)
        elif act in ("read", "preview"):
            enforce_tool_permission(Role.VIEWER)
        else:
            return json.dumps({
                "error": f"Unsupported action '{action}'. Valid actions are 'sync_repo', 'upload', 'replace', 'delete', 'read', 'preview'."
            })

        if act == "sync_repo":
            import app.services.indexing as idx_mod
            target_repo = repo.strip() if repo and repo.strip() else None
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
                        "action": "sync_repo",
                        "status": "triggered",
                        "scope": "repository",
                        "repo": target_repo,
                        "message": f"Triggered background sync for repo: '{target_repo}'",
                    })
            threading.Thread(target=idx_mod.run_full_indexing, daemon=True).start()
            return json.dumps({
                "action": "sync_repo",
                "status": "triggered",
                "scope": "full",
                "repo": target_repo,
                "message": "Triggered full background re-indexing.",
            })

        if not file_path or not file_path.strip():
            return json.dumps({"error": f"'file_path' parameter is required for action '{act}'."})

        storage = _get_tools_attr("get_local_storage_service", get_local_storage_service)()
        target_ns = repo.strip() if repo and repo.strip() else "local_storage"

        if act in ("upload", "replace"):
            if content is None:
                return json.dumps({"error": f"'content' parameter is required for action '{act}'."})
            res = storage.save_file(file_path, content, repo=target_ns, category=category)
            return json.dumps({
                "action": act,
                "status": "success",
                "file": _strip_repo_prefix(res.get("rel_path") or file_path),
                "repo": res.get("repo", target_ns),
                "category": res.get("category", category),
                "size_bytes": res.get("size_bytes", 0),
                "chunks_indexed": res.get("chunks_indexed", 0),
            })

        if act == "delete":
            storage.delete_file(file_path, repo=target_ns)
            return json.dumps({
                "action": "delete",
                "status": "success",
                "file": _strip_repo_prefix(file_path),
                "repo": target_ns,
            })

        if act == "read":
            res = storage.read_file_content(file_path)
            if res.get("is_pdf"):
                raw_content = res["content"]
                if isinstance(raw_content, str):
                    try:
                        parsed = json.loads(raw_content)
                        return json.dumps({
                            "action": "read",
                            "file": _strip_repo_prefix(res.get("rel_path") or file_path),
                            "is_pdf": True,
                            **parsed,
                        })
                    except Exception:
                        pass
                return json.dumps({
                    "action": "read",
                    "file": _strip_repo_prefix(res.get("rel_path") or file_path),
                    "is_pdf": True,
                    "content": raw_content,
                })
            return json.dumps({
                "action": "read",
                "file": _strip_repo_prefix(res.get("rel_path") or file_path),
                "size_bytes": res.get("size_bytes", 0),
                "content": res.get("content", ""),
            })

        abs_path = storage.resolve_safe_path(file_path)
        if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
            raise FileNotFoundError(f"File '{file_path}' does not exist in local storage.")

        if file_path.lower().endswith(".pdf") or abs_path.lower().endswith(".pdf"):
            pdf_extractor_fn = _get_tools_attr("extract_pdf_pages", extract_pdf_pages)
            pdf_res = pdf_extractor_fn(abs_path, filename=os.path.basename(file_path), ocr_fallback=False)
            first_page_text = pdf_res.pages[0].text[:1000] if pdf_res.pages else ""
            return json.dumps({
                "action": "preview",
                "file": _strip_repo_prefix(file_path),
                "is_pdf": True,
                "total_pages": pdf_res.total_pages,
                "total_characters": pdf_res.total_characters,
                "ocr_pages_count": pdf_res.ocr_pages_count,
                "errors": pdf_res.errors or [],
                "sample_chunks": len(pdf_res.preview_chunks),
                "preview": first_page_text,
            })
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            text_content = f.read()
        return json.dumps({
            "action": "preview",
            "file": _strip_repo_prefix(file_path),
            "is_pdf": False,
            "line_count": len(text_content.splitlines()),
            "character_count": len(text_content),
            "preview": text_content[:1000],
        })
    except ForbiddenError as e:
        logger.warning(f"Forbidden error executing manage ({action}): {e}")
        return json.dumps({"error": f"Forbidden: {str(e)}", "forbidden": True})
    except Exception as e:
        logger.error(f"Error executing manage ({action}): {e}")
        return json.dumps({"error": f"Error executing manage: {str(e)}"})
