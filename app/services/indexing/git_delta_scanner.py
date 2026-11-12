import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import app.services.database as db_service
import app.services.indexing.processor as proc_service
from app.services.text_decoding import read_source_text

logger = logging.getLogger("contextcortex.indexer")

DEFAULT_SUPPORTED_EXTENSIONS = (
    ".md", ".txt", ".yaml", ".yml", ".json",
    ".py", ".js", ".mjs", ".cjs", ".jsx",
    ".ts", ".mts", ".cts", ".tsx",
    ".go", ".rs", ".cs", ".cpp", ".c", ".h", ".java",
    ".rb", ".php", ".sh", ".sql", ".html", ".css",
    ".cbl", ".cob", ".cpy",
)

_IGNORED_DIR_NAMES = frozenset({
    "node_modules", "vendor", "__pycache__", "venv", ".venv", ".git",
    "dist", "build", "out", "coverage", "_framework", "bin", "obj",
    "target", ".next", ".nuxt", ".vite",
})

_BUNDLED_REL_PREFIXES = (
    "www/assets/",
    "wwwroot/_framework/",
    "wwwroot/lib/",
    "public/build/",
    "static/build/",
)


def _get_db_service():
    sync_mod = sys.modules.get("app.services.indexing.git_syncer")
    return getattr(sync_mod, "db_service", db_service) if sync_mod else db_service


def _get_proc_service():
    sync_mod = sys.modules.get("app.services.indexing.git_syncer")
    return getattr(sync_mod, "proc_service", proc_service) if sync_mod else proc_service


def _should_skip_indexed_file(rel_path: str, filename: str) -> bool:
    """Returns True if a file is a minified bundle or generated asset that should not be indexed as source code."""
    lower_name = filename.lower()
    if lower_name.endswith((".min.js", ".min.css", ".bundle.js", ".bundle.css", ".map", ".d.ts")):
        return True
    norm_rel = rel_path.replace("\\", "/").lstrip("/").lower()
    if any(norm_rel.startswith(prefix) for prefix in _BUNDLED_REL_PREFIXES):
        return True
    if "/www/assets/" in f"/{norm_rel}" or "/wwwroot/_framework/" in f"/{norm_rel}":
        return True
    return False


def compute_git_repo_delta(
    temp_dir: str,
    repo_name: str,
    supported_extensions: Optional[Tuple[str, ...]] = None,
    force: bool = False,
) -> Tuple[List[str], List[str], List[str], List[str]]:
    """
    Computes delta between local cloned repository and indexed_files table in DB.
    Returns: (added_files, modified_files, deleted_filepaths, unchanged_files)
    """
    exts = tuple(e.lower() for e in (supported_extensions if supported_extensions is not None else DEFAULT_SUPPORTED_EXTENSIONS))
    active_db = _get_db_service()
    active_proc = _get_proc_service()

    with active_db.get_db_connection() as conn:
        rows = conn.execute("SELECT filepath, hash FROM indexed_files WHERE repo = ?", (repo_name,)).fetchall()
        db_files = {r["filepath"].replace("\\", "/"): r["hash"] for r in rows}

    found_filepaths = set()
    added_files: List[str] = []
    modified_files: List[str] = []
    unchanged_files: List[str] = []

    for root, dirs, files in os.walk(temp_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _IGNORED_DIR_NAMES]
        for file in files:
            if not file.startswith(".") and file.lower().endswith(exts):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, temp_dir).replace("\\", "/")
                if _should_skip_indexed_file(rel_path, file):
                    continue
                db_filepath = f"{repo_name}://{rel_path}"
                found_filepaths.add(db_filepath)

                try:
                    content = read_source_text(full_path)
                    file_hash = active_proc.compute_text_hash(content)
                except Exception as e:
                    logger.warning(f"Failed to read/hash file {full_path}: {e}")
                    continue

                if db_filepath not in db_files:
                    added_files.append(full_path)
                elif force or db_files[db_filepath] != file_hash:
                    modified_files.append(full_path)
                else:
                    unchanged_files.append(full_path)

    deleted_filepaths = [fp for fp in db_files.keys() if fp not in found_filepaths]
    return added_files, modified_files, deleted_filepaths, unchanged_files


def persist_recent_commits(conn: Any, repo_name: str, recent_commits: List[Dict[str, Any]], retain_commits_count: int) -> None:
    """Stores recent git commits and prunes older commits beyond retain_commits_count."""
    if retain_commits_count <= 0:
        conn.execute("DELETE FROM git_commits WHERE repo = ?", (repo_name,))
        conn.commit()
        return

    if recent_commits:
        commit_tuples = [
            (
                repo_name,
                c["commit_sha"],
                c.get("author"),
                c.get("committed_at"),
                c.get("message"),
                json.dumps(c.get("files_changed", [])),
            )
            for c in recent_commits
        ]
        conn.executemany(
            """INSERT INTO git_commits (repo, commit_sha, author, committed_at, message, files_changed)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(repo, commit_sha) DO UPDATE SET
                   author = EXCLUDED.author,
                   committed_at = EXCLUDED.committed_at,
                   message = EXCLUDED.message,
                   files_changed = EXCLUDED.files_changed""",
            commit_tuples,
        )
        conn.execute(
            """DELETE FROM git_commits
               WHERE repo = ? AND id NOT IN (
                   SELECT id FROM git_commits
                   WHERE repo = ?
                   ORDER BY committed_at DESC, id DESC
                   LIMIT ?
               )""",
            (repo_name, repo_name, retain_commits_count),
        )
        conn.commit()


def persist_sync_batch(
    conn: Any,
    batch_indexed_files: List[tuple],
    batch_summaries: List[tuple],
    batch_symbols: List[Dict[str, Any]],
    batch_relationships: List[Dict[str, Any]],
    batch_routes: List[Dict[str, Any]],
    batch_calls: List[Dict[str, Any]],
) -> int:
    """Flushes a batch of parsed AST symbols, relationships, API routes, and file summaries into SQLite."""
    inserted_symbols = 0
    if batch_indexed_files:
        conn.executemany(
            """INSERT INTO indexed_files (filepath, repo, doc_type, language, commit_sha, mtime, hash)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(filepath) DO UPDATE SET
                   repo = EXCLUDED.repo,
                   doc_type = EXCLUDED.doc_type,
                   language = EXCLUDED.language,
                   commit_sha = EXCLUDED.commit_sha,
                   mtime = EXCLUDED.mtime,
                   hash = EXCLUDED.hash""",
            batch_indexed_files,
        )
        batch_indexed_files.clear()

    if batch_summaries:
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
            batch_summaries,
        )
        batch_summaries.clear()

    if batch_symbols:
        for s in batch_symbols:
            cursor = conn.execute(
                "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (s["repo"], s["filepath"], s["name"], s["full_symbol"], s["kind"], s["start_line"], s["end_line"], s["signature"], s["language"]),
            )
            s["inserted_id"] = cursor.lastrowid
        inserted_symbols = len(batch_symbols)

    if batch_relationships:
        sym_map: Dict[Tuple[str, str, str], Any] = {}
        syms_by_file: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for s in batch_symbols:
            if "inserted_id" in s:
                sym_map[(s["repo"], s["filepath"], s["name"])] = s["inserted_id"]
                if s.get("full_symbol"):
                    sym_map[(s["repo"], s["filepath"], s["full_symbol"])] = s["inserted_id"]
                syms_by_file.setdefault((s["repo"], s["filepath"]), []).append(s)

        rel_tuples = []
        for r in batch_relationships:
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
                r["line_number"],
            ))

        conn.executemany(
            """INSERT INTO ast_relationships
               (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rel_tuples,
        )
        batch_relationships.clear()

    if batch_routes:
        route_tuples = [
            (r["repo"], r["filepath"], r["framework"], r["http_method"], r["path_pattern"], r.get("handler_symbol"), r["start_line"], r["end_line"])
            for r in batch_routes
        ]
        conn.executemany(
            "INSERT INTO api_routes (repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            route_tuples,
        )
        batch_routes.clear()

    if batch_calls:
        call_tuples = [
            (c["repo"], c["filepath"], c.get("http_method"), c["url_pattern"], c.get("caller_symbol"), c["line_number"])
            for c in batch_calls
        ]
        conn.executemany(
            "INSERT INTO api_client_calls (repo, filepath, http_method, url_pattern, caller_symbol, line_number) VALUES (?, ?, ?, ?, ?, ?)",
            call_tuples,
        )
        batch_calls.clear()

    batch_symbols.clear()
    conn.commit()
    return inserted_symbols
