import os
import uuid
import json
import re
import logging
from collections import Counter
from typing import Tuple, List, Dict, Any, Optional
import frontmatter
from app.services.database import *
from app.services.chunking import *
from app.services.embeddings import *
from app.services.git_manager import *
from app.services.vector_store import (
    VectorStore, VectorDocument, VectorSearchResult,
    VectorStoreManager, get_vector_store
)
from app.services.indexing.state import (
    VAULT_PATH, CHUNK_SIZE, CHUNK_OVERLAP, QDRANT_URL, COLLECTION_NAME,
    trigger_list_changed_notification, ensure_collection
)

logger = logging.getLogger('contextcortex.indexer')
import sys

def _get_indexer_attr(name, default):
    mod = sys.modules.get("app.services.indexer")
    return getattr(mod, name, default) if mod else default


def get_chunk_uuid(repo: str, rel_path: str, index: int) -> str:
    namespace = uuid.uuid5(uuid.NAMESPACE_DNS, "contextcortex.lan")
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
    category_override: Optional[str] = None,
    provider: Optional[str] = None
) -> Tuple[List[VectorDocument], List[Dict[str, Any]], Tuple, List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Processes a single file into vector documents, AST symbols, summary metadata, AST relationships, API routes, and client calls."""
    language = detect_language(filepath)
    title = os.path.basename(filepath)
    folder = os.path.dirname(rel_path) or "root"
    category = category_override or folder
    tags = []
    meta = {}

    points: List[VectorDocument] = []
    ast_symbols = []
    ast_relationships = []
    api_routes = []
    api_calls = []
    headings = []

    if doc_type == "doc":
        if filepath.endswith((".md", ".txt")):
            # Check if file is in standard ADR directories or follows ADR naming
            norm_rel = rel_path.replace("\\", "/").lower()
            if any(adr_dir in norm_rel for adr_dir in ["docs/adr/", "docs/decisions/", ".adr/", "doc/architecture/decisions/", "/adr/"]):
                try:
                    from app.services.adr import sync_adr_file
                    sync_adr_file(filepath=filepath, repo=repo, content=content)
                except Exception as adr_e:
                    logger.error(f"Failed to auto-ingest ADR {filepath}: {adr_e}")

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
            batch_vecs = _get_indexer_attr("get_hybrid_embeddings_batch", get_hybrid_embeddings_batch)(texts_to_embed)
            for idx, chunk in enumerate(valid_chunks):
                point_id = get_chunk_uuid(repo, rel_path, idx)
                github_url = format_git_permalink(git_url, commit_sha, rel_path, chunk.get("start_line"), chunk.get("end_line"), provider=provider)
                
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
                    permalink_url=github_url,
                ))

    else: # Code file
        ast_result = extract_symbols_and_chunks(content, filepath, repo=repo, max_chunk_chars=CHUNK_SIZE)
        chunks = [c.model_dump() for c in ast_result.chunks]
        ast_symbols = [s.model_dump() for s in ast_result.symbols]
        ast_relationships = [r.model_dump() for r in ast_result.relationships]
        api_routes = [r.model_dump() for r in ast_result.api_routes]
        api_calls = [c.model_dump() for c in ast_result.api_client_calls]
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
            batch_vecs = _get_indexer_attr("get_hybrid_embeddings_batch", get_hybrid_embeddings_batch)(texts_to_embed)
            for idx, chunk in enumerate(valid_chunks):
                point_id = get_chunk_uuid(repo, rel_path, idx)
                github_url = format_git_permalink(git_url, commit_sha, rel_path, chunk.get("start_line"), chunk.get("end_line"), provider=provider)
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
                    permalink_url=github_url,
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

    return points, ast_symbols, summary_tuple, ast_relationships, api_routes, api_calls

# ----------------------------------------------------
# INCREMENTAL SCAN & SYNC ENGINE
# ----------------------------------------------------

