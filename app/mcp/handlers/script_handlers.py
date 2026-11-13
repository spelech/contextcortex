"""
Code Mode for ContextCortex: the `execute_script` tool and the `contextcortex://code-mode/sdk.d.ts` resource.

Same pattern as Code Mode in model-context-gateway: the agent sends one async JavaScript body; the script calls
ContextCortex tools in a sandbox and returns only the final, small result. Every tool call from a script goes
through the normal tool handler, so the normal permission checks apply to each call.
"""

import inspect
import json
import logging
import os
from typing import Annotated, Any, Dict, Optional

from pydantic import Field

from app.services.auth import ForbiddenError, Role, enforce_tool_permission
from app.services.script_sandbox import ScriptLimits, ScriptToolError, code_mode_available, run_script

logger = logging.getLogger("contextcortex.mcp.code_mode")

TOOL_NAME = "execute_script"
SDK_URI = "contextcortex://code-mode/sdk.d.ts"
MAX_SCRIPT_CHARS = 50000
MAX_RESULT_CHARS = 100000


def _env_number(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.getenv(name, default))
    except ValueError:
        value = default
    return max(low, min(high, value))


def code_mode_limits() -> ScriptLimits:
    """Limits from the environment (same defaults and ranges as model-context-gateway)."""
    return ScriptLimits(
        timeout_seconds=_env_number("CODE_MODE_TIMEOUT_SECONDS", 30, 1, 300),
        max_tool_calls=int(_env_number("CODE_MODE_MAX_TOOL_CALLS", 50, 1, 500)),
        max_memory_bytes=int(_env_number("CODE_MODE_MAX_MEMORY_MB", 64, 8, 512)) * 1024 * 1024,
    )


def code_mode_enabled() -> bool:
    return os.getenv("CODE_MODE_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


def _tool_handlers() -> Dict[str, Any]:
    from app.mcp.tools import get_tool_definitions

    return {name: handler for name, handler, _desc in get_tool_definitions() if name != TOOL_NAME}


async def call_tool_from_script(name: str, tool_args: Dict[str, Any]) -> Any:
    """Runs one tool for a script: checks the name and arguments, calls the handler, and unboxes the JSON result."""
    if name == TOOL_NAME:
        raise ScriptToolError("Recursive execute_script calls are not permitted.")
    handlers = _tool_handlers()
    handler = handlers.get(name)
    if handler is None:
        raise ScriptToolError(f"Unknown tool '{name}'. Tools: {', '.join(sorted(handlers))}")
    params = inspect.signature(handler).parameters
    unknown = sorted(set(tool_args) - set(params))
    if unknown:
        raise ScriptToolError(f"Unknown arguments for {name}: {', '.join(unknown)}. Valid: {', '.join(params)}")
    missing = [p for p, spec in params.items() if spec.default is inspect.Parameter.empty and p not in tool_args]
    if missing:
        raise ScriptToolError(f"Missing arguments for {name}: {', '.join(missing)}")
    raw = await handler(**tool_args)
    value = raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except ValueError:
            return raw
    if isinstance(value, dict) and value.get("error"):
        message = value.get("message")
        raise ScriptToolError(f"{name}: {value['error']}" + (f": {message}" if message else ""))
    return value


def _response(payload: Dict[str, Any]) -> str:
    text = json.dumps(payload, separators=(",", ":"), default=str)
    if len(text) <= MAX_RESULT_CHARS:
        return text
    preview = json.dumps(payload.get("result"), separators=(",", ":"), default=str)[:MAX_RESULT_CHARS]
    return json.dumps({**payload, "result": None, "truncated": True, "resultPreview": preview,
                       "hint": "Return less data: select fields, slice lists, or summarize in the script."},
                      separators=(",", ":"))


async def handle_execute_script(
    script: Annotated[Optional[str], Field(description=(
        "Async JavaScript body. It runs inside an async function, so top-level await and return work. "
        "Call tools with `await tools.<tool>(args)` (for example `await tools.trace_path({symbol: 'A.B', direction: 'callers'})`) "
        "or `await cc.callTool('<tool>', args)`; `tools.contextcortex.<tool>` also works. Results are parsed JSON; "
        "a tool error throws an Error. Return only what you need. Types: resource " + SDK_URI + "."))] = None,
    arguments: Annotated[Optional[Dict[str, Any]], Field(description="Optional input object, available in the script as `args` (and `arguments`).")] = None,
    code: Annotated[Optional[str], Field(description="Alias for script.")] = None,
    args: Annotated[Optional[Dict[str, Any]], Field(description="Alias for arguments.")] = None,
) -> str:
    """Runs several ContextCortex tool calls in one sandboxed JavaScript script and returns only the final result."""
    try:
        enforce_tool_permission(Role.VIEWER)
        if not code_mode_enabled():
            return json.dumps({"error": "code_mode_disabled", "message": "Code Mode is turned off (CODE_MODE_ENABLED=false)."})
        if not code_mode_available():
            return json.dumps({"error": "code_mode_unavailable", "message": "Code Mode needs the mini-racer package."})
        source = script if script is not None else code
        if not source or not source.strip():
            return json.dumps({"error": "invalid_argument", "message": "script (or code) must be a non-empty string."})
        if len(source) > MAX_SCRIPT_CHARS:
            return json.dumps({"error": "invalid_argument", "message": f"script is longer than {MAX_SCRIPT_CHARS} characters."})
        input_args = arguments if arguments is not None else (args or {})
        if not isinstance(input_args, dict):
            return json.dumps({"error": "invalid_argument", "message": "arguments (or args) must be an object."})

        outcome = await run_script(source, input_args, call_tool_from_script, code_mode_limits())
        payload: Dict[str, Any] = {
            "logs": outcome.logs,
            "executionTimeMs": outcome.execution_time_ms,
            "toolCallsCount": outcome.tool_calls_count,
        }
        if outcome.ok:
            return _response({"result": outcome.result, **payload})
        return _response({"error": "script_failed", "message": outcome.error, **payload})
    except ForbiddenError as fe:
        return json.dumps({"error": "forbidden", "message": str(fe)})
    except Exception as e:
        logger.error(f"execute_script failed: {e}")
        return json.dumps({"error": "script_failed", "message": str(e)})


async def handle_code_mode_sdk_resource() -> str:
    """TypeScript declarations of every tool that a Code Mode script can call."""
    from app.mcp.mcp_server import mcp_server
    from app.services.script_sdk_types import build_sdk_declarations

    tools = [t for t in mcp_server._tool_manager.list_tools() if t.name != TOOL_NAME]
    return build_sdk_declarations(tools)
