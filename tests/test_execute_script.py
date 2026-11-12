"""Code Mode (execute_script): sandbox behavior, limits, tool dispatch through the real handlers, and the SDK types."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.mcp.handlers.script_handlers import call_tool_from_script, code_mode_limits, handle_execute_script
from app.services.script_sandbox import ScriptLimits, ScriptToolError, code_mode_available, run_script
from app.services.script_sdk_types import build_sdk_declarations, schema_to_ts
from tests.test_trace_path_di_callers import REPO, di_graph  # noqa: F401  (pytest fixture)

needs_v8 = pytest.mark.skipif(not code_mode_available(), reason="needs the mini-racer package")


async def _fake_tool(name, tool_args):
    if name == "boom":
        raise ScriptToolError("tool boom failed on purpose")
    return {"tool": name, "args": tool_args, "items": [1, 2, 3]}


def _run(script, script_args=None, **limits):
    limit_values = {"timeout_seconds": 5, "max_tool_calls": 5, "max_memory_bytes": 32 * 1024 * 1024, **limits}
    return asyncio.run(run_script(script, script_args or {}, _fake_tool, ScriptLimits(**limit_values)))


@needs_v8
def test_script_calls_tools_and_returns_a_small_result():
    out = _run("const r = await tools.trace_path({symbol: args.sym}); console.log('got', r.items.length);"
               " return {n: r.items.length, tool: r.tool, sym: arguments.sym};", {"sym": "A.B"})
    assert out.ok and out.result == {"n": 3, "tool": "trace_path", "sym": "A.B"}
    assert out.logs == ["got 3"] and out.tool_calls_count == 1


@needs_v8
def test_gateway_form_and_call_tool_work():
    assert _run("return (await tools.contextcortex.find_routes({q: 1})).tool;").result == "find_routes"
    assert _run("return (await cc.callTool('read_file', {path: 'a'})).args;").result == {"path": "a"}
    assert _run("return (await mcg.callTool('read_file', {})).tool;").result == "read_file"


@needs_v8
def test_tool_errors_throw_and_can_be_caught():
    caught = _run("try { await tools.boom({}); } catch (e) { console.warn(e.message); return 'caught'; }")
    assert caught.ok and caught.result == "caught" and caught.logs == ["[WARN] tool boom failed on purpose"]
    uncaught = _run("console.log('before'); await tools.boom({}); return 1;")
    assert not uncaught.ok and uncaught.error.startswith("Error: tool boom failed on purpose")
    assert uncaught.logs == ["before"]


@needs_v8
def test_script_errors_report_script_line_numbers():
    out = _run("const a = 1;\nthrow new Error('bad input');")
    assert not out.ok and out.error.startswith("Error: bad input") and "<anonymous>:2:" in out.error
    syntax = _run("return {;")
    assert not syntax.ok and "SyntaxError" in syntax.error


@needs_v8
def test_no_return_gives_null():
    out = _run("console.log('only logs');")
    assert out.ok and out.result is None and out.logs == ["only logs"]


@needs_v8
def test_limits_stop_loops_memory_and_tool_fan_out():
    loop = _run("while (true) {}", timeout_seconds=1)
    assert not loop.ok and loop.error == "Script timed out after 1 seconds"
    memory = _run("const a = []; while (true) { a.push(new Array(100000).fill('xxxxxxxxxx')); }")
    assert not memory.ok and memory.error.startswith("Memory limit of 32 MB exceeded")
    calls = _run("for (let i = 0; i < 10; i++) { await tools.x({}); } return 'done';", max_tool_calls=3)
    assert not calls.ok and "Maximum tool calls limit (3) exceeded" in calls.error and calls.tool_calls_count == 3


@needs_v8
def test_host_is_not_reachable_from_the_script():
    out = _run("return [typeof require, typeof process, typeof fetch, typeof __cc_bridge];")
    assert out.ok and out.result[:3] == ["undefined", "undefined", "undefined"]


def test_dispatch_checks_tool_names_and_arguments():
    with pytest.raises(ScriptToolError, match="Recursive execute_script"):
        asyncio.run(call_tool_from_script("execute_script", {"script": "1"}))
    with pytest.raises(ScriptToolError, match="Unknown tool 'nope'"):
        asyncio.run(call_tool_from_script("nope", {}))
    with pytest.raises(ScriptToolError, match="Unknown arguments for trace_path: bogus"):
        asyncio.run(call_tool_from_script("trace_path", {"symbol": "A", "bogus": 1}))
    with pytest.raises(ScriptToolError, match="Missing arguments for trace_path: symbol"):
        asyncio.run(call_tool_from_script("trace_path", {}))


@needs_v8
def test_execute_script_runs_real_tools_end_to_end(di_graph):  # noqa: F811
    script = """
const out = {};
for (const target of args.targets) {
  const t = await tools.trace_path({symbol: target, repo: args.repo, direction: "callers", depth: 1});
  out[target] = t.callers.map(c => c.symbol);
}
return out;
"""
    raw = asyncio.run(handle_execute_script(script=script, arguments={
        "repo": REPO, "targets": ["AssistantService.PublishInstance", "ToolRepository.PublishInstance"]}))
    payload = json.loads(raw)
    assert payload["result"] == {
        "AssistantService.PublishInstance": ["AssistantsController.PublishInstance"],
        "ToolRepository.PublishInstance": ["ToolService.PublishInstance"],
    }
    assert payload["toolCallsCount"] == 2 and payload["logs"] == []


@needs_v8
def test_execute_script_reports_failures_with_logs():
    payload = json.loads(asyncio.run(handle_execute_script(code="console.log('x'); await tools.nope({});")))
    assert payload["error"] == "script_failed" and "Unknown tool 'nope'" in payload["message"]
    assert payload["logs"] == ["x"] and payload["toolCallsCount"] == 1


def test_execute_script_rejects_empty_input():
    assert json.loads(asyncio.run(handle_execute_script(script="  ")))["error"] in ("invalid_argument", "code_mode_unavailable")


def test_limits_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("CODE_MODE_TIMEOUT_SECONDS", "999")
    monkeypatch.setenv("CODE_MODE_MAX_TOOL_CALLS", "7")
    monkeypatch.setenv("CODE_MODE_MAX_MEMORY_MB", "1")
    limits = code_mode_limits()
    assert (limits.timeout_seconds, limits.max_tool_calls, limits.max_memory_bytes) == (300, 7, 8 * 1024 * 1024)


def test_sdk_declarations_from_tool_schemas():
    assert schema_to_ts({"anyOf": [{"type": "string"}, {"type": "null"}]}, {}) == "string | null"
    assert schema_to_ts({"type": "array", "items": {"enum": ["a", "b"]}}, {}) == '("a" | "b")[]'
    tool = SimpleNamespace(name="trace_path", description="Trace callers.", parameters={
        "type": "object", "required": ["symbol"],
        "properties": {"symbol": {"type": "string", "description": "Qualified symbol."},
                       "depth": {"type": "integer", "default": 2}}})
    sdk = build_sdk_declarations([tool])
    assert "trace_path(args: {" in sdk and "symbol: string;" in sdk and "depth?: number;" in sdk
    assert " * Qualified symbol." in sdk and "): Promise<any>;" in sdk and "contextcortex: Omit<typeof tools" in sdk
