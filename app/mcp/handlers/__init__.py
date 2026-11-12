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
    handle_search_infrastructure_docs,
    handle_onboard_repository,
    handle_triage_error,
    handle_investigate_change_impact,
    handle_get_recent_changes,
)
from app.mcp.handlers.resource_handlers import (
    handle_catalog_summary,
    handle_repo_summary_resource,
    handle_repo_architecture_resource,
    handle_repo_files_resource,
    handle_repo_routes_resource,
    handle_repo_adrs_resource,
)
from app.mcp.handlers.architecture_handlers import (
    handle_get_architecture,
    handle_manage_adr,
)
from app.mcp.handlers.storage_handlers import (
    handle_manage_local_file,
    handle_what_is_ingested,
)
from app.mcp.handlers.file_handlers import (
    handle_read_file,
    handle_summarize_file,
)
from app.mcp.handlers.grep_handlers import (
    handle_grep_code,
)
from app.mcp.handlers.diagnostic_handlers import (
    handle_diagnose_issue,
)
from app.mcp.handlers.script_handlers import (
    handle_execute_script,
    handle_code_mode_sdk_resource,
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
    "handle_repo_summary_resource",
    "handle_repo_architecture_resource",
    "handle_repo_files_resource",
    "handle_repo_routes_resource",
    "handle_repo_adrs_resource",
    "handle_search_infrastructure_docs",
    "handle_onboard_repository",
    "handle_triage_error",
    "handle_investigate_change_impact",
    "handle_get_recent_changes",
    "handle_get_architecture",
    "handle_manage_adr",
    "handle_manage_local_file",
    "handle_what_is_ingested",
    "handle_read_file",
    "handle_summarize_file",
    "handle_grep_code",
    "handle_diagnose_issue",
    "handle_execute_script",
    "handle_code_mode_sdk_resource",
]
