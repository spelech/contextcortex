import os
import json
import logging
import sys
from typing import Any, Dict, List, Optional, Annotated
from pydantic import Field

from app.services.auth import enforce_tool_permission, Role, ForbiddenError
from app.services.local_storage import get_local_storage_service
from app.services.database import get_db_connection
from app.services.pdf_extractor import extract_pdf_pages

logger = logging.getLogger("contextcortex.mcp")


def _get_tools_attr(name, default):
    t_mod = sys.modules.get("app.mcp.tools")
    return getattr(t_mod, name, default) if t_mod else default


def _strip_repo_prefix(filepath: Optional[str]) -> str:
    if not filepath:
        return ""
    res = filepath.split("://", 1)[1] if "://" in filepath else filepath
    return res.replace("\\", "/")


def _build_source_file_slice(paths: List[str], offset: int, limit: int) -> Dict[str, Any]:
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


async def handle_manage_local_file(
    action: Annotated[str, Field(description="Storage operation: 'upload', 'replace', 'delete' (requires editor role), or 'read', 'preview' (viewer role).")],
    file_path: Annotated[str, Field(description="Safe relative path inside managed local storage (e.g. 'docs/runbook.md' or 'specs/api.pdf').")],
    content: Annotated[Optional[str], Field(description="UTF-8 text payload to write when action is 'upload' or 'replace'.")] = None,
    repo: Annotated[str, Field(description="Repository or storage namespace tag for vector/AST indexing (default 'local_storage').")] = "local_storage",
    category: Annotated[Optional[str], Field(description="Optional document category metadata tag (e.g. 'runbook', 'architecture').")] = None,
) -> str:
    """Upload, replace, preview, read, or delete managed local storage files with immediate AST and vector indexing."""
    try:
        storage = _get_tools_attr("get_local_storage_service", get_local_storage_service)()
        act = (action or "").strip().lower()

        if act in ("upload", "replace", "delete"):
            enforce_tool_permission(Role.EDITOR)
        else:
            enforce_tool_permission(Role.VIEWER)

        if act in ("upload", "replace"):
            if content is None:
                return json.dumps({"error": f"'content' parameter is required for action '{action}'."})
            res = storage.save_file(file_path, content, repo=repo, category=category)
            return json.dumps({
                "action": act,
                "status": "success",
                "file": _strip_repo_prefix(res.get("rel_path") or file_path),
                "repo": res.get("repo", repo),
                "category": res.get("category", category),
                "size_bytes": res.get("size_bytes", 0),
                "chunks_indexed": res.get("chunks_indexed", 0),
            })

        if act == "delete":
            storage.delete_file(file_path, repo=repo)
            return json.dumps({
                "action": "delete",
                "status": "success",
                "file": _strip_repo_prefix(file_path),
                "repo": repo,
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

        if act == "preview":
            if not file_path or not file_path.strip():
                return json.dumps({"error": "'file_path' parameter is required for action 'preview'."})
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

        return json.dumps({"error": f"Unsupported action '{action}'. Valid actions are 'upload', 'replace', 'delete', 'read', 'preview'."})
    except ForbiddenError as e:
        logger.warning(f"Forbidden error executing manage_local_file ({action}): {e}")
        return json.dumps({"error": f"Forbidden: {str(e)}", "forbidden": True})
    except Exception as e:
        logger.error(f"Error executing manage_local_file ({action}): {e}")
        return json.dumps({"error": f"Error executing manage_local_file: {str(e)}"})


async def handle_what_is_ingested(
    source_type: Annotated[str, Field(description="Source filter: 'all' (default), 'git', 'monitored_path', or 'local_storage'.")] = "all",
    repo_name: Annotated[Optional[str], Field(description="Optional repository or storage namespace filter.")] = None,
    path_prefix: Annotated[Optional[str], Field(description="Optional file path substring/prefix filter (e.g. 'app/services').")] = None,
    file_extension: Annotated[Optional[str], Field(description="Optional file extension filter (e.g. '.py', '.ts', '.cs', '.cbl').")] = None,
    detail_level: Annotated[str, Field(description="Granularity: 'summary' (default counts/metadata) or 'detailed' (includes paginated file inventory).")] = "summary",
    include_files: Annotated[bool, Field(description="Set True to include bounded, paginated file lists per source and at top level (default False unless detail_level='detailed').")] = False,
    limit: Annotated[int, Field(description="Maximum files returned per source and top-level page when include_files=True or detail_level='detailed', clamped to 1..500 (default 100).")] = 100,
    offset: Annotated[int, Field(description="0-based file offset when include_files=True or detail_level='detailed' (default 0). Advance via next_offset when has_more is True.")] = 0,
) -> str:
    """Inspect ingested Git repositories, monitored local directories, and managed local storage with bounded file pagination."""
    try:
        enforce_tool_permission(Role.VIEWER)
        st = (source_type or "all").strip().lower()
        detail = (detail_level or "summary").strip().lower()
        want_files = bool(include_files or detail == "detailed")
        safe_limit = max(1, min(int(limit if limit is not None else 100), 500))
        safe_offset = max(0, int(offset if offset is not None else 0))

        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            git_repos = conn.execute(
                "SELECT id, name, url, branch, commit_sha, provider, status, last_synced FROM git_repositories"
            ).fetchall()
            indexed_paths = conn.execute(
                "SELECT path, repo, category FROM indexed_paths WHERE enabled = 1"
            ).fetchall()
            f_counts = conn.execute("SELECT repo, count(*) as cnt FROM indexed_files GROUP BY repo").fetchall()
            repo_file_counts = {r["repo"]: r["cnt"] for r in f_counts}
            s_counts = conn.execute("SELECT repo, count(*) as cnt FROM ast_symbols GROUP BY repo").fetchall()
            repo_symbol_counts = {s["repo"]: s["cnt"] for s in s_counts}

            matched_file_rows = []
            if want_files:
                query = "SELECT filepath, repo, doc_type, language, mtime FROM indexed_files WHERE 1=1"
                params: List[Any] = []
                if repo_name:
                    query += " AND repo = ?"
                    params.append(repo_name)
                if path_prefix:
                    query += " AND filepath LIKE ?"
                    params.append(f"%{path_prefix}%")
                if file_extension:
                    query += " AND filepath LIKE ?"
                    params.append(f"%{file_extension}%")
                query += " ORDER BY repo ASC, filepath ASC"
                matched_file_rows = conn.execute(query, params).fetchall()

        per_repo_paths: Dict[str, List[str]] = {}
        formatted_all_files: List[Dict[str, Any]] = []
        for df in matched_file_rows:
            r_key = df["repo"] or "unknown"
            clean_fp = _strip_repo_prefix(df["filepath"])
            per_repo_paths.setdefault(r_key, []).append(clean_fp)
            formatted_all_files.append({
                "repo": df["repo"],
                "file": clean_fp,
                "doc_type": df["doc_type"],
                "language": df["language"],
            })

        result: Dict[str, Any] = {
            "source_type": st,
            "detail_level": detail,
            "include_files": want_files,
        }

        if st in ("all", "git"):
            filtered_repos = [r for r in git_repos if not repo_name or r["name"] == repo_name]
            git_out = []
            for gr in filtered_repos:
                r_name = gr["name"]
                entry: Dict[str, Any] = {
                    "id": gr["id"],
                    "name": r_name,
                    "url": gr["url"],
                    "branch": gr["branch"],
                    "commit_sha": gr["commit_sha"],
                    "provider": gr["provider"],
                    "status": gr["status"],
                    "last_synced": gr["last_synced"],
                    "files": repo_file_counts.get(r_name, 0),
                    "symbols": repo_symbol_counts.get(r_name, 0),
                }
                if want_files:
                    entry.update(_build_source_file_slice(per_repo_paths.get(r_name, []), safe_offset, safe_limit))
                git_out.append(entry)
            result["git_repositories"] = git_out

        if st in ("all", "monitored_path"):
            filtered_paths = [p for p in indexed_paths if not repo_name or p["repo"] == repo_name]
            mon_out = []
            for p in filtered_paths:
                r_name = p["repo"]
                entry = {
                    "repo": r_name,
                    "path": p["path"],
                    "category": p["category"],
                    "files": repo_file_counts.get(r_name, 0),
                }
                if want_files:
                    entry.update(_build_source_file_slice(per_repo_paths.get(r_name, []), safe_offset, safe_limit))
                mon_out.append(entry)
            result["monitored_paths"] = mon_out

        if st in ("all", "local_storage"):
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
                ls_slice = _build_source_file_slice(ls_paths, safe_offset, safe_limit)
                ls_entry.update(ls_slice)
                ls_entry["files"] = ls_slice["file_paths"]
            result["local_storage"] = ls_entry

        if want_files:
            total_files = len(formatted_all_files)
            has_more = (safe_offset + safe_limit) < total_files
            result["total_files"] = total_files
            result["offset"] = safe_offset
            result["limit"] = safe_limit
            result["has_more"] = has_more
            result["next_offset"] = (safe_offset + safe_limit) if has_more else None
            result["files"] = formatted_all_files[safe_offset : safe_offset + safe_limit]

        return json.dumps(result, default=str)
    except ForbiddenError as e:
        logger.warning(f"Forbidden error retrieving ingestion catalog: {e}")
        return json.dumps({"error": f"Forbidden: {str(e)}", "forbidden": True})
    except Exception as e:
        logger.error(f"Error retrieving ingestion catalog: {e}")
        return json.dumps({"error": f"Error retrieving ingestion catalog: {str(e)}"})
