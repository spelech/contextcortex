"""
Code Mode sandbox: runs an agent-written JavaScript body in a disposable V8 isolate (mini-racer).

The design follows Code Mode in model-context-gateway (`execute_script`, Jint): one new engine per run,
no host access other than the tool bridge, top-level `await` and `return`, `console` logs, automatic
JSON unboxing of tool results, and limits on time, memory, and the number of tool calls.

The isolate can reach Python only through two injected async functions: the tool bridge and the log sink.
Values cross the boundary as JSON strings, so no Python object is exposed to JavaScript.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

MAX_LOG_ENTRIES = 100
MAX_LOG_CHARS = 2000


class ScriptToolError(Exception):
    """A tool called from a script failed; the script receives it as a JavaScript Error."""


@dataclass
class ScriptLimits:
    timeout_seconds: float = 30.0
    max_tool_calls: int = 50
    max_memory_bytes: int = 64 * 1024 * 1024


@dataclass
class ScriptOutcome:
    ok: bool
    result: Any = None
    error: Optional[str] = None
    logs: List[str] = field(default_factory=list)
    execution_time_ms: int = 0
    tool_calls_count: int = 0


def code_mode_available() -> bool:
    try:
        import py_mini_racer  # noqa: F401
    except ImportError:
        return False
    return True


# Runs before the script. `__cc_bridge` is the only host function; logs stay in the isolate until the end.
_PRELUDE = r"""
globalThis.args = JSON.parse(__cc_args_json);
globalThis.arguments = globalThis.args;
globalThis.__cc_logs = [];
const __cc_fmt = (v) => { if (typeof v === "string") { return v; } try { return JSON.stringify(v); } catch (e) { return String(v); } };
const __cc_push = (prefix, a) => {
  if (__cc_logs.length < %(max_logs)d) { __cc_logs.push((prefix + a.map(__cc_fmt).join(" ")).slice(0, %(max_chars)d)); }
};
globalThis.console = {
  log: (...a) => __cc_push("", a),
  info: (...a) => __cc_push("", a),
  warn: (...a) => __cc_push("[WARN] ", a),
  error: (...a) => __cc_push("[ERROR] ", a),
};
globalThis.cc = {
  callTool: async (name, toolArgs) => {
    const reply = JSON.parse(await __cc_bridge(String(name), JSON.stringify(toolArgs === undefined ? {} : toolArgs)));
    if (reply.error !== undefined) { throw new Error(reply.error); }
    return reply.value;
  },
};
globalThis.mcg = globalThis.cc;
const __cc_tool_proxy = (prefix) => new Proxy({}, {
  get: (_t, prop) => {
    if (typeof prop !== "string" || prop === "then") { return undefined; }
    if (prop === "contextcortex" && prefix === "") { return __cc_tool_proxy("contextcortex"); }
    return async (toolArgs) => cc.callTool(prop, toolArgs);
  },
});
globalThis.tools = __cc_tool_proxy("");
""" % {"max_logs": MAX_LOG_ENTRIES, "max_chars": MAX_LOG_CHARS}


def _wrap(script: str) -> str:
    # The body runs inside an async arrow function, so top-level `await` and `return` work (as in MCG).
    # The script starts on line 1 of the evaluated code, so line numbers in errors match the script.
    return "(async () => {" + script + "\n})().then((v) => JSON.stringify(v === undefined ? null : v))"


_REJECTED_PREFIX = "JavaScript rejected promise with reason: "


def _clean_error(exc: BaseException) -> str:
    """The JavaScript error text without the mini-racer prefix, limited to the first lines of the stack."""
    text = str(exc).strip() or type(exc).__name__
    if text.startswith(_REJECTED_PREFIX):
        text = text[len(_REJECTED_PREFIX):]
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[:4])


async def run_script(
    script: str,
    script_args: Dict[str, Any],
    call_tool: Callable[[str, Dict[str, Any]], Awaitable[Any]],
    limits: ScriptLimits,
) -> ScriptOutcome:
    """Runs `script` and returns its result, logs, time, and tool call count. Never raises for script errors."""
    from py_mini_racer import JSOOMException, JSTimeoutException, mini_racer

    started = time.perf_counter()
    logs: List[str] = []
    calls = [0]

    async def bridge(name: Any, args_json: Any) -> str:
        calls[0] += 1
        if calls[0] > limits.max_tool_calls:
            return json.dumps({"error": f"Maximum tool calls limit ({limits.max_tool_calls}) exceeded in a single script execution"})
        try:
            tool_args = json.loads(args_json) if args_json else {}
            if not isinstance(tool_args, dict):
                raise ScriptToolError("tool arguments must be an object")
            value = await call_tool(str(name), tool_args)
        except ScriptToolError as e:
            return json.dumps({"error": str(e)})
        except Exception as e:  # a tool raised: the script gets a JavaScript Error
            return json.dumps({"error": f"{name} failed: {e}"})
        return json.dumps({"value": value}, default=str)

    def outcome(ok: bool, result: Any = None, error: Optional[str] = None) -> ScriptOutcome:
        return ScriptOutcome(ok=ok, result=result, error=error, logs=logs,
                             execution_time_ms=int((time.perf_counter() - started) * 1000),
                             tool_calls_count=min(calls[0], limits.max_tool_calls))

    deadline = started + limits.timeout_seconds

    def remaining() -> float:
        return max(0.1, deadline - time.perf_counter())

    with mini_racer() as ctx:
        ctx.set_hard_memory_limit(int(limits.max_memory_bytes))
        async with ctx.wrap_py_function(bridge) as js_bridge:
            global_this = ctx.eval("this")
            global_this["__cc_bridge"] = js_bridge
            global_this["__cc_args_json"] = json.dumps(script_args or {}, default=str)
            try:
                await asyncio.wait_for(ctx.eval_cancelable(_PRELUDE), timeout=remaining())
                promise = await asyncio.wait_for(ctx.eval_cancelable(_wrap(script)), timeout=remaining())
                text = await asyncio.wait_for(promise, timeout=remaining()) if hasattr(promise, "__await__") else promise
                result = outcome(True, result=json.loads(text) if isinstance(text, str) else text)
            except (asyncio.TimeoutError, JSTimeoutException):
                result = outcome(False, error=f"Script timed out after {limits.timeout_seconds:g} seconds")
            except JSOOMException:
                result = outcome(False, error=f"Memory limit of {limits.max_memory_bytes // (1024 * 1024)} MB exceeded")
            except Exception as e:  # syntax errors, uncaught JavaScript errors, rejected promises
                result = outcome(False, error=_clean_error(e))
            if result.ok and ctx.was_hard_memory_limit_reached():
                result = outcome(False, error=f"Memory limit of {limits.max_memory_bytes // (1024 * 1024)} MB exceeded")
            logs.extend(_read_logs(ctx))
            result.logs = logs
            return result


def _read_logs(ctx: Any) -> List[str]:
    """Reads the console entries that the script left in the isolate (empty if the isolate cannot answer)."""
    try:
        raw = ctx.eval("JSON.stringify(globalThis.__cc_logs || [])")
        return [str(entry) for entry in json.loads(raw)][:MAX_LOG_ENTRIES]
    except Exception:
        return []
