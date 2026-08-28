from app.mcp.handlers.search_handlers import (
    handle_search_code,
    handle_search_docs,
)
from app.mcp.handlers.symbol_handlers import (
    handle_find_symbol,
    handle_trace_path,
    handle_get_file_outline,
    handle_find_implementation_symbol,
)
from app.mcp.handlers.route_handlers import (
    handle_find_routes,
    handle_find_api_callers,
)
from app.mcp.handlers.repo_handlers import (
    handle_list_repositories,
    handle_sync_repository,
    handle_index_status,
    handle_catalog_summary,
    handle_search_infrastructure_docs,
)
from app.mcp.handlers.architecture_handlers import (
    handle_get_architecture,
    handle_manage_adr,
)
from app.mcp.handlers.storage_handlers import (
    handle_manage_local_file,
    handle_what_is_ingested,
)

__all__ = [
    "handle_search_code",
    "handle_search_docs",
    "handle_find_symbol",
    "handle_trace_path",
    "handle_get_file_outline",
    "handle_find_implementation_symbol",
    "handle_find_routes",
    "handle_find_api_callers",
    "handle_list_repositories",
    "handle_sync_repository",
    "handle_index_status",
    "handle_catalog_summary",
    "handle_search_infrastructure_docs",
    "handle_get_architecture",
    "handle_manage_adr",
    "handle_manage_local_file",
    "handle_what_is_ingested",
]
