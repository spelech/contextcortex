import app.services.database as db_service
import app.services.vector_store as vs_service
import app.services.indexing.state as idx_state
import app.services.indexing.processor as proc_service
import os
import json
import logging
from typing import List, Dict, Any
from app.services.database import *
from app.services.chunking import *
from app.services.embeddings import *
import app.services.vector_store as vs_service
from app.services.indexing.state import (
    VAULT_PATH, CHUNK_SIZE, CHUNK_OVERLAP,
    trigger_list_changed_notification, ensure_collection
)
from app.services.indexing.processor import (
    process_file_content, get_chunk_uuid, extract_keywords_from_text, get_dynamic_catalog_description
)

logger = logging.getLogger('contextcortex.indexer')
import sys

def _get_indexer_attr(name, default):
    mod = sys.modules.get("app.services.indexer")
    return getattr(mod, name, default) if mod else default


def sync_local_paths():
    """Scans and indexes mounted local paths and notes vaults."""
    logger.info("Scanning local paths...")
    active_paths = []
    with db_service.get_db_connection() as conn:
        rows = conn.execute("SELECT path, type, recursive, category, repo FROM indexed_paths WHERE enabled = 1").fetchall()
        for r in rows:
            active_paths.append({
                "path": r["path"],
                "type": r["type"],
                "recursive": bool(r["recursive"]),
                "category": r["category"],
                "repo": r["repo"] or "local"
            })

    vault_p = idx_state.VAULT_PATH
    if not active_paths and os.path.exists(vault_p):
        active_paths.append({
            "path": vault_p,
            "type": "directory",
            "recursive": True,
            "category": "vault",
            "repo": "vault"
        })

    found_files = {} # abs_path -> (repo, category, base_dir)
    supported_extensions = (
        ".md", ".txt", ".yaml", ".yml", ".json", ".py", ".js", ".jsx", 
        ".ts", ".tsx", ".go", ".rs", ".cs", ".cpp", ".c", ".h", ".java", 
        ".rb", ".php", ".sh", ".sql", ".html", ".css"
    )

    for target in active_paths:
        tpath = os.path.abspath(target["path"])
        if not os.path.exists(tpath):
            continue

        if target["type"] == "file":
            if tpath.endswith(supported_extensions):
                found_files[tpath] = (target["repo"], target["category"], os.path.dirname(tpath))
        else:
            base_dir = tpath
            if target["recursive"]:
                for root, dirs, files in os.walk(tpath):
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "vendor", "__pycache__", "venv", ".git")]
                    for file in files:
                        if not file.startswith(".") and file.endswith(supported_extensions):
                            full = os.path.abspath(os.path.join(root, file))
                            found_files[full] = (target["repo"], target["category"], base_dir)
            else:
                try:
                    for entry in os.scandir(tpath):
                        if not entry.name.startswith(".") and entry.is_file() and entry.name.endswith(supported_extensions):
                            found_files[os.path.abspath(entry.path)] = (target["repo"], target["category"], base_dir)
                except Exception:
                    pass

    all_points = []
    all_symbols = []
    all_routes = []
    all_calls = []
    all_summaries = []
    all_relationships = []
    files_to_update_cache = []
    files_to_delete = []

    for filepath, (repo, category, base_dir) in found_files.items():
        try:
            mtime = os.path.getmtime(filepath)
            with db_service.get_db_connection() as conn:
                cached = conn.execute("SELECT mtime FROM indexed_files WHERE filepath = ?", (filepath,)).fetchone()
            
            if cached and abs(cached["mtime"] - mtime) < 0.01:
                continue # Cached & unchanged

            rel_path = os.path.relpath(filepath, base_dir)
            doc_type = "code" if is_code_file(filepath) else "doc"
            lang = detect_language(filepath)

            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            points, symbols, summary_tuple, rels, routes, calls = proc_service.process_file_content(
                filepath=filepath,
                rel_path=rel_path,
                content=content,
                repo=repo,
                doc_type=doc_type,
                category_override=category
            )

            files_to_delete.append((filepath, repo))
            all_points.extend(points)
            all_symbols.extend(symbols)
            all_routes.extend(routes)
            all_calls.extend(calls)
            all_summaries.append(summary_tuple)
            all_relationships.extend(rels)
            files_to_update_cache.append((filepath, repo, doc_type, lang, None, mtime))
        except Exception as e:
            logger.error(f"Error processing local file {filepath}: {e}")

    # Purge old points for modified files
    store = vs_service.get_vector_store()
    for (fpath, repo) in files_to_delete:
        try:
            store.delete_by_path(fpath)
            with db_service.get_db_connection() as conn:
                conn.execute("DELETE FROM ast_symbols WHERE filepath = ?", (fpath,))
                conn.execute("DELETE FROM ast_relationships WHERE source_filepath = ?", (fpath,))
                conn.execute("DELETE FROM api_routes WHERE filepath = ?", (fpath,))
                conn.execute("DELETE FROM api_client_calls WHERE filepath = ?", (fpath,))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to delete old points for {fpath}: {e}")

    # Bulk upsert to vector store
    if all_points:
        logger.info(f"Upserting {len(all_points)} vector documents to vector store...")
        try:
            upsert_ok = store.upsert_documents(all_points)
            if not upsert_ok:
                logger.error("Failed to upsert points to vector store during local indexing.")
                return False
        except Exception as e:
            logger.error(f"Failed to upsert points to vector store: {e}")
            return False

    # Batch update SQLite tables
    try:
        with db_service.get_db_connection() as conn:
            if files_to_update_cache:
                conn.executemany(
                    "INSERT OR REPLACE INTO indexed_files (filepath, repo, doc_type, language, commit_sha, mtime) VALUES (?, ?, ?, ?, ?, ?)",
                    files_to_update_cache
                )
            if all_summaries:
                conn.executemany(
                    "INSERT OR REPLACE INTO file_summaries (filepath, repo, title, folder, category, tags, headings, keywords, mtime) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    all_summaries
                )
            if all_symbols:
                for s in all_symbols:
                    cursor = conn.execute(
                        "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (s["repo"], s["filepath"], s["name"], s["full_symbol"], s["kind"], s["start_line"], s["end_line"], s["signature"], s["language"])
                    )
                    s["inserted_id"] = cursor.lastrowid

            if all_relationships:
                # Map symbol (repo, filepath, name) to inserted_id
                sym_map = {}
                for s in all_symbols:
                    if "inserted_id" in s:
                        sym_map[(s["repo"], s["filepath"], s["name"])] = s["inserted_id"]

                rel_tuples = []
                for r in all_relationships:
                    src_id = sym_map.get((r["repo"], r["source_filepath"], r["source_symbol"]))
                    rel_tuples.append((
                        r["repo"],
                        src_id,
                        r["source_filepath"],
                        r["source_symbol"],
                        r["target_symbol"],
                        r["relationship_type"],
                        r["line_number"]
                    ))

                conn.executemany(
                    """INSERT INTO ast_relationships
                       (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    rel_tuples
                )
            if all_routes:
                route_tuples = [
                    (r["repo"], r["filepath"], r["framework"], r["http_method"], r["path_pattern"], r.get("handler_symbol"), r["start_line"], r["end_line"])
                    for r in all_routes
                ]
                conn.executemany(
                    "INSERT INTO api_routes (repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    route_tuples
                )
            if all_calls:
                call_tuples = [
                    (c["repo"], c["filepath"], c.get("http_method"), c["url_pattern"], c.get("caller_symbol"), c["line_number"])
                    for c in all_calls
                ]
                conn.executemany(
                    "INSERT INTO api_client_calls (repo, filepath, http_method, url_pattern, caller_symbol, line_number) VALUES (?, ?, ?, ?, ?, ?)",
                    call_tuples
                )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed writing local index updates to SQLite: {e}")
        return False

    return True

