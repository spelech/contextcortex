"""
Canonical SQLAlchemy Core Schema definitions for ContextCortex.
Single source of truth for all relational database tables across SQLite and PostgreSQL.
"""

from typing import Dict
from sqlalchemy import (
    MetaData,
    Table,
    Column,
    Integer,
    String,
    Text,
    Float,
    DateTime,
    Boolean,
    ForeignKey,
    Index,
    func,
)

metadata = MetaData()

# 1. Indexed Paths
indexed_paths = Table(
    "indexed_paths",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("path", Text, unique=True, nullable=False),
    Column("type", Text, nullable=True),
    Column("recursive", Integer, default=1),
    Column("enabled", Integer, default=1, server_default="1"),
    Column("category", Text, nullable=True),
    Column("repo", Text, default="local", server_default="local"),
    Column("added_at", DateTime, server_default=func.current_timestamp()),
)

# 2. Git Repositories
git_repositories = Table(
    "git_repositories",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", Text, unique=True, nullable=False),
    Column("url", Text, nullable=False),
    Column("branch", Text, default="main", server_default="main"),
    Column("commit_sha", Text, nullable=True),
    Column("auth_token", Text, nullable=True),
    Column("provider", Text, default="github", server_default="github"),
    Column("auth_user", Text, nullable=True),
    Column("enabled", Integer, default=1, server_default="1"),
    Column("auto_sync", Integer, default=1, server_default="1"),
    Column("webhook_secret", Text, nullable=True),
    Column("status", Text, default="pending", server_default="pending"),
    Column("last_error", Text, nullable=True),
    Column("last_synced", DateTime, nullable=True),
    Column("added_at", DateTime, server_default=func.current_timestamp()),
)

# 3. Git Host Credentials
git_host_credentials = Table(
    "git_host_credentials",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("host", Text, unique=True, nullable=False),
    Column("provider", Text, nullable=False),
    Column("auth_user", Text, nullable=True),
    Column("auth_token", Text, nullable=False),
    Column("added_at", DateTime, server_default=func.current_timestamp()),
    Index("idx_git_host_credentials_host", "host"),
)

# 4. Indexed Files
indexed_files = Table(
    "indexed_files",
    metadata,
    Column("filepath", Text, primary_key=True),
    Column("repo", Text, default="local", server_default="local"),
    Column("doc_type", Text, default="doc", server_default="doc"),
    Column("language", Text, default="text", server_default="text"),
    Column("commit_sha", Text, nullable=True),
    Column("mtime", Float, nullable=True),
    Column("hash", Text, nullable=True),
    Index("idx_indexed_files_repo_hash", "repo", "hash"),
    Index("idx_indexed_files_repo", "repo"),
)

# 5. File Summaries
file_summaries = Table(
    "file_summaries",
    metadata,
    Column("filepath", Text, primary_key=True),
    Column("repo", Text, default="local", server_default="local"),
    Column("title", Text, nullable=True),
    Column("folder", Text, nullable=True),
    Column("category", Text, nullable=True),
    Column("tags", Text, nullable=True),
    Column("headings", Text, nullable=True),
    Column("keywords", Text, nullable=True),
    Column("mtime", Float, nullable=True),
)

# 6. Embedding Cache
embedding_cache = Table(
    "embedding_cache",
    metadata,
    Column("chunk_hash", Text, primary_key=True, nullable=False),
    Column("dense_vector", Text, nullable=True),
    Column("sparse_indices", Text, nullable=True),
    Column("sparse_values", Text, nullable=True),
    Column("model_name", Text, primary_key=True, nullable=False),
    Column("created_at", DateTime, server_default=func.current_timestamp()),
    Index("idx_embedding_cache_model", "model_name"),
    Index("idx_embedding_cache_model_hash", "model_name", "chunk_hash"),
)

# 7. AST Symbols
ast_symbols = Table(
    "ast_symbols",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("repo", Text, nullable=False),
    Column("filepath", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("full_symbol", Text, nullable=True),
    Column("kind", Text, nullable=False),
    Column("start_line", Integer, nullable=False),
    Column("end_line", Integer, nullable=False),
    Column("signature", Text, nullable=True),
    Column("language", Text, nullable=True),
    Index("idx_ast_symbols_name", "name"),
    Index("idx_ast_symbols_repo", "repo"),
)

# 8. AST Relationships
ast_relationships = Table(
    "ast_relationships",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("repo", Text, nullable=False),
    Column("source_symbol_id", Integer, ForeignKey("ast_symbols.id", ondelete="CASCADE"), nullable=True),
    Column("source_filepath", Text, nullable=False),
    Column("source_symbol", Text, nullable=False),
    Column("target_symbol", Text, nullable=False),
    Column("relationship_type", Text, nullable=False),
    Column("line_number", Integer, nullable=False),
    Index("idx_ast_rel_repo_source", "repo", "source_symbol"),
    Index("idx_ast_rel_repo_target", "repo", "target_symbol"),
    Index("idx_ast_rel_type", "relationship_type"),
)

# 9. API Routes
api_routes = Table(
    "api_routes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("repo", Text, nullable=False),
    Column("filepath", Text, nullable=False),
    Column("framework", Text, nullable=False),
    Column("http_method", Text, nullable=False),
    Column("path_pattern", Text, nullable=False),
    Column("handler_symbol", Text, nullable=True),
    Column("start_line", Integer, nullable=False),
    Column("end_line", Integer, nullable=False),
    Column("created_at", DateTime, server_default=func.current_timestamp()),
    Index("idx_api_routes_repo_path", "repo", "path_pattern"),
    Index("idx_api_routes_method", "http_method"),
)

# 10. API Client Calls
api_client_calls = Table(
    "api_client_calls",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("repo", Text, nullable=False),
    Column("filepath", Text, nullable=False),
    Column("http_method", Text, nullable=True),
    Column("url_pattern", Text, nullable=False),
    Column("caller_symbol", Text, nullable=True),
    Column("line_number", Integer, nullable=False),
    Column("created_at", DateTime, server_default=func.current_timestamp()),
    Index("idx_api_calls_url", "url_pattern"),
)

# 11. System Metadata
system_metadata = Table(
    "system_metadata",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value", Text, nullable=True),
)

# 12. Architecture Decision Records
architecture_decision_records = Table(
    "architecture_decision_records",
    metadata,
    Column("id", Text, primary_key=True),
    Column("repo", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("context", Text, nullable=False),
    Column("decision", Text, nullable=False),
    Column("consequences", Text, nullable=True),
    Column("superseded_by", Text, nullable=True),
    Column("created_at", DateTime, server_default=func.current_timestamp()),
    Column("updated_at", DateTime, server_default=func.current_timestamp()),
    Index("idx_adr_repo_status", "repo", "status"),
)

# 13. Custom Prompts
custom_prompts = Table(
    "custom_prompts",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", Text, unique=True, nullable=False),
    Column("description", Text, nullable=False),
    Column("arguments_json", Text, nullable=True),
    Column("template", Text, nullable=False),
    Column("added_at", DateTime, server_default=func.current_timestamp()),
)

# 14. API Keys (MCP 2026-07-28 Auth & RBAC)
api_keys = Table(
    "api_keys",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(100), nullable=False),
    Column("key_prefix", String(16), nullable=False),
    Column("key_hash", String(64), unique=True, nullable=False),
    Column("role", String(20), nullable=False, default="viewer", server_default="viewer"),
    Column("group_name", String(100), nullable=True),
    Column("expires_at", DateTime, nullable=True),
    Column("created_at", DateTime, server_default=func.current_timestamp()),
    Column("last_used_at", DateTime, nullable=True),
    Column("is_active", Boolean, default=True, server_default="1"),
    Index("idx_api_keys_hash", "key_hash"),
    Index("idx_api_keys_prefix", "key_prefix"),
)

# Dictionary mapping table names to SQLAlchemy Table objects
TABLES: Dict[str, Table] = {t.name: t for t in metadata.tables.values()}

__all__ = [
    "metadata",
    "TABLES",
    "indexed_paths",
    "git_repositories",
    "git_host_credentials",
    "indexed_files",
    "file_summaries",
    "embedding_cache",
    "ast_symbols",
    "ast_relationships",
    "api_routes",
    "api_client_calls",
    "system_metadata",
    "architecture_decision_records",
    "custom_prompts",
    "api_keys",
]
