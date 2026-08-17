import os
import json
import sqlite3
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger("notes-rag-mcp.db")

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
                enabled INTEGER DEFAULT 1,
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

# Global GitHub token resolution
def get_effective_github_token(override_token: Optional[str] = None) -> Optional[str]:
    if override_token and override_token.strip():
        return override_token.strip()
    db_token = get_metadata("github_token")
    if db_token and db_token.strip():
        return db_token.strip()
    env_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if env_token and env_token.strip():
        return env_token.strip()
    return None

def get_token_source() -> str:
    db_token = get_metadata("github_token")
    if db_token and db_token.strip():
        return "Database"
    env_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if env_token and env_token.strip():
        return "Environment Variable"
    return "None"
