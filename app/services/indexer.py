import os
import uuid
import json
import threading
import asyncio
import re
import logging
from collections import Counter
from typing import Tuple, List, Dict, Any, Optional
import frontmatter
from app.services.db import *
from app.services.chunker import *
from app.services.embeddings import *
from app.services.git_manager import *
from app.services.vector_store import (
    VectorStore, VectorDocument, VectorSearchResult,
    VectorStoreManager, get_vector_store
)

logger = logging.getLogger('knowledge-rag-mcp')

VAULT_PATH = os.getenv("VAULT_PATH", "/docs")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "knowledge_rag_v1")

active_sessions = set()
main_event_loop = None
async def notify_list_changed():
    if not active_sessions:
        return
    logger.info(f"Sending list_changed notifications to {len(active_sessions)} active sessions...")
    for session in list(active_sessions):
        try:
            await session.send_tool_list_changed()
            await session.send_prompt_list_changed()
            await session.send_resource_list_changed()
        except Exception as e:
            logger.warning(f"Failed to send list_changed notification to session: {e}")

def trigger_list_changed_notification():
    if main_event_loop and main_event_loop.is_running():
        asyncio.run_coroutine_threadsafe(notify_list_changed(), main_event_loop)

# Thread locking and indexing status flag
indexing_lock = threading.Lock()
is_indexing = False

# Initialize database
init_db(VAULT_PATH)

# Legacy Qdrant proxy for backward compatibility
class _QdrantCompatProxy:
    def __getattr__(self, item):
        store = get_vector_store()
        client = getattr(store, "client", None)
        if client is not None:
            return getattr(client, item)
        raise AttributeError(f"Active vector store has no direct qdrant client attribute: '{item}'")

qdrant = _QdrantCompatProxy()

def ensure_collection() -> bool:
    """Initializes or validates collection on the active VectorStore backend."""
    try:
        store = get_vector_store()
        return store.ensure_collection()
    except Exception as e:
        logger.error(f"Error initializing vector store collection: {e}")
        return False

def get_chunk_uuid(repo: str, rel_path: str, index: int) -> str:
    namespace = uuid.uuid5(uuid.NAMESPACE_DNS, "knowledge-rag-mcp.lan")
    return str(uuid.uuid5(namespace, f"{repo}:{rel_path}#{index}"))

STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by",
    "can", "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing",
    "don't", "down", "during", "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't",
    "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers", "herself",
    "him", "himself", "his", "how", "how's", "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is",
    "isn't", "it", "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself",
    "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our", "ours",
    "ourselves", "out", "over", "own", "same", "shan't", "she", "she'd", "she'll", "she's", "should",
    "shouldn't", "so", "some", "such", "than", "that", "that's", "the", "their", "theirs", "them",
    "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "wasn't",
    "we", "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when", "when's",
    "where", "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with", "won't",
    "would", "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself",
    "yourselves", "true", "false", "none", "null", "file", "path", "type", "http", "https", "com",
    "net", "org", "yaml", "json", "txt", "md", "root", "self", "def", "class", "return", "import", "from"
}

def extract_keywords_from_text(content: str, title: str, headings: List[str], tags: List[str]) -> List[str]:
    combined = f"{title} {' '.join(headings)} {' '.join(tags)} {content}".lower()
    words = re.findall(r'[a-zA-Z0-9_\-]+', combined)
    filtered = [w for w in words if len(w) >= 3 and w not in STOPWORDS and not w.isdigit()]
    counts = Counter(filtered)
    return [w for w, c in counts.most_common(25)]

# Dynamic MCP Catalog Description
def get_dynamic_catalog_description() -> str:
    base_desc = "Hybrid semantic & code symbol search across registered repositories and documentation."
    try:
        with get_db_connection() as conn:
            repos = [r["name"] for r in conn.execute("SELECT name FROM git_repositories WHERE status = 'synced'").fetchall()]
            local_paths = [r["path"] for r in conn.execute("SELECT path FROM indexed_paths WHERE enabled = 1").fetchall()]
            symbols_count = conn.execute("SELECT count(*) FROM ast_symbols").fetchone()[0]
            files_count = conn.execute("SELECT count(*) FROM indexed_files").fetchone()[0]

        parts = [base_desc]
        if repos or local_paths:
            all_sources = repos + [os.path.basename(p) for p in local_paths]
            parts.append(f"Active Sources ({len(all_sources)}): {', '.join(all_sources[:10])}.")
        if symbols_count > 0:
            parts.append(f"Indexed Code Symbols: {symbols_count} across {files_count} files.")
        return " ".join(parts)
    except Exception as e:
        logger.error(f"Error building dynamic description: {e}")
        return base_desc

# ----------------------------------------------------
# FILE & REPOSITORY PROCESSORS
# ----------------------------------------------------

def process_file_content(
    filepath: str, 
    rel_path: str, 
    content: str, 
    repo: str, 
    doc_type: str, 
    git_url: Optional[str] = None, 
    commit_sha: Optional[str] = None,
    category_override: Optional[str] = None
) -> Tuple[List[VectorDocument], List[Dict[str, Any]], Tuple]:
    """Processes a single file into vector documents, AST symbols, and summary metadata."""
    language = detect_language(filepath)
    title = os.path.basename(filepath)
    folder = os.path.dirname(rel_path) or "root"
    category = category_override or folder
    tags = []
    meta = {}

    points: List[VectorDocument] = []
    ast_symbols = []
    headings = []

    if doc_type == "doc":
        if filepath.endswith((".md", ".txt")):
            try:
                post = frontmatter.loads(content)
                content = post.content
                meta = post.metadata or {}
                if "category" in meta:
                    category = meta["category"]
                if "tags" in meta:
                    raw_tags = meta["tags"]
                    tags = [t.strip() for t in raw_tags.split(",")] if isinstance(raw_tags, str) else raw_tags
            except Exception:
                pass
        
        chunks_models = chunk_markdown(content, max_chars=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
        chunks = [c.model_dump() for c in chunks_models]
        valid_chunks = [c for c in chunks if c.get("content", "").strip()]
        headings = [c["heading"] for c in valid_chunks if c.get("heading") and c["heading"] != "Root"]
        keywords = extract_keywords_from_text(content, title, headings, tags)

        texts_to_embed = []
        for chunk in valid_chunks:
            texts_to_embed.append(
                f"Repo: {repo}\n"
                f"Document: {rel_path}\n"
                f"Category: {category}\n"
                f"Heading: {chunk.get('heading', 'Root')}\n"
                f"Content:\n{chunk['content'].strip()}"
            )

        if texts_to_embed:
            batch_vecs = get_hybrid_embeddings_batch(texts_to_embed)
            for idx, chunk in enumerate(valid_chunks):
                point_id = get_chunk_uuid(repo, rel_path, idx)
                github_url = format_github_permalink(git_url, commit_sha, rel_path, chunk.get("start_line"), chunk.get("end_line"))
                
                bv = batch_vecs[idx] if idx < len(batch_vecs) and isinstance(batch_vecs[idx], dict) else {}
                dense_v = bv.get("dense")
                sparse_obj = bv.get("sparse")
                s_indices = None
                s_values = None
                if sparse_obj is not None:
                    if hasattr(sparse_obj, "indices") and hasattr(sparse_obj, "values"):
                        s_indices = list(sparse_obj.indices)
                        s_values = list(sparse_obj.values)
                    elif isinstance(sparse_obj, dict):
                        s_indices = list(sparse_obj.get("indices", []))
                        s_values = list(sparse_obj.get("values", []))

                points.append(VectorDocument(
                    id=point_id,
                    text=chunk["content"].strip(),
                    dense_vector=dense_v,
                    sparse_indices=s_indices,
                    sparse_values=s_values,
                    repo=repo,
                    doc_type="doc",
                    path=filepath,
                    rel_path=rel_path,
                    title=title,
                    folder=folder,
                    category=category,
                    tags=tags,
                    heading=chunk.get("heading", "Root"),
                    start_line=chunk.get("start_line", 1),
                    end_line=chunk.get("end_line", 1),
                    github_url=github_url,
                ))

    else: # Code file
        ast_result = extract_symbols_and_chunks(content, filepath, repo=repo, max_chunk_chars=CHUNK_SIZE)
        chunks = [c.model_dump() for c in ast_result.chunks]
        ast_symbols = [s.model_dump() for s in ast_result.symbols]
        valid_chunks = [c for c in chunks if c.get("content", "").strip()]
        headings = [s["name"] for s in ast_symbols]
        keywords = extract_keywords_from_text(content, title, headings, [language])

        texts_to_embed = []
        for chunk in valid_chunks:
            symbol_label = chunk.get("symbol") or title
            texts_to_embed.append(
                f"Repo: {repo}\n"
                f"File: {rel_path}\n"
                f"Language: {language}\n"
                f"Symbol: {symbol_label}\n"
                f"Lines: {chunk.get('start_line')}-{chunk.get('end_line')}\n"
                f"Code:\n{chunk['content'].strip()}"
            )

        if texts_to_embed:
            batch_vecs = get_hybrid_embeddings_batch(texts_to_embed)
            for idx, chunk in enumerate(valid_chunks):
                point_id = get_chunk_uuid(repo, rel_path, idx)
                github_url = format_github_permalink(git_url, commit_sha, rel_path, chunk.get("start_line"), chunk.get("end_line"))
                symbol_label = chunk.get("symbol") or title

                bv = batch_vecs[idx] if idx < len(batch_vecs) and isinstance(batch_vecs[idx], dict) else {}
                dense_v = bv.get("dense")
                sparse_obj = bv.get("sparse")
                s_indices = None
                s_values = None
                if sparse_obj is not None:
                    if hasattr(sparse_obj, "indices") and hasattr(sparse_obj, "values"):
                        s_indices = list(sparse_obj.indices)
                        s_values = list(sparse_obj.values)
                    elif isinstance(sparse_obj, dict):
                        s_indices = list(sparse_obj.get("indices", []))
                        s_values = list(sparse_obj.get("values", []))

                points.append(VectorDocument(
                    id=point_id,
                    text=chunk["content"].strip(),
                    dense_vector=dense_v,
                    sparse_indices=s_indices,
                    sparse_values=s_values,
                    repo=repo,
                    doc_type="code",
                    language=language,
                    path=filepath,
                    rel_path=rel_path,
                    title=title,
                    folder=folder,
                    category=language,
                    symbol=symbol_label,
                    start_line=chunk.get("start_line", 1),
                    end_line=chunk.get("end_line", 1),
                    github_url=github_url,
                    metadata={"kind": chunk.get("kind", "code")}
                ))

    mtime = os.path.getmtime(filepath) if os.path.exists(filepath) else 0.0
    summary_tuple = (
        filepath,
        repo,
        title,
        folder,
        category,
        json.dumps(tags),
        json.dumps(list(set(headings[:20]))),
        json.dumps(keywords),
        mtime
    )

    return points, ast_symbols, summary_tuple

# ----------------------------------------------------
# INCREMENTAL SCAN & SYNC ENGINE
# ----------------------------------------------------

def sync_local_paths():
    """Scans and indexes mounted local paths and notes vaults."""
    logger.info("Scanning local paths...")
    active_paths = []
    with get_db_connection() as conn:
        rows = conn.execute("SELECT path, type, recursive, category, repo FROM indexed_paths WHERE enabled = 1").fetchall()
        for r in rows:
            active_paths.append({
                "path": r["path"],
                "type": r["type"],
                "recursive": bool(r["recursive"]),
                "category": r["category"],
                "repo": r["repo"] or "local"
            })

    if not active_paths and os.path.exists(VAULT_PATH):
        active_paths.append({
            "path": VAULT_PATH,
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
                for entry in os.scandir(tpath):
                    if not entry.name.startswith(".") and entry.is_file() and entry.name.endswith(supported_extensions):
                        found_files[os.path.abspath(entry.path)] = (target["repo"], target["category"], base_dir)

    all_points = []
    all_symbols = []
    all_summaries = []
    files_to_update_cache = []
    files_to_delete = []

    for filepath, (repo, category, base_dir) in found_files.items():
        try:
            mtime = os.path.getmtime(filepath)
            with get_db_connection() as conn:
                cached = conn.execute("SELECT mtime FROM indexed_files WHERE filepath = ?", (filepath,)).fetchone()
            
            if cached and abs(cached["mtime"] - mtime) < 0.01:
                continue # Cached & unchanged

            rel_path = os.path.relpath(filepath, base_dir)
            doc_type = "code" if is_code_file(filepath) else "doc"
            lang = detect_language(filepath)

            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            points, symbols, summary_tuple = process_file_content(
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
            all_summaries.append(summary_tuple)
            files_to_update_cache.append((filepath, repo, doc_type, lang, None, mtime))
        except Exception as e:
            logger.error(f"Error processing local file {filepath}: {e}")

    # Purge old points for modified files
    store = get_vector_store()
    for (fpath, repo) in files_to_delete:
        try:
            store.delete_by_path(fpath)
            with get_db_connection() as conn:
                conn.execute("DELETE FROM ast_symbols WHERE filepath = ?", (fpath,))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to delete old points for {fpath}: {e}")

    # Bulk upsert to vector store
    if all_points:
        logger.info(f"Upserting {len(all_points)} vector documents to vector store...")
        try:
            store.upsert_documents(all_points)
        except Exception as e:
            logger.error(f"Failed to upsert points to vector store: {e}")

    # Batch update SQLite tables
    try:
        with get_db_connection() as conn:
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
                symbol_tuples = [
                    (s["repo"], s["filepath"], s["name"], s["full_symbol"], s["kind"], s["start_line"], s["end_line"], s["signature"], s["language"])
                    for s in all_symbols
                ]
                conn.executemany(
                    "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    symbol_tuples
                )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed writing local index updates to SQLite: {e}")

def sync_single_git_repo(repo_id: int):
    """Ephemeral shallow clone, AST parse, hybrid vector upsert, and immediate disk cleanup."""
    with get_db_connection() as conn:
        repo_row = conn.execute("SELECT * FROM git_repositories WHERE id = ?", (repo_id,)).fetchone()
    if not repo_row:
        return

    repo_name = repo_row["name"]
    git_url = repo_row["url"]
    branch = repo_row["branch"] or "main"
    per_repo_token = repo_row["auth_token"]
    per_repo_user = repo_row["auth_user"] if "auth_user" in repo_row.keys() else None
    provider = repo_row["provider"] if "provider" in repo_row.keys() else None

    from app.services.db import get_effective_git_token
    effective_token, effective_user, token_source = get_effective_git_token(
        git_url, 
        override_token=per_repo_token, 
        override_user=per_repo_user, 
        provider=provider
    )

    logger.info(f"Checking remote status for Git repo '{repo_name}' ({git_url}, provider: {provider or 'auto'}, auth: {token_source})...")
    remote_sha = get_remote_head_sha(git_url, branch, token=effective_token, username=effective_user, provider=provider)
    if remote_sha and repo_row["commit_sha"] == remote_sha:
        logger.info(f"Repo '{repo_name}' already up-to-date at commit {remote_sha[:8]}. Skipping clone.")
        with get_db_connection() as conn:
            conn.execute("UPDATE git_repositories SET status = 'synced', last_synced = CURRENT_TIMESTAMP WHERE id = ?", (repo_id,))
            conn.commit()
        return

    # Update status to syncing
    with get_db_connection() as conn:
        conn.execute("UPDATE git_repositories SET status = 'syncing' WHERE id = ?", (repo_id,))
        conn.commit()

    temp_dir = None
    try:
        clone_res = shallow_clone_repo(
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
            with get_db_connection() as conn:
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
        all_summaries = []
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

                    points, symbols, summary_tuple = process_file_content(
                        filepath=db_filepath,
                        rel_path=rel_path,
                        content=content,
                        repo=repo_name,
                        doc_type=doc_type,
                        git_url=git_url,
                        commit_sha=commit_sha
                    )
                    all_points.extend(points)
                    all_symbols.extend(symbols)
                    all_summaries.append(summary_tuple)
                    indexed_files.append((db_filepath, repo_name, doc_type, lang, commit_sha, 0.0))
                except Exception as fe:
                    logger.error(f"Error parsing file {rel_path} in repo '{repo_name}': {fe}")

        # Purge previous vectors for this repo in vector store
        store = get_vector_store()
        try:
            store.delete_by_repo(repo_name)
        except Exception as qe:
            logger.error(f"Error purging old vectors for repo '{repo_name}': {qe}")

        # Bulk upsert new points to vector store
        if all_points:
            logger.info(f"Upserting {len(all_points)} vectors for repo '{repo_name}'...")
            store.upsert_documents(all_points)

        # Update SQLite
        with get_db_connection() as conn:
            conn.execute("DELETE FROM indexed_files WHERE repo = ?", (repo_name,))
            conn.execute("DELETE FROM file_summaries WHERE repo = ?", (repo_name,))
            conn.execute("DELETE FROM ast_symbols WHERE repo = ?", (repo_name,))

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
                symbol_tuples = [
                    (s["repo"], s["filepath"], s["name"], s["full_symbol"], s["kind"], s["start_line"], s["end_line"], s["signature"], s["language"])
                    for s in all_symbols
                ]
                conn.executemany(
                    "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    symbol_tuples
                )

            conn.execute(
                "UPDATE git_repositories SET status = 'synced', last_error = NULL, commit_sha = ?, last_synced = CURRENT_TIMESTAMP WHERE id = ?",
                (commit_sha, repo_id)
            )
            conn.commit()

        logger.info(f"Successfully synced repo '{repo_name}' (@ {commit_sha[:8] if commit_sha else 'head'}). Vectors: {len(all_points)}, Symbols: {len(all_symbols)}")

    except Exception as e:
        logger.error(f"Unexpected error during repo sync for '{repo_name}': {e}")
        try:
            with get_db_connection() as conn:
                conn.execute("UPDATE git_repositories SET status = 'error', last_error = ? WHERE id = ?", (str(e), repo_id))
                conn.commit()
        except Exception:
            pass
    finally:
        # Crucial: Ephemeral disk cleanup!
        cleanup_repo_dir(temp_dir)

def run_full_indexing():
    global is_indexing
    if not indexing_lock.acquire(blocking=False):
        logger.warning("Indexing already running. Skipping duplicate call.")
        return False
    is_indexing = True
    try:
        ensure_collection()
        sync_local_paths()
        
        # Sync all registered git repos
        with get_db_connection() as conn:
            git_repos = conn.execute("SELECT id FROM git_repositories WHERE enabled = 1").fetchall()
        for gr in git_repos:
            sync_single_git_repo(gr["id"])

        import datetime
        set_metadata("last_indexed", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        trigger_list_changed_notification()
        return True
    except Exception as e:
        logger.error(f"Error during full indexing: {e}")
        return False
    finally:
        is_indexing = False
        indexing_lock.release()

# Register re-index callback with VectorStoreManager
VectorStoreManager.register_reindex_callback(run_full_indexing)



