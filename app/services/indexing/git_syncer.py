import logging
import os
import threading
import time
from typing import Dict, Tuple

_repo_sync_locks: Dict[Tuple[str, int], threading.Lock] = {}
_repo_sync_locks_guard = threading.Lock()


def _get_repo_lock(repo_id: int) -> threading.Lock:
    try:
        from app.services.database.engine import get_db_url
        db_key = get_db_url()
    except Exception:
        db_key = "default"
    key = (db_key, repo_id)
    with _repo_sync_locks_guard:
        if key not in _repo_sync_locks:
            _repo_sync_locks[key] = threading.Lock()
        return _repo_sync_locks[key]


import app.services.database as db_service
import app.services.git_manager as gm_service
import app.services.indexing.local_syncer as local_syncer
import app.services.indexing.processor as proc_service
import app.services.indexing.state as idx_state
import app.services.vector_store as vs_service
from app.services.text_decoding import read_source_text
from app.services.chunking import *
from app.services.database import *
from app.services.embeddings import *
from app.services.git_manager import *
from app.services.indexing.git_delta_scanner import (
    DEFAULT_SUPPORTED_EXTENSIONS,
    _BUNDLED_REL_PREFIXES,
    _IGNORED_DIR_NAMES,
    _should_skip_indexed_file,
    compute_git_repo_delta,
    persist_recent_commits,
    persist_sync_batch,
)
from app.services.indexing.git_progress import progress_tracker
from app.services.indexing.local_syncer import sync_local_paths
from app.services.indexing.processor import (
    compute_text_hash,
    extract_keywords_from_text,
    get_chunk_uuid,
    get_dynamic_catalog_description,
    process_file_content,
)
from app.services.indexing.state import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    VAULT_PATH,
    ensure_collection,
    indexing_lock,
    is_indexing,
    trigger_list_changed_notification,
)
from app.services.memory_utils import trim_memory
from app.services.vector_store import VectorStoreManager

logger = logging.getLogger("contextcortex.indexer")


def sync_single_git_repo(repo_id: int, force: bool = False):
    """Ephemeral shallow clone, delta calculation, incremental vector upsert, and immediate disk cleanup."""
    repo_lock = _get_repo_lock(repo_id)
    if not repo_lock.acquire(blocking=False):
        logger.info(f"Sync already in progress for repo_id={repo_id}; skipping overlapping call.")
        return

    repo_name = f"repo-{repo_id}"
    temp_dir = None
    keep_shallow = False
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
        raw_provider = repo_row["provider"] if "provider" in repo_row.keys() else None
        provider = gm_service.detect_git_provider(git_url, raw_provider)
        keep_shallow = bool(repo_row["keep_shallow"]) if "keep_shallow" in repo_row.keys() and repo_row["keep_shallow"] else False
        retain_commits_count = int(repo_row["retain_commits_count"]) if "retain_commits_count" in repo_row.keys() and repo_row["retain_commits_count"] is not None else 20
        prev_status = repo_row["status"] if "status" in repo_row.keys() else None

        progress_tracker.get_or_create_job(repo_id, repo_name)

        effective_token, effective_user, token_source = db_service.get_effective_git_token(
            git_url,
            override_token=per_repo_token,
            override_user=per_repo_user,
            provider=provider,
        )
        safe_url = gm_service.sanitize_url_for_logging(git_url)

        target_dir = gm_service.get_persistent_repo_dir(repo_name) if keep_shallow else None
        persistent_dir_valid = True
        if keep_shallow and target_dir:
            is_valid_fn = getattr(gm_service, "is_valid_git_repo", None)
            persistent_dir_valid = is_valid_fn(target_dir) if callable(is_valid_fn) else os.path.isdir(os.path.join(target_dir, ".git"))

        # Stage 1: Connecting & Remote Check
        progress_tracker.update_step(repo_id, 1, "Checking Remote Repository Ref", pct=10)
        progress_tracker.log(repo_id, "INFO", f"Checking remote ref for '{repo_name}' ({safe_url})...")
        logger.info(f"Checking remote status for Git repo '{repo_name}' ({git_url}, provider: {provider or 'auto'}, auth: {token_source})...")
        remote_sha = gm_service.get_remote_head_sha(git_url, branch, token=effective_token, username=effective_user, provider=provider)
        if (
            not force
            and prev_status != "error"
            and persistent_dir_valid
            and remote_sha
            and repo_row["commit_sha"] == remote_sha
        ):
            msg = f"Repo '{repo_name}' already up-to-date at commit {remote_sha[:8]}. Skipping clone."
            logger.info(msg)
            progress_tracker.log(repo_id, "INFO", msg)
            with db_service.get_db_connection() as conn:
                conn.execute("UPDATE git_repositories SET status = 'synced', last_synced = CURRENT_TIMESTAMP WHERE id = ?", (repo_id,))
                conn.commit()
            progress_tracker.finish_job(repo_id, "synced")
            return

        if progress_tracker.is_cancelled(repo_id):
            logger.info(f"Sync cancelled for repo '{repo_name}'")
            progress_tracker.log(repo_id, "WARN", "Sync cancelled by user")
            return

        # Stage 2: Shallow Cloning
        with db_service.get_db_connection() as conn:
            conn.execute("UPDATE git_repositories SET status = 'syncing' WHERE id = ?", (repo_id,))
            conn.commit()

        clone_mode_label = f"persistent storage ({target_dir})" if keep_shallow else "ephemeral directory"
        clone_depth = max(1, retain_commits_count) if retain_commits_count > 0 else 1
        progress_tracker.update_step(repo_id, 2, "Shallow Cloning Repository", pct=25)
        progress_tracker.log(repo_id, "INFO", f"Cloning branch '{branch}' (depth {clone_depth}) to {clone_mode_label}...")

        clone_start = time.time()
        clone_res = gm_service.shallow_clone_repo(
            git_url,
            branch,
            token=effective_token,
            username=effective_user,
            provider=provider,
            repo_id=str(repo_id),
            target_dir=target_dir,
            depth=clone_depth,
        )
        temp_dir = clone_res.temp_dir
        commit_sha = clone_res.commit_sha
        err = clone_res.error

        if err or not temp_dir:
            err_msg = f"Failed to clone repo '{repo_name}': {err}"
            logger.error(err_msg)
            progress_tracker.log(repo_id, "ERROR", err_msg)
            with db_service.get_db_connection() as conn:
                conn.execute("UPDATE git_repositories SET status = 'error', last_error = ? WHERE id = ?", (err or "Unknown clone error", repo_id))
                conn.commit()
            progress_tracker.finish_job(repo_id, "error", err or "Unknown clone error")
            return

        clone_duration = round(time.time() - clone_start, 2)
        progress_tracker.log(repo_id, "INFO", f"Cloned successfully in {clone_duration}s (@ {commit_sha[:8] if commit_sha else 'head'})")

        if progress_tracker.is_cancelled(repo_id):
            logger.info(f"Sync cancelled for repo '{repo_name}' after clone")
            progress_tracker.log(repo_id, "WARN", "Sync cancelled by user")
            return

        try:
            with db_service.get_db_connection() as conn:
                recent_commits = gm_service.extract_recent_commits(temp_dir, limit=retain_commits_count) if retain_commits_count > 0 else []
                persist_recent_commits(conn, repo_name, recent_commits, retain_commits_count)
        except Exception as ce:
            logger.error(f"Error extracting/pruning commits for repo '{repo_name}': {ce}")

        # Stage 3: Computing File Delta & Scanning
        progress_tracker.update_step(repo_id, 3, "Computing File Delta & Scanning", pct=40)
        try:
            added_files, modified_files, deleted_filepaths, unchanged_files = compute_git_repo_delta(temp_dir, repo_name, force=force)
        except TypeError:
            added_files, modified_files, deleted_filepaths, unchanged_files = compute_git_repo_delta(temp_dir, repo_name)
        total_delta = len(added_files) + len(modified_files) + len(deleted_filepaths)
        delta_msg = (
            f"Delta computed: +{len(added_files)} added, ~{len(modified_files)} modified, "
            f"-{len(deleted_filepaths)} deleted, {len(unchanged_files)} unchanged"
        )
        logger.info(
            f"Git delta computed for '{repo_name}': {len(added_files)} added, "
            f"{len(modified_files)} modified, {len(deleted_filepaths)} deleted, {len(unchanged_files)} unchanged"
        )
        progress_tracker.log(repo_id, "INFO", delta_msg)

        if total_delta == 0:
            msg = f"Repo '{repo_name}' delta is empty (all {len(unchanged_files)} files unchanged). Updating commit SHA."
            logger.info(msg)
            progress_tracker.log(repo_id, "INFO", msg)
            with db_service.get_db_connection() as conn:
                conn.execute(
                    "UPDATE git_repositories SET status = 'synced', last_error = NULL, commit_sha = ?, last_synced = CURRENT_TIMESTAMP WHERE id = ?",
                    (commit_sha, repo_id),
                )
                conn.commit()
            progress_tracker.finish_job(repo_id, "synced")
            idx_state.trigger_list_changed_notification()
            return

        if progress_tracker.is_cancelled(repo_id):
            logger.info(f"Sync cancelled for repo '{repo_name}' after delta scan")
            progress_tracker.log(repo_id, "WARN", "Sync cancelled by user")
            return

        store = vs_service.get_vector_store()
        added_db_filepaths = [f"{repo_name}://" + os.path.relpath(f, temp_dir).replace("\\", "/") for f in added_files]
        modified_db_filepaths = [f"{repo_name}://" + os.path.relpath(f, temp_dir).replace("\\", "/") for f in modified_files]
        paths_to_delete = modified_db_filepaths + deleted_filepaths
        db_paths_to_clean = list(dict.fromkeys(added_db_filepaths + modified_db_filepaths + deleted_filepaths))

        for fpath in paths_to_delete:
            try:
                store.delete_by_path(fpath)
            except Exception as qe:
                logger.error(f"Error deleting vector for {fpath}: {qe}")

        if db_paths_to_clean:
            with db_service.get_db_connection() as conn:
                for fpath in db_paths_to_clean:
                    conn.execute("DELETE FROM ast_symbols WHERE filepath = ?", (fpath,))
                    conn.execute("DELETE FROM ast_relationships WHERE source_filepath = ?", (fpath,))
                    conn.execute("DELETE FROM api_routes WHERE filepath = ?", (fpath,))
                    conn.execute("DELETE FROM api_client_calls WHERE filepath = ?", (fpath,))
                    conn.execute("DELETE FROM file_summaries WHERE filepath = ?", (fpath,))
                for fpath in deleted_filepaths:
                    conn.execute("DELETE FROM indexed_files WHERE filepath = ?", (fpath,))
                conn.commit()

        files_to_sync = added_files + modified_files
        total_files = len(files_to_sync)
        logger.info(f"Ingesting {total_files} added/modified files for repo '{repo_name}'...")
        progress_tracker.log(repo_id, "INFO", f"Ingesting {total_files} added/modified files...")

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

        # Stage 4: Parsing AST & Routes
        for idx, full_path in enumerate(files_to_sync):
            if progress_tracker.is_cancelled(repo_id):
                logger.info(f"Sync cancelled for repo '{repo_name}' during file ingestion at file {idx + 1}/{total_files}")
                progress_tracker.log(repo_id, "WARN", f"Sync cancelled by user at file {idx + 1}/{total_files}")
                return

            rel_path = os.path.relpath(full_path, temp_dir).replace("\\", "/")
            progress_tracker.update_step(
                repo_id, 4, f"Parsing Files ({idx + 1}/{total_files})",
                current_file=rel_path, processed=idx + 1, total=total_files,
            )
            doc_type = "code" if is_code_file(full_path) else "doc"
            lang = detect_language(full_path)
            db_filepath = f"{repo_name}://{rel_path}"

            try:
                content = read_source_text(full_path)
                file_hash = proc_service.compute_text_hash(content)

                points, symbols, summary_tuple, rels, routes, calls = proc_service.process_file_content(
                    filepath=db_filepath,
                    rel_path=rel_path,
                    content=content,
                    repo=repo_name,
                    doc_type=doc_type,
                    git_url=git_url,
                    commit_sha=commit_sha,
                    provider=provider,
                )
                batch_points.extend(points)
                batch_symbols.extend(symbols)
                batch_routes.extend(routes)
                batch_calls.extend(calls)
                batch_summaries.append(summary_tuple)
                batch_relationships.extend(rels)
                batch_indexed_files.append((db_filepath, repo_name, doc_type, lang, commit_sha, 0.0, file_hash))

                progress_tracker.log(repo_id, "INFO", f"[{idx + 1}/{total_files}] Ingested {rel_path} (+{len(points)} chunks, +{len(symbols)} symbols)")
                if (idx + 1) % 10 == 0 or (idx + 1) == total_files:
                    pct = int(((idx + 1) / total_files) * 100)
                    logger.info(f"[{idx + 1}/{total_files}] ({pct}%) Ingesting {rel_path} (+{len(points)} chunks, +{len(symbols)} symbols)")
            except Exception as fe:
                logger.error(f"Error parsing file {rel_path} in repo '{repo_name}': {fe}")
                progress_tracker.log(repo_id, "ERROR", f"Error parsing {rel_path}: {fe}")

            if (idx + 1) % BATCH_SIZE == 0 or (idx + 1) == total_files:
                if batch_points:
                    upsert_ok = store.upsert_documents(batch_points)
                    if not upsert_ok:
                        logger.error(f"Failed to upsert points to vector store during git indexing for repo '{repo_name}'.")
                        raise RuntimeError(f"Vector store upsert failed during git indexing for repo '{repo_name}'")
                    total_vectors_count += len(batch_points)
                    batch_points.clear()

                with db_service.get_db_connection() as conn:
                    total_symbols_count += persist_sync_batch(
                        conn,
                        batch_indexed_files,
                        batch_summaries,
                        batch_symbols,
                        batch_relationships,
                        batch_routes,
                        batch_calls,
                    )
                trim_memory()

        # Stage 5: Vector Indexing & Cleanup
        progress_tracker.update_step(repo_id, 5, "Upserting Embeddings & Finalizing", pct=90)
        with db_service.get_db_connection() as conn:
            conn.execute(
                "UPDATE git_repositories SET status = 'synced', last_error = NULL, commit_sha = ?, last_synced = CURRENT_TIMESTAMP WHERE id = ?",
                (commit_sha, repo_id),
            )
            conn.commit()

        success_msg = f"Successfully synced repo '{repo_name}' (@ {commit_sha[:8] if commit_sha else 'head'}). Delta: +{len(added_files)} ~{len(modified_files)} -{len(deleted_filepaths)}. Vectors: {total_vectors_count}, Symbols: {total_symbols_count}"
        logger.info(success_msg)
        progress_tracker.log(repo_id, "INFO", success_msg)
        progress_tracker.finish_job(repo_id, "synced")
        idx_state.trigger_list_changed_notification()

    except Exception as e:
        logger.error(f"Unexpected error during repo sync for '{repo_name}': {e}")
        progress_tracker.log(repo_id, "ERROR", f"Sync failed: {str(e)}")
        progress_tracker.finish_job(repo_id, "error", str(e))
        try:
            with db_service.get_db_connection() as conn:
                conn.execute("UPDATE git_repositories SET status = 'error', last_error = ? WHERE id = ?", (str(e), repo_id))
                conn.commit()
        except Exception:
            pass
    finally:
        if not keep_shallow and temp_dir:
            gm_service.cleanup_repo_dir(temp_dir)
        elif keep_shallow and temp_dir:
            logger.info(f"Retained persistent shallow copy for repo '{repo_name}' at {temp_dir}")
        repo_lock.release()
        trim_memory()


def run_full_indexing():
    global is_indexing
    if not indexing_lock.acquire(blocking=False):
        logger.warning("Indexing already running. Skipping duplicate call.")
        return False
    is_indexing = True
    try:
        idx_state.ensure_collection()
        local_syncer.sync_local_paths()

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
        trim_memory()


VectorStoreManager.register_reindex_callback(run_full_indexing)
