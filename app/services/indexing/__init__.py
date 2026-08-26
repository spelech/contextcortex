from app.services.indexing.state import (
    VAULT_PATH,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    QDRANT_URL,
    COLLECTION_NAME,
    active_sessions,
    main_event_loop,
    notify_list_changed,
    trigger_list_changed_notification,
    indexing_lock,
    is_indexing,
    ensure_collection,
)
from app.services.indexing.processor import (
    get_chunk_uuid,
    extract_keywords_from_text,
    get_dynamic_catalog_description,
    process_file_content,
    compute_text_hash,
    MAX_FILE_SIZE_BYTES,
)
from app.services.indexing.local_syncer import sync_local_paths
from app.services.indexing.git_syncer import (
    compute_git_repo_delta,
    sync_single_git_repo,
    run_full_indexing,
)

__all__ = [
    "VAULT_PATH",
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "QDRANT_URL",
    "COLLECTION_NAME",
    "active_sessions",
    "main_event_loop",
    "notify_list_changed",
    "trigger_list_changed_notification",
    "indexing_lock",
    "is_indexing",
    "ensure_collection",
    "get_chunk_uuid",
    "extract_keywords_from_text",
    "get_dynamic_catalog_description",
    "process_file_content",
    "compute_text_hash",
    "MAX_FILE_SIZE_BYTES",
    "sync_local_paths",
    "compute_git_repo_delta",
    "sync_single_git_repo",
    "run_full_indexing",
]
