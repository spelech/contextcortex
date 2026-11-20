import app.services.database as db_service
import app.services.vector_store as vs_service
import app.services.indexing.state as idx_state
import app.services.indexing.processor as proc_service
from app.services.memory_utils import trim_memory
from app.services.text_decoding import read_source_text
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


def sync_local_paths(force: bool = False, repo: str = None):
    """Scans and indexes mounted local paths and notes vaults.

    force=True ignores the mtime cache and reprocesses every file. repo limits the scan
    to the indexed paths with that repo name.
    """
    try:
        return _sync_local_paths_internal(force=force, repo_filter=repo)
    finally:
        trim_memory()


def sync_local_repo(repo: str, force: bool = True) -> bool:
    """Syncs the local paths of one repo name while it holds the global indexing lock."""
    if not idx_state.indexing_lock.acquire(blocking=False):
        logger.warning(f"Indexing already running. Skipping local sync for repo '{repo}'.")
        return False
    try:
        return sync_local_paths(force=force, repo=repo)
    finally:
        idx_state.indexing_lock.release()


def _sync_local_paths_internal(force: bool = False, repo_filter: str = None):
    logger.info(f"Scanning local paths (force={force}, repo={repo_filter or 'all'})...")
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
    if repo_filter:
        active_paths = [p for p in active_paths if p["repo"] == repo_filter]

    found_files = {} # abs_path -> (repo, category, base_dir)
    from app.services.indexing.git_delta_scanner import (
        DEFAULT_SUPPORTED_EXTENSIONS,
        _IGNORED_DIR_NAMES,
        _should_skip_indexed_file,
    )
    supported_extensions = DEFAULT_SUPPORTED_EXTENSIONS

    from app.services.ripgrep_runner import list_files_with_ripgrep

    for target in active_paths:
        tpath = os.path.abspath(target["path"])
        if not os.path.exists(tpath):
            continue

        if target["type"] == "file":
            if tpath.lower().endswith(supported_extensions) and not _should_skip_indexed_file(os.path.basename(tpath), os.path.basename(tpath)):
                found_files[tpath] = (target["repo"], target["category"], os.path.dirname(tpath))
        else:
            base_dir = tpath
            if target["recursive"]:
                rg_files = list_files_with_ripgrep(
                    tpath,
                    ignored_dirs=_IGNORED_DIR_NAMES,
                    include_hidden=False,
                    extensions=supported_extensions,
                )
                if rg_files is not None:
                    for full, rel_p in rg_files:
                        parts = rel_p.split("/")
                        if any(p.startswith(".") for p in parts):
                            continue
                        if not _should_skip_indexed_file(rel_p, parts[-1]):
                            found_files[full] = (target["repo"], target["category"], base_dir)
                else:
                    for root, dirs, files in os.walk(tpath):
                        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _IGNORED_DIR_NAMES]
                        for file in files:
                            if not file.startswith(".") and file.lower().endswith(supported_extensions):
                                full = os.path.abspath(os.path.join(root, file))
                                rel_p = os.path.relpath(full, base_dir).replace("\\", "/")
                                if not _should_skip_indexed_file(rel_p, file):
                                    found_files[full] = (target["repo"], target["category"], base_dir)
            else:
                try:
                    for entry in os.scandir(tpath):
                        if not entry.name.startswith(".") and entry.is_file() and entry.name.lower().endswith(supported_extensions):
                            if not _should_skip_indexed_file(entry.name, entry.name):
                                found_files[os.path.abspath(entry.path)] = (target["repo"], target["category"], base_dir)
                except Exception:
                    pass

    from app.services.indexing.channel_pipeline import (
        BoundedChannel,
        ChannelIngestionPipeline,
        ParsedFileItem,
    )

    try:
        from app.services.chunking.csharp_route_attributes import cache_repo_csharp_attributes

        for target in active_paths:
            if target.get("type") != "file" and os.path.isdir(target["path"]):
                cache_repo_csharp_attributes(target["repo"], os.path.abspath(target["path"]))
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

    def _produce_local_files(channel: BoundedChannel[ParsedFileItem]) -> None:
        for filepath, (repo, category, base_dir) in found_files.items():
            if channel.is_closed:
                return
            try:
                mtime = os.path.getmtime(filepath)
                with db_service.get_db_connection() as conn:
                    cached = conn.execute("SELECT mtime FROM indexed_files WHERE filepath = ?", (filepath,)).fetchone()

                if not force and cached and abs(cached["mtime"] - mtime) < 0.01:
                    continue  # Cached & unchanged

                rel_path = os.path.relpath(filepath, base_dir).replace("\\", "/")
                doc_type = "code" if is_code_file(filepath) else "doc"
                lang = detect_language(filepath)
                content = read_source_text(filepath)

                try:
                    points, symbols, summary_tuple, rels, routes, calls = proc_service.process_file_content(
                        filepath=filepath,
                        rel_path=rel_path,
                        content=content,
                        repo=repo,
                        doc_type=doc_type,
                        category_override=category,
                        embed=False,
                    )
                except TypeError:
                    points, symbols, summary_tuple, rels, routes, calls = proc_service.process_file_content(
                        filepath=filepath,
                        rel_path=rel_path,
                        content=content,
                        repo=repo,
                        doc_type=doc_type,
                        category_override=category,
                    )

                if not channel.write(
                    ParsedFileItem(
                        filepath=filepath,
                        rel_path=rel_path,
                        repo=repo,
                        points=points,
                        symbols=symbols,
                        summary_tuple=summary_tuple,
                        relationships=rels,
                        routes=routes,
                        calls=calls,
                        indexed_file_row=(filepath, repo, doc_type, lang, None, mtime),
                    )
                ):
                    return
            except Exception as e:
                if channel.is_closed:
                    return
                logger.error(f"Error processing local file {filepath}: {e}")

    def _collect_embedded_local_batch(batch_items: list[ParsedFileItem]) -> None:
        for item in batch_items:
            files_to_delete.append((item.filepath, item.repo))
            all_points.extend(item.points)
            all_symbols.extend(item.symbols)
            all_routes.extend(item.routes)
            all_calls.extend(item.calls)
            if item.summary_tuple is not None:
                all_summaries.append(item.summary_tuple)
            all_relationships.extend(item.relationships)
            if item.indexed_file_row is not None:
                files_to_update_cache.append(item.indexed_file_row)

    try:
        pipeline = ChannelIngestionPipeline(
            persist_batch_fn=_collect_embedded_local_batch,
            file_batch_size=50,
        )
        pipeline.run(_produce_local_files)
    except Exception as e:
        logger.error(f"Failed to embed local files in pipeline: {e}")
        return False

    from app.services.indexing.db_write_channel import submit_db_write

    # Purge old points for modified files
    store = vs_service.get_vector_store()
    for (fpath, repo) in files_to_delete:
        try:
            store.delete_by_path(fpath)

            def _purge_local_file(target_fp: str = fpath) -> None:
                with db_service.get_db_connection() as conn:
                    conn.execute("DELETE FROM ast_symbols WHERE filepath = ?", (target_fp,))
                    conn.execute("DELETE FROM ast_relationships WHERE source_filepath = ?", (target_fp,))
                    conn.execute("DELETE FROM api_routes WHERE filepath = ?", (target_fp,))
                    conn.execute("DELETE FROM api_client_calls WHERE filepath = ?", (target_fp,))
                    conn.commit()

            submit_db_write(_purge_local_file)
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

    # Batch update database tables
    try:
        def _persist_local_batch() -> None:
            with db_service.get_db_connection() as conn:
                if files_to_update_cache:
                    conn.executemany(
                        """INSERT INTO indexed_files (filepath, repo, doc_type, language, commit_sha, mtime)
                           VALUES (?, ?, ?, ?, ?, ?)
                           ON CONFLICT(filepath) DO UPDATE SET
                               repo = EXCLUDED.repo,
                               doc_type = EXCLUDED.doc_type,
                               language = EXCLUDED.language,
                               commit_sha = EXCLUDED.commit_sha,
                               mtime = EXCLUDED.mtime""",
                        files_to_update_cache
                    )
                if all_summaries:
                    conn.executemany(
                        """INSERT INTO file_summaries (filepath, repo, title, folder, category, tags, headings, keywords, summary_text, mtime)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(filepath) DO UPDATE SET
                               repo = EXCLUDED.repo,
                               title = EXCLUDED.title,
                               folder = EXCLUDED.folder,
                               category = EXCLUDED.category,
                               tags = EXCLUDED.tags,
                               headings = EXCLUDED.headings,
                               keywords = EXCLUDED.keywords,
                               summary_text = EXCLUDED.summary_text,
                               mtime = EXCLUDED.mtime""",
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
                    syms_by_file = {}
                    for s in all_symbols:
                        if "inserted_id" in s:
                            sym_map[(s["repo"], s["filepath"], s["name"])] = s["inserted_id"]
                            if s.get("full_symbol"):
                                sym_map[(s["repo"], s["filepath"], s["full_symbol"])] = s["inserted_id"]
                            syms_by_file.setdefault((s["repo"], s["filepath"]), []).append(s)

                    rel_tuples = []
                    for r in all_relationships:
                        src_id = None
                        r_line = r.get("line_number")
                        if r_line is not None:
                            candidates = [
                                s for s in syms_by_file.get((r["repo"], r["source_filepath"]), [])
                                if (s.get("start_line") or 0) <= r_line <= (s.get("end_line") or 0)
                                and (s.get("name") == r["source_symbol"] or s.get("full_symbol") == r["source_symbol"])
                            ]
                            if candidates:
                                candidates.sort(key=lambda s: (s.get("end_line") or 0) - (s.get("start_line") or 0))
                                src_id = candidates[0].get("inserted_id")
                        if src_id is None:
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

        submit_db_write(_persist_local_batch)
    except Exception as e:
        logger.error(f"Failed writing local index updates to SQLite: {e}")
        return False

    return True

