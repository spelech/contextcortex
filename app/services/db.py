import os
import json
import sqlite3
import logging
import re
from typing import Optional, List, Dict, Any, Tuple, Union

logger = logging.getLogger("contextcortex.db")

def get_default_db_path() -> str:
    env_path = os.getenv("CACHE_DB_PATH")
    if env_path:
        return env_path
    # Check if /app/data is writable
    if os.path.exists("/app") and os.access("/app", os.W_OK):
        return "/app/data/index_cache.db"
    # Fallback to local directory
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "index_cache.db")

CACHE_DB_PATH = get_default_db_path()
try:
    os.makedirs(os.path.dirname(CACHE_DB_PATH), exist_ok=True)
except Exception:
    pass


def get_db_connection():
    conn = sqlite3.connect(CACHE_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn

def init_db(vault_path: str = "/docs"):
    with get_db_connection() as conn:
        # Local paths
        conn.execute("""
            CREATE TABLE IF NOT EXISTS indexed_paths (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE,
                type TEXT, -- "directory" or "file"
                recursive INTEGER, -- 1 or 0
                enabled INTEGER DEFAULT 1,
                category TEXT,
                repo TEXT DEFAULT 'local',
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Remote Git repositories
        conn.execute("""
            CREATE TABLE IF NOT EXISTS git_repositories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                url TEXT NOT NULL,
                branch TEXT DEFAULT 'main',
                commit_sha TEXT,
                auth_token TEXT,
                provider TEXT DEFAULT 'github',
                auth_user TEXT,
                enabled INTEGER DEFAULT 1,
                auto_sync INTEGER DEFAULT 1,
                webhook_secret TEXT,
                status TEXT DEFAULT 'pending',
                last_error TEXT,
                last_synced TIMESTAMP,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        try:
            conn.execute("ALTER TABLE git_repositories ADD COLUMN last_error TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE git_repositories ADD COLUMN provider TEXT DEFAULT 'github'")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE git_repositories ADD COLUMN auth_user TEXT")
        except Exception:
            pass
        try:
            repo_cols = [r[1] for r in conn.execute("PRAGMA table_info(git_repositories)").fetchall()]
            if "auto_sync" not in repo_cols:
                conn.execute("ALTER TABLE git_repositories ADD COLUMN auto_sync INTEGER DEFAULT 1")
            if "webhook_secret" not in repo_cols:
                conn.execute("ALTER TABLE git_repositories ADD COLUMN webhook_secret TEXT")
        except Exception:
            pass

        # Custom Git Host Credentials (for self-hosted GitLab, Gitea, or custom servers)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS git_host_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host TEXT UNIQUE NOT NULL,
                provider TEXT NOT NULL,
                auth_user TEXT,
                auth_token TEXT NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_git_host_credentials_host ON git_host_credentials(host)")

        # Indexed files
        conn.execute("""
            CREATE TABLE IF NOT EXISTS indexed_files (
                filepath TEXT PRIMARY KEY,
                repo TEXT DEFAULT 'local',
                doc_type TEXT DEFAULT 'doc', -- 'code' or 'doc'
                language TEXT DEFAULT 'text',
                commit_sha TEXT,
                mtime REAL,
                hash TEXT
            )
        """)

        try:
            conn.execute("ALTER TABLE indexed_files ADD COLUMN doc_type TEXT DEFAULT 'doc'")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE indexed_files ADD COLUMN language TEXT DEFAULT 'text'")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE indexed_files ADD COLUMN commit_sha TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE indexed_files ADD COLUMN mtime REAL")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE indexed_files ADD COLUMN hash TEXT")
        except Exception:
            pass

        # File summaries and topics
        conn.execute("""
            CREATE TABLE IF NOT EXISTS file_summaries (
                filepath TEXT PRIMARY KEY,
                repo TEXT DEFAULT 'local',
                title TEXT,
                folder TEXT,
                category TEXT,
                tags TEXT,
                headings TEXT,
                keywords TEXT,
                mtime REAL
            )
        """)

        # AST symbols for fast exact/prefix symbol lookup
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ast_symbols (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo TEXT NOT NULL,
                filepath TEXT NOT NULL,
                name TEXT NOT NULL,
                full_symbol TEXT,
                kind TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                signature TEXT,
                language TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ast_symbols_name ON ast_symbols(name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ast_symbols_repo ON ast_symbols(repo)")

        # System metadata (tokens, timestamps)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # Architecture Decision Records (ADR)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS architecture_decision_records (
                id TEXT PRIMARY KEY,
                repo TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                context TEXT NOT NULL,
                decision TEXT NOT NULL,
                consequences TEXT,
                superseded_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_adr_repo_status ON architecture_decision_records(repo, status)")

        # Custom prompts
        conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT NOT NULL,
                arguments_json TEXT,
                template TEXT NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Seed default prompts if empty
        try:
            prompt_count = conn.execute("SELECT count(*) FROM custom_prompts").fetchone()[0]
            if prompt_count == 0:
                default_prompts = [
                    (
                        "search_infrastructure_docs",
                        "Workflow to search system infrastructure documentation, container mappings, or network routes.",
                        json.dumps([{"name": "topic", "description": "The specific infrastructure topic to search for", "required": True}]),
                        "Please perform a search using the search_docs tool for topic '{topic}' and summarize the matching container mappings, port numbers, reverse proxy routes, or setup instructions."
                    ),
                    (
                        "find_implementation_symbol",
                        "Workflow to locate functions, classes, and logic across registered codebases.",
                        json.dumps([{"name": "symbol", "description": "Function or class name to find", "required": True}, {"name": "repo", "description": "Target repository (optional)", "required": False}]),
                        "Please use find_symbol for '{symbol}' in repo '{repo}' and inspect its declaration, line numbers, and implementation details."
                    )
                ]
                conn.executemany(
                    "INSERT OR IGNORE INTO custom_prompts (name, description, arguments_json, template) VALUES (?, ?, ?, ?)",
                    default_prompts
                )
        except Exception as pe:
            logger.error(f"Failed to seed default prompts: {pe}")

        # Seed default vault path if paths table is empty
        try:
            conn.execute("DELETE FROM indexed_paths WHERE path = '/notes'")
            count = conn.execute("SELECT count(*) FROM indexed_paths").fetchone()[0]
            if count == 0 and os.path.exists(vault_path):
                conn.execute(
                    "INSERT OR IGNORE INTO indexed_paths (path, type, recursive, enabled, category, repo) VALUES (?, ?, ?, ?, ?, ?)",
                    (os.path.abspath(vault_path), "directory", 1, 1, "default", "vault")
                )
        except Exception as se:
            logger.error(f"Failed to seed default vault path: {se}")

        # Seed default vector store settings if not already present
        try:
            default_cfg = _resolve_default_vector_store_config(conn)
            for key, val in [
                ("vector_store_provider", default_cfg["provider"]),
                ("vector_store_mode", default_cfg["mode"]),
                ("vector_store_storage_path", default_cfg["storage_path"]),
                ("vector_store_url", default_cfg["url"]),
                ("vector_store_collection", default_cfg["collection"]),
            ]:
                row = conn.execute("SELECT value FROM system_metadata WHERE key = ?", (key,)).fetchone()
                if row is None:
                    conn.execute("INSERT INTO system_metadata (key, value) VALUES (?, ?)", (key, str(val)))
        except Exception as ve:
            logger.error(f"Failed to seed vector store configuration: {ve}")

        conn.commit()

# Metadata Helpers
def get_metadata(key: str, default: Optional[str] = None) -> Optional[str]:
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT value FROM system_metadata WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default
    except Exception:
        return default

def set_metadata(key: str, value: str):
    try:
        with get_db_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO system_metadata (key, value) VALUES (?, ?)", (key, value))
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to set metadata key {key}: {e}")

def get_default_vector_storage_path() -> str:
    env_path = os.getenv("VECTOR_STORE_STORAGE_PATH")
    if env_path:
        return env_path
    if os.path.exists("/app") and os.access("/app", os.W_OK):
        return "/app/data/vector_storage"
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "vector_storage")

def _resolve_default_vector_store_config(conn: Optional[sqlite3.Connection] = None) -> Dict[str, str]:
    """Helper to resolve default vector store config from env vars or defaults."""
    provider = os.getenv("VECTOR_STORE") or os.getenv("VECTOR_STORE_PROVIDER") or "qdrant"
    provider = provider.lower().strip()

    mode = os.getenv("VECTOR_STORE_MODE")
    if not mode:
        if provider == "qdrant":
            q_url = os.getenv("QDRANT_URL")
            if q_url and q_url.strip() and not q_url.strip().startswith(":memory:"):
                mode = "remote"
            else:
                mode = "embedded"
        elif provider in ("chroma", "chromadb"):
            c_url = os.getenv("CHROMA_URL")
            if c_url and c_url.strip():
                mode = "remote"
            else:
                mode = "embedded"
        else:
            mode = "embedded"
    mode = mode.lower().strip()

    storage_path = os.getenv("VECTOR_STORE_STORAGE_PATH") or get_default_vector_storage_path()

    if provider == "qdrant":
        url = os.getenv("VECTOR_STORE_URL") or os.getenv("QDRANT_URL") or ""
    elif provider in ("chroma", "chromadb"):
        url = os.getenv("VECTOR_STORE_URL") or os.getenv("CHROMA_URL") or ""
    else:
        url = os.getenv("VECTOR_STORE_URL") or ""


    collection = os.getenv("VECTOR_STORE_COLLECTION") or os.getenv("COLLECTION_NAME") or "knowledge_rag_v1"

    return {
        "provider": provider,
        "mode": mode,
        "storage_path": storage_path,
        "url": url.strip(),
        "collection": collection.strip(),
    }

def get_vector_store_db_config() -> Dict[str, str]:
    """
    Returns the vector store configuration from system_metadata,
    falling back to default resolution if not set in DB.
    """
    provider = get_metadata("vector_store_provider")
    mode = get_metadata("vector_store_mode")
    storage_path = get_metadata("vector_store_storage_path")
    url = get_metadata("vector_store_url")
    collection = get_metadata("vector_store_collection")

    default_cfg = _resolve_default_vector_store_config()

    return {
        "provider": (provider or default_cfg["provider"]).lower().strip(),
        "mode": (mode or default_cfg["mode"]).lower().strip(),
        "storage_path": storage_path or default_cfg["storage_path"],
        "url": (url if url is not None else default_cfg["url"]).strip(),
        "collection": (collection or default_cfg["collection"]).strip(),
    }

def set_vector_store_db_config(
    provider: Optional[str] = None,
    mode: Optional[str] = None,
    storage_path: Optional[str] = None,
    url: Optional[str] = None,
    collection: Optional[str] = None,
):
    """
    Saves vector store configuration settings into system_metadata.
    """
    if provider is not None:
        set_metadata("vector_store_provider", provider.lower().strip())
    if mode is not None:
        set_metadata("vector_store_mode", mode.lower().strip())
    if storage_path is not None:
        set_metadata("vector_store_storage_path", storage_path.strip())
    if url is not None:
        set_metadata("vector_store_url", url.strip())
    if collection is not None:
        set_metadata("vector_store_collection", collection.strip())

# Multi-Provider & Git Host Credential Management

def list_git_host_credentials() -> List[Dict[str, Any]]:
    try:
        with get_db_connection() as conn:
            rows = conn.execute("SELECT * FROM git_host_credentials ORDER BY host ASC").fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to list git host credentials: {e}")
        return []

def get_git_host_credential(host: str) -> Optional[Dict[str, Any]]:
    if not host:
        return None
    try:
        clean = host.strip().lower()
        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM git_host_credentials WHERE host = ?", (clean,)).fetchone()
            return dict(row) if row else None
    except Exception:
        return None

def save_git_host_credential(host: str, provider: str, auth_token: str, auth_user: Optional[str] = None):
    try:
        clean_host = host.strip().lower()
        clean_host = re.sub(r"^https?://", "", clean_host).split("/")[0]
        with get_db_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO git_host_credentials (host, provider, auth_user, auth_token)
                   VALUES (?, ?, ?, ?)""",
                (clean_host, provider.lower().strip(), auth_user.strip() if auth_user else None, auth_token.strip())
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to save git host credential for {host}: {e}")
        raise

def delete_git_host_credential(id_or_host: Any):
    try:
        with get_db_connection() as conn:
            if isinstance(id_or_host, int) or (isinstance(id_or_host, str) and id_or_host.isdigit()):
                conn.execute("DELETE FROM git_host_credentials WHERE id = ?", (int(id_or_host),))
            else:
                clean_host = str(id_or_host).strip().lower()
                clean_host = re.sub(r"^https?://", "", clean_host).split("/")[0]
                conn.execute("DELETE FROM git_host_credentials WHERE host = ?", (clean_host,))
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to delete git host credential {id_or_host}: {e}")
        raise

def extract_host_from_url(url: str) -> str:
    if not url:
        return ""
    clean = re.sub(r"^(git@|https?://)", "", url.strip())
    if ":" in clean and "/" not in clean.split(":")[0]:
        host_part = clean.split(":")[0]
    else:
        host_part = clean.split("/")[0]
    return host_part.lower()

def get_effective_git_token(
    git_url: str, 
    override_token: Optional[str] = None, 
    override_user: Optional[str] = None,
    provider: Optional[str] = None
) -> Tuple[Optional[str], Optional[str], str]:
    """
    Resolves (token, username, source_description) using hierarchy:
    1. Explicit override token / user on repo
    2. Host Vault matching repository domain
    3. Global provider token from database
    4. Environment variables
    """
    if override_token and override_token.strip():
        return override_token.strip(), override_user.strip() if override_user else None, "Repository Override"
    
    host = extract_host_from_url(git_url)
    if host:
        host_cred = get_git_host_credential(host)
        if host_cred and host_cred.get("auth_token"):
            return host_cred["auth_token"], host_cred.get("auth_user"), f"Host Vault ({host})"

    prov = (provider or "").lower()
    if not prov:
        if "gitlab" in host:
            prov = "gitlab"
        elif "gitea" in host or "forgejo" in host:
            prov = "gitea"
        elif "bitbucket" in host:
            prov = "bitbucket"
        elif "github" in host:
            prov = "github"
        else:
            prov = "generic"

    # Global DB tokens
    db_token = get_metadata(f"{prov}_token") or (get_metadata("github_token") if prov == "github" else None)
    if db_token and db_token.strip():
        return db_token.strip(), override_user, f"Database ({prov.capitalize()})"

    # Environment variables
    env_keys = {
        "github": ["GITHUB_TOKEN", "GH_TOKEN"],
        "gitlab": ["GITLAB_TOKEN", "GL_TOKEN"],
        "gitea": ["GITEA_TOKEN", "FORGEJO_TOKEN"],
        "bitbucket": ["BITBUCKET_TOKEN", "BITBUCKET_APP_PASSWORD"]
    }.get(prov, [])

    for k in env_keys:
        val = os.getenv(k)
        if val and val.strip():
            return val.strip(), override_user, f"Environment Variable ({k})"

    return None, override_user, "None"

def get_auto_sync_interval() -> int:
    try:
        val = get_metadata("auto_sync_interval_mins", "15")
        return int(val)
    except (ValueError, TypeError):
        return 15

def set_auto_sync_interval(interval_mins: int) -> None:
    set_metadata("auto_sync_interval_mins", str(max(0, interval_mins)))

def get_global_webhook_secret() -> Optional[str]:
    sec = get_metadata("global_webhook_secret", "")
    return sec.strip() if sec and sec.strip() else None

def set_global_webhook_secret(secret: Optional[str]) -> None:
    set_metadata("global_webhook_secret", secret.strip() if secret else "")

def set_repo_auto_sync(repo_id: int, enabled: bool) -> bool:
    with get_db_connection() as conn:
        res = conn.execute("UPDATE git_repositories SET auto_sync = ? WHERE id = ?", (1 if enabled else 0, repo_id))
        conn.commit()
        return res.rowcount > 0

def list_auto_sync_repos() -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        rows = conn.execute("SELECT id, name, url, branch, commit_sha, auth_token, auth_user, provider, auto_sync, webhook_secret FROM git_repositories WHERE auto_sync = 1").fetchall()
        return [dict(r) for r in rows]

# Architecture Decision Records (ADR) Helpers

def get_adr(adr_id: str, repo: Optional[str] = None) -> Optional[Dict[str, Any]]:
    try:
        with get_db_connection() as conn:
            if repo:
                row = conn.execute(
                    "SELECT * FROM architecture_decision_records WHERE id = ? AND repo = ?",
                    (adr_id, repo)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM architecture_decision_records WHERE id = ?",
                    (adr_id,)
                ).fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get ADR {adr_id}: {e}")
        return None

def list_adrs(repo: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        with get_db_connection() as conn:
            query = "SELECT * FROM architecture_decision_records WHERE repo = ?"
            params = [repo]
            if status:
                query += " AND status = ?"
                params.append(status.upper().strip())
            query += " ORDER BY id ASC"
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to list ADRs for repo {repo}: {e}")
        return []

def create_adr(
    repo: str,
    title: str,
    status: str = "PROPOSED",
    context: str = "",
    decision: str = "",
    consequences: Optional[str] = None,
    superseded_by: Optional[str] = None,
    adr_id: Optional[str] = None
) -> Dict[str, Any]:
    try:
        with get_db_connection() as conn:
            if not adr_id:
                # Generate next ADR id like 'ADR-001' or count-based per repo
                count_row = conn.execute(
                    "SELECT count(*) FROM architecture_decision_records WHERE repo = ?",
                    (repo,)
                ).fetchone()
                seq = (count_row[0] if count_row else 0) + 1
                adr_id = f"ADR-{seq:03d}"
                # Ensure global uniqueness across the table
                while conn.execute("SELECT 1 FROM architecture_decision_records WHERE id = ?", (adr_id,)).fetchone():
                    seq += 1
                    adr_id = f"ADR-{seq:03d}"

            status_clean = status.upper().strip()
            conn.execute(
                """INSERT INTO architecture_decision_records (id, repo, title, status, context, decision, consequences, superseded_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                (adr_id, repo, title, status_clean, context, decision, consequences, superseded_by)
            )
            conn.commit()
            return get_adr(adr_id, repo) or {}
    except Exception as e:
        logger.error(f"Failed to create ADR: {e}")
        raise

def update_adr(
    adr_id: str,
    repo: str,
    title: Optional[str] = None,
    status: Optional[str] = None,
    context: Optional[str] = None,
    decision: Optional[str] = None,
    consequences: Optional[str] = None,
    superseded_by: Optional[str] = None
) -> Dict[str, Any]:
    try:
        existing = get_adr(adr_id, repo)
        if not existing:
            raise ValueError(f"ADR '{adr_id}' not found for repository '{repo}'.")

        new_title = title if title is not None else existing["title"]
        new_status = status.upper().strip() if status is not None else existing["status"]
        new_context = context if context is not None else existing["context"]
        new_decision = decision if decision is not None else existing["decision"]
        new_consequences = consequences if consequences is not None else existing["consequences"]
        new_superseded_by = superseded_by if superseded_by is not None else existing["superseded_by"]

        with get_db_connection() as conn:
            conn.execute(
                """UPDATE architecture_decision_records
                   SET title = ?, status = ?, context = ?, decision = ?, consequences = ?, superseded_by = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND repo = ?""",
                (new_title, new_status, new_context, new_decision, new_consequences, new_superseded_by, adr_id, repo)
            )
            conn.commit()

        return get_adr(adr_id, repo) or {}
    except Exception as e:
        logger.error(f"Failed to update ADR {adr_id}: {e}")
        raise

def supersede_adr(old_id: str, new_id: str, repo: str) -> Dict[str, Any]:
    try:
        old_adr = get_adr(old_id, repo)
        if not old_adr:
            raise ValueError(f"Target ADR '{old_id}' to supersede does not exist in repo '{repo}'.")
        new_adr = get_adr(new_id, repo)
        if not new_adr:
            raise ValueError(f"Superseding ADR '{new_id}' does not exist in repo '{repo}'.")

        with get_db_connection() as conn:
            conn.execute(
                """UPDATE architecture_decision_records
                   SET status = 'SUPERSEDED', superseded_by = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND repo = ?""",
                (new_id, old_id, repo)
            )
            conn.commit()

        return get_adr(old_id, repo) or {}
    except Exception as e:
        logger.error(f"Failed to supersede ADR {old_id} with {new_id}: {e}")
        raise

def upsert_adr(
    adr_id: str,
    repo: str,
    title: str,
    status: str,
    context: str,
    decision: str,
    consequences: Optional[str] = None,
    superseded_by: Optional[str] = None
) -> Dict[str, Any]:
    try:
        status_clean = status.upper().strip()
        with get_db_connection() as conn:
            conn.execute(
                """INSERT INTO architecture_decision_records (id, repo, title, status, context, decision, consequences, superseded_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                   ON CONFLICT(id) DO UPDATE SET
                       repo = excluded.repo,
                       title = excluded.title,
                       status = excluded.status,
                       context = excluded.context,
                       decision = excluded.decision,
                       consequences = excluded.consequences,
                       superseded_by = excluded.superseded_by,
                       updated_at = CURRENT_TIMESTAMP""",
                (adr_id, repo, title, status_clean, context, decision, consequences, superseded_by)
            )
            conn.commit()
        return get_adr(adr_id, repo) or {}
    except Exception as e:
        logger.error(f"Failed to upsert ADR {adr_id}: {e}")
        raise
