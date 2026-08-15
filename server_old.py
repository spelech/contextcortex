import os
import re
import json
import uuid
import logging
import threading
import asyncio
import anyio
from contextlib import AsyncExitStack
import concurrent.futures
from collections import Counter
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from mcp.server import Server
from mcp.server.session import ServerSession
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent, Resource, Prompt, PromptMessage, PromptArgument
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
import frontmatter

from db import (
    get_db_connection, init_db, get_metadata, set_metadata,
    get_effective_github_token, get_token_source, CACHE_DB_PATH
)
from chunker import (
    extract_symbols_and_chunks, chunk_markdown, detect_language, 
    is_code_file, get_file_outline
)
from embeddings import (
    get_dense_embedding, get_sparse_embedding, get_hybrid_embeddings,
    get_hybrid_embeddings_batch, get_dense_dim, EMBEDDING_PROVIDER, 
    DENSE_MODEL_NAME, SPARSE_MODEL_NAME
)
from git_manager import (
    shallow_clone_repo, cleanup_repo_dir, get_remote_head_sha,
    format_github_permalink, check_github_rate_limit, mask_token
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("notes-rag-mcp")

# Environment configurations
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "notes_rag_v2")
VAULT_PATH = os.getenv("VAULT_PATH", "/docs")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))

# Active MCP sessions and event loop
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

# Initialize Qdrant Client
logger.info(f"Connecting to Qdrant at {QDRANT_URL}")
qdrant = QdrantClient(url=QDRANT_URL)

def ensure_collection():
    """Initializes or validates named multi-vector (Dense + Sparse) Qdrant collection."""
    dim = get_dense_dim()
    try:
        if qdrant.collection_exists(COLLECTION_NAME):
            info = qdrant.get_collection(COLLECTION_NAME)
            vectors_config = info.config.params.vectors
            sparse_config = info.config.params.sparse_vectors
            
            needs_recreate = False
            if not isinstance(vectors_config, dict) or "dense" not in vectors_config:
                logger.warning("Existing collection uses legacy single-vector schema. Upgrading to Named Multi-Vectors (Dense + Sparse)...")
                needs_recreate = True
            elif sparse_config is None or "sparse" not in sparse_config:
                logger.warning("Collection missing sparse vector index. Upgrading to Hybrid collection...")
                needs_recreate = True
            elif vectors_config["dense"].size != dim:
                logger.warning(f"Dense vector dimension mismatch: expected {dim}, found {vectors_config['dense'].size}. Recreating...")
                needs_recreate = True
                
            if needs_recreate:
                qdrant.delete_collection(COLLECTION_NAME)

        if not qdrant.collection_exists(COLLECTION_NAME):
            logger.info(f"Creating Hybrid Qdrant collection: {COLLECTION_NAME} (Dense: {dim}d, Sparse: BM25)")
            qdrant.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config={
                    "dense": qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE)
                },
                sparse_vectors_config={
                    "sparse": qmodels.SparseVectorParams()
                }
            )
            # Create payload indexes for fast filtering
            qdrant.create_payload_index(COLLECTION_NAME, "repo", qmodels.PayloadSchemaType.KEYWORD)
            qdrant.create_payload_index(COLLECTION_NAME, "doc_type", qmodels.PayloadSchemaType.KEYWORD)
            qdrant.create_payload_index(COLLECTION_NAME, "language", qmodels.PayloadSchemaType.KEYWORD)
            qdrant.create_payload_index(COLLECTION_NAME, "path", qmodels.PayloadSchemaType.KEYWORD)
        else:
            logger.info(f"Collection {COLLECTION_NAME} verified with Named Multi-Vectors.")
    except Exception as e:
        logger.error(f"Error initializing Qdrant collection: {e}")

def get_chunk_uuid(repo: str, rel_path: str, index: int) -> str:
    namespace = uuid.uuid5(uuid.NAMESPACE_DNS, "notes-rag-mcp.lan")
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
) -> Tuple[List[qmodels.PointStruct], List[Dict[str, Any]], Tuple]:
    """Processes a single file into hybrid vector points, AST symbols, and summary metadata."""
    language = detect_language(filepath)
    title = os.path.basename(filepath)
    folder = os.path.dirname(rel_path) or "root"
    category = category_override or folder
    tags = []
    meta = {}

    points = []
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
        
        chunks = chunk_markdown(content, max_chars=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
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
                points.append(qmodels.PointStruct(
                    id=point_id,
                    vector=batch_vecs[idx],
                    payload={
                        "repo": repo,
                        "doc_type": "doc",
                        "path": filepath,
                        "rel_path": rel_path,
                        "title": title,
                        "folder": folder,
                        "category": category,
                        "tags": tags,
                        "heading": chunk.get("heading", "Root"),
                        "start_line": chunk.get("start_line", 1),
                        "end_line": chunk.get("end_line", 1),
                        "github_url": github_url,
                        "content": chunk["content"].strip()
                    }
                ))

    else: # Code file
        ast_result = extract_symbols_and_chunks(content, filepath, repo=repo, max_chunk_chars=CHUNK_SIZE)
        chunks = ast_result["chunks"]
        ast_symbols = ast_result["symbols"]
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
                points.append(qmodels.PointStruct(
                    id=point_id,
                    vector=batch_vecs[idx],
                    payload={
                        "repo": repo,
                        "doc_type": "code",
                        "language": language,
                        "path": filepath,
                        "rel_path": rel_path,
                        "title": title,
                        "folder": folder,
                        "category": language,
                        "symbol": symbol_label,
                        "kind": chunk.get("kind", "code"),
                        "start_line": chunk.get("start_line", 1),
                        "end_line": chunk.get("end_line", 1),
                        "github_url": github_url,
                        "content": chunk["content"].strip()
                    }
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
    for (fpath, repo) in files_to_delete:
        try:
            qdrant.delete(
                collection_name=COLLECTION_NAME,
                points_selector=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(key="path", match=qmodels.MatchValue(value=fpath))
                    ]
                )
            )
            with get_db_connection() as conn:
                conn.execute("DELETE FROM ast_symbols WHERE filepath = ?", (fpath,))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to delete old points for {fpath}: {e}")

    # Bulk upsert to Qdrant
    if all_points:
        logger.info(f"Upserting {len(all_points)} hybrid vector points to Qdrant...")
        try:
            qdrant.upsert(collection_name=COLLECTION_NAME, points=all_points)
        except Exception as e:
            logger.error(f"Failed to upsert points to Qdrant: {e}")

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
        repo_row = conn.execute("SELECT id, name, url, branch, commit_sha, auth_token FROM git_repositories WHERE id = ?", (repo_id,)).fetchone()
    if not repo_row:
        return

    repo_name = repo_row["name"]
    git_url = repo_row["url"]
    branch = repo_row["branch"] or "main"
    per_repo_token = repo_row["auth_token"]
    effective_token = get_effective_github_token(per_repo_token)

    logger.info(f"Checking remote status for Git repo '{repo_name}' ({git_url})...")
    remote_sha = get_remote_head_sha(git_url, branch, token=effective_token)
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
        temp_dir, commit_sha, err = shallow_clone_repo(git_url, branch, token=effective_token, repo_id=str(repo_id))
        if err or not temp_dir:
            logger.error(f"Failed to clone repo '{repo_name}': {err}")
            with get_db_connection() as conn:
                conn.execute("UPDATE git_repositories SET status = 'error' WHERE id = ?", (repo_id,))
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

        # Purge previous vectors for this repo in Qdrant
        try:
            qdrant.delete(
                collection_name=COLLECTION_NAME,
                points_selector=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(key="repo", match=qmodels.MatchValue(value=repo_name))
                    ]
                )
            )
        except Exception as qe:
            logger.error(f"Error purging old vectors for repo '{repo_name}': {qe}")

        # Bulk upsert new points to Qdrant
        if all_points:
            logger.info(f"Upserting {len(all_points)} vectors for repo '{repo_name}'...")
            qdrant.upsert(collection_name=COLLECTION_NAME, points=all_points)

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
                "UPDATE git_repositories SET status = 'synced', commit_sha = ?, last_synced = CURRENT_TIMESTAMP WHERE id = ?",
                (commit_sha, repo_id)
            )
            conn.commit()

        logger.info(f"Successfully synced repo '{repo_name}' (@ {commit_sha[:8] if commit_sha else 'head'}). Vectors: {len(all_points)}, Symbols: {len(all_symbols)}")

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
    finally:
        is_indexing = False
        indexing_lock.release()

# ----------------------------------------------------
# MCP SERVER & SPECIALIZED TOOLS
# ----------------------------------------------------

mcp_server = Server("notes-rag-mcp", version="2.0.0")

@mcp_server.list_tools()
async def list_tools() -> List[Tool]:
    catalog_desc = get_dynamic_catalog_description()
    return [
        Tool(
            name="search_code",
            description=f"Hybrid semantic and BM25 search over code functions, classes, and logic snippets with line numbers and GitHub links. {catalog_desc}",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language question or code concept (e.g. 'JWT token authentication handler')."},
                    "repo": {"type": "string", "description": "Optional repository name/alias to filter by."},
                    "language": {"type": "string", "description": "Optional language filter (e.g. 'python', 'typescript', 'go')."},
                    "limit": {"type": "integer", "description": "Max number of code blocks to return (default 5).", "default": 5}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="search_docs",
            description=f"Hybrid search across system documentation, markdown notes, architectural decisions, and runbooks. {catalog_desc}",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query or documentation topic."},
                    "repo": {"type": "string", "description": "Optional repository/vault filter."},
                    "category": {"type": "string", "description": "Optional category filter."},
                    "tag": {"type": "string", "description": "Optional tag filter."},
                    "limit": {"type": "integer", "description": "Max documents to return (default 5).", "default": 5}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="find_symbol",
            description="Instant exact or prefix symbol lookup (functions, classes, structs, interfaces) from AST index without broad token scans.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Symbol name (e.g. 'extract_symbols_and_chunks' or 'FastAPI')."},
                    "repo": {"type": "string", "description": "Optional repository filter."},
                    "exact": {"type": "boolean", "description": "If true, matches exact name. If false, prefix/fuzzy matches.", "default": True},
                    "limit": {"type": "integer", "description": "Max results (default 10).", "default": 10}
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="get_file_outline",
            description="Get the AST outline (classes, methods, functions, line numbers) of a file without retrieving its entire token body.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "File path (e.g. 'src/server.py' or 'repo_name://src/server.py')."},
                    "repo": {"type": "string", "description": "Repository identifier (optional)."}
                },
                "required": ["filepath"]
            }
        ),
        Tool(
            name="list_repositories",
            description="Lists all indexed local paths and remote Git repositories, including active branches, commit SHAs, and file counts.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="sync_repository",
            description="Trigger an immediate re-fetch and re-indexing of a registered Git repo or local path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository name to sync (or omit to sync all)."}
                }
            }
        ),
        Tool(
            name="index_status",
            description="Get global index health, vector counts, GitHub rate limits, and active embedding models.",
            inputSchema={"type": "object", "properties": {}}
        )
    ]

@mcp_server.list_resources()
async def list_resources() -> List[Resource]:
    return [
        Resource(
            uri="notes://catalog/summary",
            name="Repository & Documentation Topic Catalog",
            description="Catalog of indexed repositories, documentation files, and AST symbol distributions.",
            mimeType="text/markdown"
        )
    ]

@mcp_server.read_resource()
async def read_resource(uri: str) -> str:
    if uri == "notes://catalog/summary":
        try:
            with get_db_connection() as conn:
                git_repos = conn.execute("SELECT name, url, branch, commit_sha, status, last_synced FROM git_repositories").fetchall()
                files = conn.execute("SELECT filepath, repo, doc_type, language FROM indexed_files").fetchall()
                symbols_count = conn.execute("SELECT count(*) FROM ast_symbols").fetchone()[0]

            md = "# Repository & Documentation Catalog\n\n"
            md += f"**Total Files Indexed:** {len(files)} | **Total AST Code Symbols:** {symbols_count}\n\n"

            if git_repos:
                md += "## Registered Git Repositories\n\n"
                md += "| Name | URL | Branch | Commit SHA | Status | Last Synced |\n"
                md += "| --- | --- | --- | --- | --- | --- |\n"
                for gr in git_repos:
                    sha_short = gr["commit_sha"][:8] if gr["commit_sha"] else "-"
                    md += f"| {gr['name']} | {gr['url']} | {gr['branch']} | `{sha_short}` | {gr['status']} | {gr['last_synced'] or '-'} |\n"
                md += "\n"

            md += "## Indexed File Overview\n\n"
            md += "| Repository | File | Type | Language |\n"
            md += "| --- | --- | --- | --- |\n"
            for f in files[:40]:
                md += f"| {f['repo']} | {f['filepath']} | {f['doc_type']} | {f['language']} |\n"
            if len(files) > 40:
                md += f"\n*...and {len(files) - 40} more files.*"
            return md
        except Exception as e:
            return f"Error generating catalog resource: {str(e)}"
    raise ValueError(f"Unknown resource URI: {uri}")

@mcp_server.list_prompts()
async def list_prompts() -> List[Prompt]:
    prompts = []
    try:
        with get_db_connection() as conn:
            rows = conn.execute("SELECT name, description, arguments_json FROM custom_prompts ORDER BY name ASC").fetchall()
        for r in rows:
            args_list = []
            if r["arguments_json"]:
                try:
                    for a in json.loads(r["arguments_json"]):
                        args_list.append(PromptArgument(
                            name=a.get("name", ""),
                            description=a.get("description", ""),
                            required=a.get("required", False)
                        ))
                except Exception:
                    pass
            prompts.append(Prompt(name=r["name"], description=r["description"], arguments=args_list))
    except Exception as e:
        logger.error(f"Error listing prompts: {e}")
    return prompts

@mcp_server.get_prompt()
async def get_prompt(name: str, arguments: dict = None) -> List[PromptMessage]:
    arguments = arguments or {}
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT template FROM custom_prompts WHERE name = ?", (name,)).fetchone()
        if not row:
            raise ValueError(f"Unknown prompt: {name}")
        formatted = row["template"]
        for k, v in arguments.items():
            formatted = formatted.replace(f"{{{k}}}", str(v))
        return [PromptMessage(role="user", content=TextContent(type="text", text=formatted))]
    except Exception as e:
        raise ValueError(f"Failed to get prompt '{name}': {e}")

# ----------------------------------------------------
# HYBRID RETRIEVAL EXECUTION
# ----------------------------------------------------

def execute_hybrid_search(
    query_text: str,
    doc_type: Optional[str] = None,
    repo: Optional[str] = None,
    language: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 5
) -> List[Any]:
    """Executes Dense + BM25 Sparse hybrid search with Reciprocal Rank Fusion in Qdrant."""
    dense_vec = get_dense_embedding(query_text.strip())
    sparse_vec = get_sparse_embedding(query_text.strip())

    must_conditions = []
    if doc_type:
        must_conditions.append(qmodels.FieldCondition(key="doc_type", match=qmodels.MatchValue(value=doc_type)))
    if repo:
        must_conditions.append(qmodels.FieldCondition(key="repo", match=qmodels.MatchValue(value=repo)))
    if language:
        must_conditions.append(qmodels.FieldCondition(key="language", match=qmodels.MatchValue(value=language)))
    if category:
        must_conditions.append(qmodels.FieldCondition(key="category", match=qmodels.MatchValue(value=category)))
    if tag:
        must_conditions.append(qmodels.FieldCondition(key="tags", match=qmodels.MatchAny(any=[tag])))

    query_filter = qmodels.Filter(must=must_conditions) if must_conditions else None

    # Use RRF if sparse vector is available, otherwise dense search
    if sparse_vec is not None:
        response = qdrant.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=[
                qmodels.Prefetch(
                    query=dense_vec,
                    using="dense",
                    limit=limit * 2,
                    filter=query_filter
                ),
                qmodels.Prefetch(
                    query=sparse_vec,
                    using="sparse",
                    limit=limit * 2,
                    filter=query_filter
                )
            ],
            query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
            limit=limit
        )
    else:
        response = qdrant.query_points(
            collection_name=COLLECTION_NAME,
            query=dense_vec,
            using="dense",
            query_filter=query_filter,
            limit=limit
        )
    return response.points

@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict) -> List[TextContent]:
    if name == "search_code":
        query = arguments.get("query", "").strip()
        repo = arguments.get("repo")
        language = arguments.get("language")
        limit = arguments.get("limit", 5)

        if not query:
            return [TextContent(type="text", text="Error: search query cannot be empty.")]

        try:
            hits = execute_hybrid_search(query_text=query, doc_type="code", repo=repo, language=language, limit=limit)
            if not hits:
                return [TextContent(type="text", text=f"No matching code snippets found for query: '{query}'.")]

            formatted = []
            for hit in hits:
                p = hit.payload
                header = f"### [{p.get('repo')}] {p.get('rel_path')} (Lines {p.get('start_line')}-{p.get('end_line')})"
                if p.get("symbol"):
                    header += f" - Symbol: `{p.get('symbol')}`"
                if p.get("github_url"):
                    header += f"\nGitHub Link: {p.get('github_url')}"
                header += f"\nRRF Score: {hit.score:.4f}\n"

                lang = p.get("language", "")
                block = f"{header}```{lang}\n{p.get('content')}\n```"
                formatted.append(block)

            return [TextContent(type="text", text="\n\n========================\n\n".join(formatted))]
        except Exception as e:
            logger.error(f"search_code failed: {e}")
            return [TextContent(type="text", text=f"Error executing code search: {str(e)}")]

    elif name == "search_docs":
        query = arguments.get("query", "").strip()
        repo = arguments.get("repo")
        category = arguments.get("category")
        tag = arguments.get("tag")
        limit = arguments.get("limit", 5)

        if not query:
            return [TextContent(type="text", text="Error: search query cannot be empty.")]

        try:
            hits = execute_hybrid_search(query_text=query, doc_type="doc", repo=repo, category=category, tag=tag, limit=limit)
            if not hits:
                return [TextContent(type="text", text=f"No matching documentation found for query: '{query}'.")]

            formatted = []
            for hit in hits:
                p = hit.payload
                tags_str = ", ".join(p.get("tags", []))
                header = f"### [{p.get('repo')}] {p.get('rel_path')}"
                if p.get("heading") and p.get("heading") != "Root":
                    header += f" -> {p.get('heading')}"
                if tags_str:
                    header += f"\nTags: {tags_str}"
                if p.get("github_url"):
                    header += f"\nGitHub Link: {p.get('github_url')}"
                header += f"\nRRF Score: {hit.score:.4f}\n"

                block = f"{header}---\n{p.get('content')}"
                formatted.append(block)

            return [TextContent(type="text", text="\n\n========================\n\n".join(formatted))]
        except Exception as e:
            logger.error(f"search_docs failed: {e}")
            return [TextContent(type="text", text=f"Error executing doc search: {str(e)}")]

    elif name == "find_symbol":
        sym_name = arguments.get("name", "").strip()
        repo = arguments.get("repo")
        exact = arguments.get("exact", True)
        limit = arguments.get("limit", 10)

        if not sym_name:
            return [TextContent(type="text", text="Error: symbol name cannot be empty.")]

        try:
            with get_db_connection() as conn:
                query = "SELECT repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language FROM ast_symbols WHERE "
                params = []
                if exact:
                    query += "(name = ? OR full_symbol = ?)"
                    params.extend([sym_name, sym_name])
                else:
                    query += "(name LIKE ? OR full_symbol LIKE ?)"
                    params.extend([f"%{sym_name}%", f"%{sym_name}%"])

                if repo:
                    query += " AND repo = ?"
                    params.append(repo)

                query += f" LIMIT {limit}"
                rows = conn.execute(query, params).fetchall()

            if not rows:
                return [TextContent(type="text", text=f"No symbols found matching '{sym_name}'.")]

            lines = [f"Found {len(rows)} matching symbols for '{sym_name}':\n"]
            for r in rows:
                lines.append(
                    f"- **{r['name']}** (`{r['kind']}`) in `[{r['repo']}] {r['filepath']}` (Lines {r['start_line']}-{r['end_line']})\n"
                    f"  Signature: `{r['signature']}`"
                )
            return [TextContent(type="text", text="\n".join(lines))]
        except Exception as e:
            logger.error(f"find_symbol error: {e}")
            return [TextContent(type="text", text=f"Error finding symbol: {str(e)}")]

    elif name == "get_file_outline":
        filepath = arguments.get("filepath", "").strip()
        repo = arguments.get("repo")

        try:
            with get_db_connection() as conn:
                if repo:
                    rows = conn.execute(
                        "SELECT name, full_symbol, kind, start_line, end_line, signature FROM ast_symbols WHERE (filepath = ? OR filepath LIKE ?) AND repo = ? ORDER BY start_line ASC",
                        (filepath, f"%{filepath}", repo)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT repo, filepath, name, full_symbol, kind, start_line, end_line, signature FROM ast_symbols WHERE filepath = ? OR filepath LIKE ? ORDER BY start_line ASC",
                        (filepath, f"%{filepath}")
                    ).fetchall()

            if not rows:
                return [TextContent(type="text", text=f"No outline available for '{filepath}'.")]

            outline_text = f"# File Outline: {filepath}\n\n"
            for r in rows:
                outline_text += f"- **{r['name']}** ({r['kind']}, lines {r['start_line']}-{r['end_line']}): `{r['signature']}`\n"
            return [TextContent(type="text", text=outline_text)]
        except Exception as e:
            return [TextContent(type="text", text=f"Failed to get outline: {str(e)}")]

    elif name == "list_repositories":
        try:
            with get_db_connection() as conn:
                git_repos = conn.execute("SELECT id, name, url, branch, commit_sha, status, last_synced FROM git_repositories").fetchall()
                local_paths = conn.execute("SELECT path, repo, category FROM indexed_paths WHERE enabled = 1").fetchall()
                counts = conn.execute("SELECT repo, count(*) as cnt FROM indexed_files GROUP BY repo").fetchall()
                file_count_map = {c["repo"]: c["cnt"] for c in counts}

            out = "# Registered Sources & Repositories\n\n"
            if git_repos:
                out += "### Git Repositories\n"
                for gr in git_repos:
                    fc = file_count_map.get(gr["name"], 0)
                    sha = gr["commit_sha"][:8] if gr["commit_sha"] else "None"
                    out += f"- **{gr['name']}** ({gr['url']} @ `{gr['branch']}` | SHA: `{sha}`) - Status: `{gr['status']}` | Files: {fc} | Last Synced: {gr['last_synced'] or 'Never'}\n"
                out += "\n"

            if local_paths:
                out += "### Local Monitored Paths\n"
                for lp in local_paths:
                    fc = file_count_map.get(lp["repo"], 0)
                    out += f"- **{lp['repo']}** (`{lp['path']}`) - Category: `{lp['category']}` | Files: {fc}\n"

            return [TextContent(type="text", text=out)]
        except Exception as e:
            return [TextContent(type="text", text=f"Error listing repositories: {str(e)}")]

    elif name == "sync_repository":
        target_repo = arguments.get("repo")
        try:
            if target_repo:
                with get_db_connection() as conn:
                    row = conn.execute("SELECT id FROM git_repositories WHERE name = ?", (target_repo,)).fetchone()
                if row:
                    threading.Thread(target=sync_single_git_repo, args=(row["id"],), daemon=True).start()
                    return [TextContent(type="text", text=f"Triggered background sync for repo: '{target_repo}'")]
            
            threading.Thread(target=run_full_indexing, daemon=True).start()
            return [TextContent(type="text", text="Triggered full background re-indexing.")]
        except Exception as e:
            return [TextContent(type="text", text=f"Failed to trigger sync: {str(e)}")]

    elif name == "index_status":
        try:
            with get_db_connection() as conn:
                files_count = conn.execute("SELECT count(*) FROM indexed_files").fetchone()[0]
                symbols_count = conn.execute("SELECT count(*) FROM ast_symbols").fetchone()[0]
                git_count = conn.execute("SELECT count(*) FROM git_repositories").fetchone()[0]
            
            points_count = 0
            if qdrant.collection_exists(COLLECTION_NAME):
                info = qdrant.get_collection(COLLECTION_NAME)
                points_count = info.points_count

            eff_token = get_effective_github_token()
            rate_info = check_github_rate_limit(eff_token)

            status_text = (
                f"Collection: {COLLECTION_NAME}\n"
                f"Embedding Provider: {EMBEDDING_PROVIDER.upper()} ({DENSE_MODEL_NAME} + {SPARSE_MODEL_NAME})\n"
                f"Total Hybrid Vectors: {points_count}\n"
                f"Total Indexed Files: {files_count}\n"
                f"Total AST Symbols: {symbols_count}\n"
                f"Registered Git Repos: {git_count}\n"
                f"GitHub Token Source: {get_token_source()} (Masked: {mask_token(eff_token)})\n"
                f"GitHub API Rate Limit: {rate_info.get('remaining', 0)} / {rate_info.get('limit', 60)}"
            )
            return [TextContent(type="text", text=status_text)]
        except Exception as e:
            return [TextContent(type="text", text=f"Failed to get status: {str(e)}")]

    else:
        raise ValueError(f"Unknown tool: {name}")

# ----------------------------------------------------
# FASTAPI APP & REST ENDPOINTS
# ----------------------------------------------------

app = FastAPI(title="Notes & Code RAG MCP Server")
sse_transport = SseServerTransport("/messages/")

@app.get("/admin/api/stats")
async def api_get_stats():
    try:
        with get_db_connection() as conn:
            files_count = conn.execute("SELECT count(*) FROM indexed_files").fetchone()[0]
            paths_count = conn.execute("SELECT count(*) FROM indexed_paths").fetchone()[0]
            repos_count = conn.execute("SELECT count(*) FROM git_repositories").fetchone()[0]
            symbols_count = conn.execute("SELECT count(*) FROM ast_symbols").fetchone()[0]
            last_indexed = get_metadata("last_indexed", "Never")

            sum_rows = conn.execute("SELECT keywords FROM file_summaries").fetchall()
            kw_counts = {}
            for sr in sum_rows:
                if sr["keywords"]:
                    try:
                        for kw in json.loads(sr["keywords"]):
                            kw_counts[kw] = kw_counts.get(kw, 0) + 1
                    except Exception:
                        pass
            top_keywords = sorted(kw_counts.keys(), key=lambda k: kw_counts[k], reverse=True)[:25]

        points_count = 0
        if qdrant.collection_exists(COLLECTION_NAME):
            info = qdrant.get_collection(COLLECTION_NAME)
            points_count = info.points_count

        eff_token = get_effective_github_token()
        rate_info = check_github_rate_limit(eff_token)

        return {
            "files_count": files_count,
            "paths_count": paths_count,
            "repos_count": repos_count,
            "symbols_count": symbols_count,
            "points_count": points_count,
            "is_indexing": is_indexing,
            "last_indexed": last_indexed,
            "embedding_provider": EMBEDDING_PROVIDER.upper(),
            "dense_model": DENSE_MODEL_NAME,
            "sparse_model": SPARSE_MODEL_NAME,
            "top_keywords": top_keywords,
            "token_source": get_token_source(),
            "masked_token": mask_token(eff_token),
            "rate_limit": rate_info
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/admin/api/repos")
async def api_get_repos():
    try:
        with get_db_connection() as conn:
            rows = conn.execute("SELECT id, name, url, branch, commit_sha, enabled, status, last_synced, added_at, (SELECT count(*) FROM indexed_files WHERE repo = git_repositories.name) as file_count FROM git_repositories ORDER BY added_at DESC").fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/admin/api/repos")
async def api_add_repo(request: Request):
    try:
        data = await request.json()
        name = data.get("name", "").strip()
        url = data.get("url", "").strip()
        branch = data.get("branch", "main").strip() or "main"
        token = data.get("auth_token", "").strip() or None

        if not name or not url:
            return JSONResponse(status_code=400, content={"error": "Repository name and Git URL are required."})

        name = re.sub(r'[^a-zA-Z0-9_\-]', '_', name).lower()

        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO git_repositories (name, url, branch, auth_token) VALUES (?, ?, ?, ?)",
                (name, url, branch, token)
            )
            conn.commit()
            repo_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        threading.Thread(target=sync_single_git_repo, args=(repo_id,), daemon=True).start()
        return {"status": "success", "message": f"Added repo '{name}' and started background sync."}
    except sqlite3.IntegrityError:
        return JSONResponse(status_code=400, content={"error": f"Repository '{name}' is already registered."})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/admin/api/repos/sync/{repo_id}")
async def api_sync_repo(repo_id: int):
    try:
        threading.Thread(target=sync_single_git_repo, args=(repo_id,), daemon=True).start()
        return {"status": "success", "message": f"Sync triggered for repository ID {repo_id}"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.delete("/admin/api/repos/{repo_id}")
async def api_delete_repo(repo_id: int):
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT name FROM git_repositories WHERE id = ?", (repo_id,)).fetchone()
            if not row:
                return JSONResponse(status_code=404, content={"error": "Repo not found"})
            repo_name = row["name"]
            conn.execute("DELETE FROM git_repositories WHERE id = ?", (repo_id,))
            conn.execute("DELETE FROM indexed_files WHERE repo = ?", (repo_name,))
            conn.execute("DELETE FROM file_summaries WHERE repo = ?", (repo_name,))
            conn.execute("DELETE FROM ast_symbols WHERE repo = ?", (repo_name,))
            conn.commit()

        # Delete from Qdrant
        try:
            qdrant.delete(
                collection_name=COLLECTION_NAME,
                points_selector=qmodels.Filter(
                    must=[qmodels.FieldCondition(key="repo", match=qmodels.MatchValue(value=repo_name))]
                )
            )
        except Exception:
            pass

        return {"status": "success", "message": f"Deleted repository '{repo_name}'"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/admin/api/paths")
async def api_get_paths():
    try:
        with get_db_connection() as conn:
            rows = conn.execute("SELECT id, path, type, recursive, enabled, category, repo, added_at FROM indexed_paths ORDER BY added_at DESC").fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/admin/api/paths")
async def api_add_path(request: Request):
    try:
        data = await request.json()
        path = data.get("path")
        ptype = data.get("type", "directory")
        recursive = int(data.get("recursive", 1))
        enabled = int(data.get("enabled", 1))
        category = data.get("category")
        repo = data.get("repo", "local") or "local"

        if not path or not os.path.exists(path):
            return JSONResponse(status_code=400, content={"error": f"Valid local path is required: {path}"})

        path = os.path.abspath(path)
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO indexed_paths (path, type, recursive, enabled, category, repo) VALUES (?, ?, ?, ?, ?, ?)",
                (path, ptype, recursive, enabled, category, repo)
            )
            conn.commit()

        threading.Thread(target=run_full_indexing, daemon=True).start()
        return {"status": "success", "message": f"Added local path: {path}"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.delete("/admin/api/paths/{path_id}")
async def api_delete_path(path_id: int):
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM indexed_paths WHERE id = ?", (path_id,))
            conn.commit()
        threading.Thread(target=run_full_indexing, daemon=True).start()
        return {"status": "success", "message": f"Deleted path ID {path_id}"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/admin/api/settings/token")
async def api_set_token(request: Request):
    try:
        data = await request.json()
        token = data.get("github_token", "").strip()
        set_metadata("github_token", token)
        eff_token = get_effective_github_token()
        rate_info = check_github_rate_limit(eff_token)
        return {
            "status": "success",
            "message": "GitHub token updated",
            "token_source": get_token_source(),
            "masked_token": mask_token(eff_token),
            "rate_limit": rate_info
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/admin/api/search/test")
async def api_test_search(request: Request):
    try:
        data = await request.json()
        query = data.get("query", "").strip()
        search_type = data.get("type", "code") # "code" or "doc"
        repo = data.get("repo") or None

        if not query:
            return JSONResponse(status_code=400, content={"error": "Query required"})

        hits = execute_hybrid_search(query_text=query, doc_type=search_type, repo=repo, limit=6)
        results = []
        for h in hits:
            results.append({
                "score": round(h.score, 4),
                "payload": h.payload
            })
        return {"query": query, "type": search_type, "results": results}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/admin/api/reindex")
async def api_trigger_reindex():
    if is_indexing:
        return JSONResponse(status_code=409, content={"error": "Indexing in progress"})
    threading.Thread(target=run_full_indexing, daemon=True).start()
    return {"status": "success", "message": "Re-indexing triggered"}

@app.get("/admin/api/browse")
async def api_browse_dir(path: str = "/"):
    resolved = os.path.abspath(path)
    if not os.path.exists(resolved):
        resolved = "/"
    try:
        entries = os.scandir(resolved)
        dirs = []
        files = []
        for e in entries:
            if e.name.startswith("."):
                continue
            if e.is_dir():
                dirs.append({"name": e.name, "path": os.path.abspath(e.path)})
            else:
                files.append({"name": e.name, "path": os.path.abspath(e.path)})
        dirs.sort(key=lambda x: x["name"].lower())
        files.sort(key=lambda x: x["name"].lower())
        return {
            "current_path": resolved,
            "parent_path": os.path.dirname(resolved) if resolved != "/" else "",
            "directories": dirs,
            "files": files
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/")
async def root_redirect():
    return RedirectResponse(url="/admin/")

app.mount("/admin", StaticFiles(directory="www", html=True), name="admin")

@app.get("/sse")
async def sse_endpoint(request: Request):
    logger.info("New SSE client connection requested.")
    async with sse_transport.connect_sse(request.scope, request.receive, request._send) as (read_stream, write_stream):
        initialization_options = mcp_server.create_initialization_options()
        async with AsyncExitStack() as stack:
            lifespan_context = await stack.enter_async_context(mcp_server.lifespan(mcp_server))
            session = await stack.enter_async_context(ServerSession(read_stream, write_stream, initialization_options))
            active_sessions.add(session)
            logger.info(f"Registered active session {session}. Total active: {len(active_sessions)}")
            try:
                async with anyio.create_task_group() as tg:
                    try:
                        async for message in session.incoming_messages:
                            tg.start_soon(mcp_server._handle_message, message, session, lifespan_context, False)
                    finally:
                        tg.cancel_scope.cancel()
            finally:
                active_sessions.discard(session)
                logger.info(f"Unregistered session {session}. Remaining active: {len(active_sessions)}")

app.mount("/messages", sse_transport.handle_post_message)

@app.get("/health")
async def health():
    return JSONResponse(content={"status": "healthy"})

@app.on_event("startup")
async def startup_event():
    global main_event_loop
    main_event_loop = asyncio.get_running_loop()
    logger.info("Notes & Code RAG Server starting up...")
    try:
        threading.Thread(target=run_full_indexing, daemon=True).start()
    except Exception as e:
        logger.error(f"Startup indexing error: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)
