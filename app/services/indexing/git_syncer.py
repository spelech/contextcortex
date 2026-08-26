import os
import json
import logging
import gc
import sys
import hashlib
from typing import List, Dict, Any, Tuple, Optional

import app.services.indexing.local_syncer as local_syncer
import app.services.indexing.state as idx_state
import app.services.indexing.processor as proc_service
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
    process_file_content, get_chunk_uuid, extract_keywords_from_text, get_dynamic_catalog_description,
    compute_text_hash
)
from app.services.indexing.local_syncer import sync_local_paths

logger = logging.getLogger('contextcortex.indexer')

DEFAULT_SUPPORTED_EXTENSIONS = (
    ".md", ".txt", ".yaml", ".yml", ".json", ".py", ".js", ".jsx", 
    ".ts", ".tsx", ".go", ".rs", ".cs", ".cpp", ".c", ".h", ".java", 
    ".rb", ".php", ".sh", ".sql", ".html", ".css"
)


def compute_git_repo_delta(
    temp_dir: str, 
    repo_name: str, 
    supported_extensions: Optional[Tuple[str, ...]] = None
) -> Tuple[List[str], List[str], List[str], List[str]]:
    """
    Computes delta between local cloned repository and indexed_files table in DB.
    Returns: (added_files, modified_files, deleted_filepaths, unchanged_files)
      - added_files: List of full file paths on disk that do not exist in DB
      - modified_files: List of full file paths on disk whose content SHA256 hash != DB hash
      - deleted_filepaths: List of db_filepath strings ('repo://rel_path') in DB that no longer exist on disk
      - unchanged_files: List of full file paths on disk whose content SHA256 hash == DB hash
    """
    exts = supported_extensions if supported_extensions is not None else DEFAULT_SUPPORTED_EXTENSIONS
    
    with db_service.get_db_connection() as conn:
        rows = conn.execute("SELECT filepath, hash FROM indexed_files WHERE repo = ?", (repo_name,)).fetchall()
        db_files = {r["filepath"]: r["hash"] for r in rows}
    
    found_filepaths = set()
    added_files = []
    modified_files = []
    unchanged_files = []

    for root, dirs, files in os.walk(temp_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "vendor", "__pycache__", "venv", ".git", "dist", "build")]
        for file in files:
            if not file.startswith(".") and file.endswith(exts):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, temp_dir)
                db_filepath = f"{repo_name}://{rel_path}"
                found_filepaths.add(db_filepath)
                
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    file_hash = proc_service.compute_text_hash(content)
                except Exception as e:
                    logger.warning(f"Failed to read/hash file {full_path}: {e}")
                    continue

                if db_filepath not in db_files:
                    added_files.append(full_path)
                elif db_files[db_filepath] != file_hash:
                    modified_files.append(full_path)
                else:
                    unchanged_files.append(full_path)

    deleted_filepaths = [fp for fp in db_files.keys() if fp not in found_filepaths]

    return added_files, modified_files, deleted_filepaths, unchanged_files


def sync_single_git_repo(repo_id: int):
    """Ephemeral shallow clone, delta calculation, incremental vector upsert, and immediate disk cleanup."""
    repo_name = f"repo-{repo_id}"
    temp_dir = None
    try:
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

        added_files, modified_files, deleted_filepaths, unchanged_files = compute_git_repo_delta(temp_dir, repo_name)
        total_delta = len(added_files) + len(modified_files) + len(deleted_filepaths)
        logger.info(
            f"Git delta computed for '{repo_name}': {len(added_files)} added, "
            f"{len(modified_files)} modified, {len(deleted_filepaths)} deleted, {len(unchanged_files)} unchanged"
        )

        if total_delta == 0:
            logger.info(f"Repo '{repo_name}' delta is empty (all {len(unchanged_files)} files unchanged). Updating commit SHA.")
            with db_service.get_db_connection() as conn:
                conn.execute(
                    "UPDATE git_repositories SET status = 'synced', last_error = NULL, commit_sha = ?, last_synced = CURRENT_TIMESTAMP WHERE id = ?",
                    (commit_sha, repo_id)
                )
                conn.commit()
            idx_state.trigger_list_changed_notification()
            return

        # Delete old vector points & SQLite rows ONLY for modified and deleted files
        store = vs_service.get_vector_store()
        modified_db_filepaths = [f"{repo_name}://{os.path.relpath(f, temp_dir)}" for f in modified_files]
        paths_to_delete = modified_db_filepaths + deleted_filepaths

        for fpath in paths_to_delete:
            try:
                store.delete_by_path(fpath)
            except Exception as qe:
                logger.error(f"Error deleting vector for {fpath}: {qe}")

        if paths_to_delete:
            with db_service.get_db_connection() as conn:
                for fpath in paths_to_delete:
                    conn.execute("DELETE FROM ast_symbols WHERE filepath = ?", (fpath,))
                    conn.execute("DELETE FROM ast_relationships WHERE source_filepath = ?", (fpath,))
                    conn.execute("DELETE FROM api_routes WHERE filepath = ?", (fpath,))
                    conn.execute("DELETE FROM api_client_calls WHERE filepath = ?", (fpath,))
                    conn.execute("DELETE FROM file_summaries WHERE filepath = ?", (fpath,))
                for fpath in deleted_filepaths:
                    conn.execute("DELETE FROM indexed_files WHERE filepath = ?", (fpath,))
                conn.commit()

        # Ingest added and modified files in batches
        files_to_sync = added_files + modified_files
        total_files = len(files_to_sync)
        logger.info(f"Ingesting {total_files} added/modified files for repo '{repo_name}'...")

        BATCH_SIZE = 25
        batch_points = []
        batch_symbols = []
        batch_routes = []
        batch_calls = []
        batch_summaries = []
        batch_relationships = []
        batch_indexed_files = []
        total_vectors_count = 0
        total_symbols_count = 0

        for idx, full_path in enumerate(files_to_sync):
            rel_path = os.path.relpath(full_path, temp_dir)
            doc_type = "code" if is_code_file(full_path) else "doc"
            lang = detect_language(full_path)
            db_filepath = f"{repo_name}://{rel_path}"

            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                file_hash = proc_service.compute_text_hash(content)

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
                batch_points.extend(points)
                batch_symbols.extend(symbols)
                batch_routes.extend(routes)
                batch_calls.extend(calls)
                batch_summaries.append(summary_tuple)
                batch_relationships.extend(rels)
                batch_indexed_files.append((db_filepath, repo_name, doc_type, lang, commit_sha, 0.0, file_hash))

                if (idx + 1) % 10 == 0 or (idx + 1) == total_files:
                    pct = int(((idx + 1) / total_files) * 100)
                    logger.info(f"[{idx+1}/{total_files}] ({pct}%) Ingesting {rel_path} (+{len(points)} chunks, +{len(symbols)} symbols)")

            except Exception as fe:
                logger.error(f"Error parsing file {rel_path} in repo '{repo_name}': {fe}")

            # Flush batch every BATCH_SIZE files or on the last file
            if (idx + 1) % BATCH_SIZE == 0 or (idx + 1) == total_files:
                if batch_points:
                    upsert_ok = store.upsert_documents(batch_points)
                    if not upsert_ok:
                        logger.error(f"Failed to upsert points to vector store during git indexing for repo '{repo_name}'.")
                        raise RuntimeError(f"Vector store upsert failed during git indexing for repo '{repo_name}'")
                    total_vectors_count += len(batch_points)
                    batch_points.clear()

                with db_service.get_db_connection() as conn:
                    if batch_indexed_files:
                        conn.executemany(
                            "INSERT OR REPLACE INTO indexed_files (filepath, repo, doc_type, language, commit_sha, mtime, hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            batch_indexed_files
                        )
                        batch_indexed_files.clear()
                    if batch_summaries:
                        conn.executemany(
                            "INSERT OR REPLACE INTO file_summaries (filepath, repo, title, folder, category, tags, headings, keywords, mtime) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            batch_summaries
                        )
                        batch_summaries.clear()
                    if batch_symbols:
                        for s in batch_symbols:
                            cursor = conn.execute(
                                "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (s["repo"], s["filepath"], s["name"], s["full_symbol"], s["kind"], s["start_line"], s["end_line"], s["signature"], s["language"])
                            )
                            s["inserted_id"] = cursor.lastrowid
                        total_symbols_count += len(batch_symbols)
                    if batch_relationships:
                        sym_map = {}
                        for s in batch_symbols:
                            if "inserted_id" in s:
                                sym_map[(s["repo"], s["filepath"], s["name"])] = s["inserted_id"]

                        rel_tuples = []
                        for r in batch_relationships:
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
                        batch_relationships.clear()
                    if batch_routes:
                        route_tuples = [
                            (r["repo"], r["filepath"], r["framework"], r["http_method"], r["path_pattern"], r.get("handler_symbol"), r["start_line"], r["end_line"])
                            for r in batch_routes
                        ]
                        conn.executemany(
                            "INSERT INTO api_routes (repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            route_tuples
                        )
                        batch_routes.clear()
                    if batch_calls:
                        call_tuples = [
                            (c["repo"], c["filepath"], c.get("http_method"), c["url_pattern"], c.get("caller_symbol"), c["line_number"])
                            for c in batch_calls
                        ]
                        conn.executemany(
                            "INSERT INTO api_client_calls (repo, filepath, http_method, url_pattern, caller_symbol, line_number) VALUES (?, ?, ?, ?, ?, ?)",
                            call_tuples
                        )
                        batch_calls.clear()
                    batch_symbols.clear()
                    conn.commit()

                gc.collect()

        with db_service.get_db_connection() as conn:
            conn.execute(
                "UPDATE git_repositories SET status = 'synced', last_error = NULL, commit_sha = ?, last_synced = CURRENT_TIMESTAMP WHERE id = ?",
                (commit_sha, repo_id)
            )
            conn.commit()

        logger.info(f"Successfully synced repo '{repo_name}' (@ {commit_sha[:8] if commit_sha else 'head'}). Delta: +{len(added_files)} ~{len(modified_files)} -{len(deleted_filepaths)}. Vectors: {total_vectors_count}, Symbols: {total_symbols_count}")
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
