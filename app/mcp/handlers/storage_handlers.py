import os
import json
import logging
import sys
from typing import Optional, Annotated
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
    return filepath.split("://", 1)[1] if "://" in filepath else filepath


async def handle_manage_local_file(
    action: Annotated[str, Field(description="Action to perform: 'upload', 'replace', 'delete', 'read', or 'preview'")],
    file_path: Annotated[str, Field(description="Relative path of file in local storage (e.g. 'docs/spec.md')")],
    content: Annotated[Optional[str], Field(description="Content to write for upload or replace actions")] = None,
    repo: Annotated[str, Field(description="Repository or namespace tag (default: 'local_storage')")] = "local_storage",
    category: Annotated[Optional[str], Field(description="Category tag for document")] = None
) -> str:
    """Manage files in ContextCortex local storage: upload, replace, read, preview, or delete files with immediate vector indexing."""
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
        elif act == "delete":
            storage.delete_file(file_path, repo=repo)
            return json.dumps({
                "action": "delete",
                "status": "success",
                "file": _strip_repo_prefix(file_path),
                "repo": repo,
            })
        elif act == "read":
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
        elif act == "preview":
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
            else:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    text_content = f.read()
                line_count = len(text_content.splitlines())
                char_count = len(text_content)
                preview_sample = text_content[:1000]
                return json.dumps({
                    "action": "preview",
                    "file": _strip_repo_prefix(file_path),
                    "is_pdf": False,
                    "line_count": line_count,
                    "character_count": char_count,
                    "preview": preview_sample,
                })
        else:
            return json.dumps({"error": f"Unsupported action '{action}'. Valid actions are 'upload', 'replace', 'delete', 'read', 'preview'."})
    except ForbiddenError as e:
        logger.warning(f"Forbidden error executing manage_local_file ({action}): {e}")
        return json.dumps({"error": f"Forbidden: {str(e)}", "forbidden": True})
    except Exception as e:
        logger.error(f"Error executing manage_local_file ({action}): {e}")
        return json.dumps({"error": f"Error executing manage_local_file: {str(e)}"})


async def handle_what_is_ingested(
    source_type: Annotated[str, Field(description="Filter source type: 'all', 'git', 'monitored_path', or 'local_storage'")] = "all",
    repo_name: Annotated[Optional[str], Field(description="Filter by repository or namespace name")] = None,
    path_prefix: Annotated[Optional[str], Field(description="Filter files matching path prefix")] = None,
    file_extension: Annotated[Optional[str], Field(description="Filter by file extension (e.g. '.md', '.py')")] = None,
    detail_level: Annotated[str, Field(description="Granularity: 'summary' or 'detailed'")] = "summary"
) -> str:
    """Inspect all ingested Git repositories, monitored local paths, and uploaded local storage files with optional filtering and detailed file trees."""
    try:
        enforce_tool_permission(Role.VIEWER)
        st = (source_type or "all").strip().lower()
        detail = (detail_level or "summary").strip().lower()

        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            git_repos = conn.execute("SELECT id, name, url, branch, commit_sha, provider, status, last_synced FROM git_repositories").fetchall()
            indexed_paths = conn.execute("SELECT path, repo, category FROM indexed_paths WHERE enabled = 1").fetchall()
            
            f_counts = conn.execute("SELECT repo, count(*) as cnt FROM indexed_files GROUP BY repo").fetchall()
            repo_file_counts = {r["repo"]: r["cnt"] for r in f_counts}

            s_counts = conn.execute("SELECT repo, count(*) as cnt FROM ast_symbols GROUP BY repo").fetchall()
            repo_symbol_counts = {s["repo"]: s["cnt"] for s in s_counts}

            detailed_files = []
            if detail == "detailed":
                query = "SELECT filepath, repo, doc_type, language, mtime FROM indexed_files WHERE 1=1"
                params = []
                if repo_name:
                    query += " AND repo = ?"
                    params.append(repo_name)
                if path_prefix:
                    query += " AND filepath LIKE ?"
                    params.append(f"%{path_prefix}%")
                if file_extension:
                    query += " AND filepath LIKE ?"
                    params.append(f"%{file_extension}")
                query += " ORDER BY repo, filepath LIMIT 200"
                detailed_files = conn.execute(query, params).fetchall()

        result: Dict[str, Any] = {
            "source_type": st,
            "detail_level": detail,
        }

        if st in ("all", "git"):
            filtered_repos = [r for r in git_repos if not repo_name or r["name"] == repo_name]
            result["git_repositories"] = [
                {
                    "id": gr["id"],
                    "name": gr["name"],
                    "url": gr["url"],
                    "branch": gr["branch"],
                    "commit_sha": gr["commit_sha"],
                    "provider": gr["provider"],
                    "status": gr["status"],
                    "last_synced": gr["last_synced"],
                    "files": repo_file_counts.get(gr["name"], 0),
                    "symbols": repo_symbol_counts.get(gr["name"], 0),
                }
                for gr in filtered_repos
            ]

        if st in ("all", "monitored_path"):
            filtered_paths = [p for p in indexed_paths if not repo_name or p["repo"] == repo_name]
            result["monitored_paths"] = [
                {
                    "repo": p["repo"],
                    "path": p["path"],
                    "category": p["category"],
                    "files": repo_file_counts.get(p["repo"], 0),
                }
                for p in filtered_paths
            ]

        if st in ("all", "local_storage"):
            storage = _get_tools_attr("get_local_storage_service", get_local_storage_service)()
            tree = storage.get_file_tree(subfolder=path_prefix if path_prefix and not path_prefix.startswith("/") else None)
            total_ls_files = repo_file_counts.get("local_storage", len(tree.get("files", [])))
            result["local_storage"] = {
                "root_path": storage.get_storage_root(),
                "total_files": total_ls_files,
                "directories": [d["name"] for d in tree.get("directories", [])],
            }

        if detail == "detailed":
            result["files"] = [
                {
                    "repo": df["repo"],
                    "file": _strip_repo_prefix(df["filepath"]),
                    "doc_type": df["doc_type"],
                    "language": df["language"],
                }
                for df in detailed_files
            ]

        return json.dumps(result)
    except ForbiddenError as e:
        logger.warning(f"Forbidden error retrieving ingestion catalog: {e}")
        return json.dumps({"error": f"Forbidden: {str(e)}", "forbidden": True})
    except Exception as e:
        logger.error(f"Error retrieving ingestion catalog: {e}")
        return json.dumps({"error": f"Error retrieving ingestion catalog: {str(e)}"})
