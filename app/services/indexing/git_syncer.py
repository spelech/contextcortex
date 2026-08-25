import app.services.indexing.local_syncer as local_syncer
import app.services.indexing.state as idx_state
import app.services.indexing.processor as proc_service
import os
import json
import logging
import sys
from typing import List, Dict, Any
import app.services.database as db_service
from app.services.database import *
from app.services.chunking import *
from app.services.embeddings import *
import app.services.git_manager as gm_service
from app.services.git_manager import *
import app.services.vector_store as vs_service
from app.services.vector_store import VectorStoreManager
from app.services.indexing.state import (
    VAULT_PATH, CHUNK_SIZE, CHUNK_OVERLAP,
    indexing_lock, is_indexing,
    trigger_list_changed_notification, ensure_collection
)
from app.services.indexing.processor import (
    process_file_content, get_chunk_uuid, extract_keywords_from_text, get_dynamic_catalog_description
)
from app.services.indexing.local_syncer import sync_local_paths

logger = logging.getLogger('contextcortex.indexer')
import sys

def _get_indexer_attr(name, default):
    mod = sys.modules.get("app.services.indexer")
    return getattr(mod, name, default) if mod else default


def sync_single_git_repo(repo_id: int):
    """Ephemeral shallow clone, AST parse, hybrid vector upsert, and immediate disk cleanup."""
    with db_service.get_db_connection() as conn:
        repo_row = conn.execute("SELECT * FROM git_repositories WHERE id = ?", (repo_id,)).fetchone()
    if not repo_row:
        return

    repo_name = repo_row["name"]
    git_url = repo_row["url"]
    branch = repo_row["branch"] or "main"
    per_repo_token = repo_row["auth_token"]
    per_repo_user = repo_row["auth_user"] if "auth_user" in repo_row.keys() else None
    provider = repo_row["provider"] if "provider" in repo_row.keys() else None

    effective_token, effective_user, token_source = db_service.get_effective_git_token(
        git_url, 
        override_token=per_repo_token, 
        override_user=per_repo_user, 
        provider=provider
    )

    logger.info(f"Checking remote status for Git repo '{repo_name}' ({git_url}, provider: {provider or 'auto'}, auth: {token_source})...")
    remote_sha = gm_service.get_remote_head_sha(git_url, branch, token=effective_token, username=effective_user, provider=provider)
    if remote_sha and repo_row["commit_sha"] == remote_sha:
        logger.info(f"Repo '{repo_name}' already up-to-date at commit {remote_sha[:8]}. Skipping clone.")
        with db_service.get_db_connection() as conn:
            conn.execute("UPDATE git_repositories SET status = 'synced', last_synced = CURRENT_TIMESTAMP WHERE id = ?", (repo_id,))
            conn.commit()
        return

    # Update status to syncing
    with db_service.get_db_connection() as conn:
        conn.execute("UPDATE git_repositories SET status = 'syncing' WHERE id = ?", (repo_id,))
        conn.commit()

    temp_dir = None
    try:
        clone_res = gm_service.shallow_clone_repo(
            git_url, 
            branch, 
            token=effective_token, 
            username=effective_user, 
            provider=provider, 
            repo_id=str(repo_id)
        )
        temp_dir = clone_res.temp_dir
        commit_sha = clone_res.commit_sha
        err = clone_res.error
        
        if err or not temp_dir:
            logger.error(f"Failed to clone repo '{repo_name}': {err}")
            with db_service.get_db_connection() as conn:
                conn.execute("UPDATE git_repositories SET status = 'error', last_error = ? WHERE id = ?", (err or "Unknown clone error", repo_id))
                conn.commit()
            return

        supported_extensions = (
            ".md", ".txt", ".yaml", ".yml", ".json", ".py", ".js", ".jsx", 
            ".ts", ".tsx", ".go", ".rs", ".cs", ".cpp", ".c", ".h", ".java", 
            ".rb", ".php", ".sh", ".sql", ".html", ".css"
        )

        all_points = []
        all_symbols = []
        all_routes = []
        all_calls = []
        all_summaries = []
        all_relationships = []
        indexed_files = []

        for root, dirs, files in os.walk(temp_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "vendor", "__pycache__", "venv", ".git", "dist", "build")]
            for file in files:
                if file.startswith(".") or not file.endswith(supported_extensions):
                    continue
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, temp_dir)
                doc_type = "code" if is_code_file(full_path) else "doc"
                lang = detect_language(full_path)

                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()

                    # Filepath recorded in DB is repo:rel_path
                    db_filepath = f"{repo_name}://{rel_path}"

                    points, symbols, summary_tuple, rels, routes, calls = proc_service.process_file_content(
                        filepath=db_filepath,
                        rel_path=rel_path,
                        content=content,
                        repo=repo_name,
                        doc_type=doc_type,
                        git_url=git_url,
                        commit_sha=commit_sha,
                        provider=provider
                    )
                    all_points.extend(points)
                    all_symbols.extend(symbols)
                    all_routes.extend(routes)
                    all_calls.extend(calls)
                    all_summaries.append(summary_tuple)
                    all_relationships.extend(rels)
                    indexed_files.append((db_filepath, repo_name, doc_type, lang, commit_sha, 0.0))
                except Exception as fe:
                    logger.error(f"Error parsing file {rel_path} in repo '{repo_name}': {fe}")

        # Purge previous vectors for this repo in vector store
        store = vs_service.get_vector_store()
        try:
            store.delete_by_repo(repo_name)
        except Exception as qe:
            logger.error(f"Error purging old vectors for repo '{repo_name}': {qe}")

        # Bulk upsert new points to vector store
        if all_points:
            logger.info(f"Upserting {len(all_points)} vectors for repo '{repo_name}'...")
            upsert_ok = store.upsert_documents(all_points)
            if not upsert_ok:
                raise RuntimeError(f"Failed to upsert {len(all_points)} documents into vector store for repo '{repo_name}'")

        # Update SQLite
        with db_service.get_db_connection() as conn:
            conn.execute("DELETE FROM indexed_files WHERE repo = ?", (repo_name,))
            conn.execute("DELETE FROM file_summaries WHERE repo = ?", (repo_name,))
            conn.execute("DELETE FROM ast_relationships WHERE repo = ?", (repo_name,))
            conn.execute("DELETE FROM ast_symbols WHERE repo = ?", (repo_name,))
            conn.execute("DELETE FROM api_routes WHERE repo = ?", (repo_name,))
            conn.execute("DELETE FROM api_client_calls WHERE repo = ?", (repo_name,))

            if indexed_files:
                conn.executemany(
                    "INSERT INTO indexed_files (filepath, repo, doc_type, language, commit_sha, mtime) VALUES (?, ?, ?, ?, ?, ?)",
                    indexed_files
                )
            if all_summaries:
                conn.executemany(
                    "INSERT INTO file_summaries (filepath, repo, title, folder, category, tags, headings, keywords, mtime) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
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

            conn.execute(
                "UPDATE git_repositories SET status = 'synced', last_error = NULL, commit_sha = ?, last_synced = CURRENT_TIMESTAMP WHERE id = ?",
                (commit_sha, repo_id)
            )
            conn.commit()

        logger.info(f"Successfully synced repo '{repo_name}' (@ {commit_sha[:8] if commit_sha else 'head'}). Vectors: {len(all_points)}, Symbols: {len(all_symbols)}")
        idx_state.trigger_list_changed_notification()

    except Exception as e:
        logger.error(f"Unexpected error during repo sync for '{repo_name}': {e}")
        try:
            with db_service.get_db_connection() as conn:
                conn.execute("UPDATE git_repositories SET status = 'error', last_error = ? WHERE id = ?", (str(e), repo_id))
                conn.commit()
        except Exception:
            pass
    finally:
        # Crucial: Ephemeral disk cleanup!
        gm_service.cleanup_repo_dir(temp_dir)

def run_full_indexing():
    global is_indexing
    if not indexing_lock.acquire(blocking=False):
        logger.warning("Indexing already running. Skipping duplicate call.")
        return False
    is_indexing = True
    try:
        idx_state.ensure_collection()
        local_syncer.sync_local_paths()
        
        # Sync all registered git repos
        with db_service.get_db_connection() as conn:
            git_repos = conn.execute("SELECT id FROM git_repositories WHERE enabled = 1").fetchall()
        for gr in git_repos:
            sync_single_git_repo(gr["id"])

        import datetime
        set_metadata("last_indexed", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        idx_state.trigger_list_changed_notification()
        return True
    except Exception as e:
        logger.error(f"Error during full indexing: {e}")
        return False
    finally:
        is_indexing = False
        indexing_lock.release()

# Register re-index callback with VectorStoreManager
VectorStoreManager.register_reindex_callback(run_full_indexing)



