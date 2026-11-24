"""
TypeScript declarations for Code Mode scripts (the `contextcortex://code-mode/sdk.d.ts` resource).

Like `router://code-mode/sdk.d.ts` in model-context-gateway: one typed function per tool, made from the tool's
JSON Schema, with the tool and argument descriptions as JSDoc. Agents read it before they write a script.
"""

import json
import re
from typing import Any, Dict, Iterable, List

_IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")

HEADER = """\
/**
 * ContextCortex Code Mode (execute_script).
 * Call tools with `await tools.<tool>(args)` or `await cc.callTool("<tool>", args)`.
 * `tools.contextcortex.<tool>(args)` also works, so a script runs unchanged through model-context-gateway.
 * Results are parsed JSON. A tool error throws an Error (use try/catch).
 * Globals: `args` / `arguments` (input object), `console.log/warn/error` (returned in `logs`).
 * Top-level `await` and `return` work. The value you `return` is the result.
 */
"""

# Result types for tools whose results have a fixed compact shape. The other tools return `Promise<any>`.
RESULT_TYPES = """\
/** grep_code lines: '<line>:<text>' is a match, '<line>-<text>' is context, '--' separates blocks. */
interface GrepCodeFile { file: string; repo?: string; symbols?: Record<string, string>; permalink?: string; lines: string[] }
interface GrepCodeResult { total_matches: number; has_more: boolean; next_offset?: number; offset?: number; pattern_mode?: string; path_filter?: string; repo?: string; files: GrepCodeFile[]; index_status?: string; sync_progress?: Record<string, any> }
/** read_file text slice: each content line is '<line>:<text>'. With outline_only=True the result has symbols instead. */
interface ReadFileResult { file: string; lines: [number, number]; total_lines: number; next_start_line?: number; truncated?: boolean; source?: string; missing_lines?: [number, number][]; content: string }
interface ReadFileOutline { file: string; repo: string | null; outline_only: true; total_symbols: number; offset: number; limit: number; has_more: boolean; next_offset: number | null; symbols: { name: string; symbol: string; kind: string; lines: [number, number]; signature: string | null }[]; candidates?: string[] }
"""

# Result shapes of the tools that scripts chain most. A field name that ends in "?" is not always there.
# tests/test_code_mode_result_types.py checks these fields against real results of the tools.
_S, _SN, _N, _NN, _LINES = "string", "string | null", "number", "number | null", "[number, number]"
_PAGE = {"offset": _N, "limit": _N, "has_more": "boolean", "next_offset": _NN}
RESULT_INTERFACES: Dict[str, Dict[str, str]] = {
    "CallSite": {"file?": _S, "line": _N, "text": _S},
    "ChainStep": {"symbol": _S, "kind": _SN, "file": _S, "lines": _LINES, "via?": _S, "call_site?": "CallSite",
                  "not_passed?": "string[]", "evidence": "{ line: number; text: string }[]", "score": _N, "code?": _S},
    "ChainHit": {"symbol": _S, "file": _S, "lines": _LINES, "score": _N, "not_passed?": "string[]"},
    "CallChain": {"entry": _SN, "terms": "string[]", "steps": "ChainStep[]", "other_hits": "ChainHit[]", "nodes_read": _N},
    "WorkingStep": {"symbol": _S, "file": _S, "lines": _LINES, "call_site?": "CallSite"},
    "WorkingPathComparison": {"statement": _S, "entry": "{ symbol: string; aligned_with: string; route?: string } | null",
                              "steps": "WorkingStep[]", "first_divergence": "Record<string, any> | null"},
    "DiagnoseResult": {"call_chain": "CallChain", "working_path_comparison": "WorkingPathComparison | null",
                       "resolved_frames": "any[]", "matched_routes": "any[]", "matched_symbols": "any[]",
                       "semantic_candidates": "any[]", "hint?": _S,
                       "index_status?": _S, "sync_progress?": "Record<string, any>"},
    "Route": {"repo": _S, "method": _S, "path": _S, "framework": _SN, "handler": _S, "file": _S, "lines": _LINES,
              "permalink?": _SN},
    "RouteCaller": {"repo": _S, "method": _SN, "url": _S, "caller": _S, "file": _S, "line": _N, "permalink?": _SN},
    "FindRoutesResult": {"query": _SN, "kind": _S, "method": _SN, "repo": _SN, "total": _N, "total_routes?": _N,
                         "total_callers?": _N, **_PAGE, "routes?": "Route[]", "callers?": "RouteCaller[]"},
    "TraceTarget": {"symbol": _S, "name": _S, "kind": _SN, "repo": _S, "file": _S, "lines": _LINES, "permalink": _SN,
                    "route?": "any", "external_callers?": "any[]", "http_calls?": "any[]"},
    "TraceNode": {"symbol": _S, "rel": _S, "repo": _S, "file": _S, "line": _NN, "defined_at?": _S, "permalink?": _SN,
                  "confidence?": _S, "route?": "any", "external_callers?": "any[]", "http_calls?": "any[]",
                  "unresolved?": "string[]", "callers?": "TraceNode[]", "callees?": "TraceNode[]"},
    "TracePathResult": {"target?": "TraceTarget", "symbol?": _S, "found?": "false",
                        "candidates?": "{ symbol: string; file: string; line: number; repos: string[] }[]", "hint?": _S, "direction?": _S, "depth?": _N,
                        "truncated?": "boolean", "truncation_reason?": _S, "callers": "TraceNode[]", "callees": "TraceNode[]",
                        "unresolved?": "string[]", "total_callers": _N, "total_callees": _N, **_PAGE,
                        "index_status?": _S, "sync_progress?": "Record<string, any>"},
    "SymbolHit": {"name": _S, "symbol": _S, "kind": _SN, "repo": _S, "file": _S, "lines": _LINES, "signature": _SN,
                  "language": _SN},
    "FindSymbolResult": {"query": _S, "exact": "boolean", "total": _N, **_PAGE, "symbols": "SymbolHit[]",
                         "index_status?": _S, "sync_progress?": "Record<string, any>"},
    "SearchHit": {"repo": _SN, "file": _S, "doc_type": _S, "lines": "[number, number] | null", "symbol": _SN,
                  "kind": _SN, "signature": _SN, "language": _SN, "heading": _SN, "tags": "string[]", "score": _N,
                  "dense_score": _NN, "sparse_score": _NN, "permalink?": _SN, "content_truncated": "boolean",
                  "content": _S},
    "SearchResult": {"query": _S, "scope": _S, "mode": _S, "returned": _N, "total": _N, **_PAGE, "max_snippet_chars": _N,
                     "results": "SearchHit[]", "dense_fallback_lexical_only?": "boolean",
                     "index_status?": _S, "sync_progress?": "Record<string, any>"},
}
_INTERFACE_DOCS = {
    "CallSite": "The line in the caller that calls this step (a working-path step has no file).",
    "ChainStep": "One step of the failing call path. The last step is the most likely fault; not_passed lists "
                 "arguments that the call site does not pass on (for example the transaction).",
    "TraceNode": "file/line is the call site in the caller; defined_at (path:line) is where the callee is defined.",
    "TracePathResult": "An unknown symbol gives {symbol, found: false} and no target; for an unknown class, candidates "
                       "lists the indexed symbols with the same member name.",
}


def _render_interface(name: str, fields: Dict[str, str]) -> str:
    doc = f"/** {_INTERFACE_DOCS[name]} */\n" if name in _INTERFACE_DOCS else ""
    return doc + f"interface {name} {{ " + "; ".join(f"{key}: {ts}" for key, ts in fields.items()) + " }"


RESULT_TYPES += "\n".join(_render_interface(name, fields) for name, fields in RESULT_INTERFACES.items()) + "\n"

_RESULT_TYPE_NAMES = {
    "grep_code": "GrepCodeResult", "read_file": "ReadFileResult | ReadFileOutline", "diagnose_issue": "DiagnoseResult",
    "find_routes": "FindRoutesResult", "trace_path": "TracePathResult", "find_symbol": "FindSymbolResult",
    "search": "SearchResult",
}


def _doc(text: str, indent: str) -> List[str]:
    lines = [line.rstrip() for line in (text or "").strip().splitlines() if line.strip()]
    if not lines:
        return []
    safe = [line.replace("*/", "* /") for line in lines]
    return [f"{indent}/**"] + [f"{indent} * {line}" for line in safe] + [f"{indent} */"]


def schema_to_ts(schema: Any, defs: Dict[str, Any], depth: int = 0) -> str:
    """A TypeScript type for a JSON Schema fragment (objects, arrays, enums, unions, $ref)."""
    if not isinstance(schema, dict) or depth > 6:
        return "any"
    if "$ref" in schema:
        ref = str(schema["$ref"]).rsplit("/", 1)[-1]
        return schema_to_ts(defs.get(ref, {}), defs, depth + 1)
    if "enum" in schema:
        return " | ".join(json.dumps(v) for v in schema["enum"]) or "any"
    if "const" in schema:
        return json.dumps(schema["const"])
    for key in ("anyOf", "oneOf"):
        if key in schema:
            parts = []
            for option in schema[key]:
                ts = schema_to_ts(option, defs, depth + 1)
                if ts not in parts:
                    parts.append(ts)
            return " | ".join(parts) or "any"
    kind = schema.get("type")
    if isinstance(kind, list):
        return " | ".join(schema_to_ts({**schema, "type": k}, defs, depth + 1) for k in kind)
    if kind in ("string",):
        return "string"
    if kind in ("integer", "number"):
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "null":
        return "null"
    if kind == "array":
        item = schema_to_ts(schema.get("items", {}), defs, depth + 1)
        return f"({item})[]" if " " in item else f"{item}[]"
    if kind == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        if not props:
            return "Record<string, any>"
        required = set(schema.get("required") or [])
        fields = []
        for name, prop in props.items():
            key = name if _IDENTIFIER.match(name) else json.dumps(name)
            fields.append(f"{key}{'' if name in required else '?'}: {schema_to_ts(prop, defs, depth + 1)}")
        return "{ " + "; ".join(fields) + " }"
    return "any"


def _args_type(schema: Dict[str, Any], indent: str) -> List[str]:
    defs = schema.get("$defs") or schema.get("definitions") or {}
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    lines = ["{"]
    for name, prop in props.items():
        lines += _doc((prop or {}).get("description", ""), indent + "  ")
        key = name if _IDENTIFIER.match(name) else json.dumps(name)
        lines.append(f"{indent}  {key}{'' if name in required else '?'}: {schema_to_ts(prop, defs)};")
    lines.append(f"{indent}}}")
    return lines


def _tool_declaration(tool: Any) -> List[str]:
    schema = getattr(tool, "parameters", None) or {}
    lines = _doc(getattr(tool, "description", "") or "", "  ")
    has_required = bool(schema.get("required"))
    arg_lines = _args_type(schema, "  ")
    arg_lines[0] = f"  {tool.name}(args{'' if has_required else '?'}: {arg_lines[0]}"
    arg_lines[-1] = arg_lines[-1] + f"): Promise<{_RESULT_TYPE_NAMES.get(tool.name, 'any')}>;"
    return lines + arg_lines


HELP_DECLARATION = [
    "  /** tools.help() lists the tools; tools.help('<tool>') gives its arguments and result type. Not a tool call. */",
    "  help(tool?: string): string;",
]


def build_sdk_declarations(tools: Iterable[Any]) -> str:
    """`declare const tools: {...}` with one async function per tool (objects with name, description, parameters)."""
    lines = [HEADER, RESULT_TYPES, "declare const args: Record<string, any>;", "declare const tools: {"]
    for tool in sorted(tools, key=lambda t: t.name):
        lines += _tool_declaration(tool)
    lines += HELP_DECLARATION + [
        "  contextcortex: Omit<typeof tools, \"contextcortex\">;",
        "};",
        "declare const cc: { callTool(name: string, args?: Record<string, any>): Promise<any> };",
        "",
    ]
    return "\n".join(lines)


HELP_INTRO = ("ContextCortex Code Mode. Call a tool with `await tools.<tool>(args)`; results are parsed JSON. "
              "tools.help('<tool>') gives the argument docs and the result type of one tool. "
              "For a bug report with a stack trace, error message, or route, call diagnose_issue first; "
              "for a plain-language description, start with search.")


def _interface_blocks() -> Dict[str, str]:
    """Each interface in RESULT_TYPES with the doc comment above it."""
    blocks: Dict[str, str] = {}
    doc = ""
    for line in RESULT_TYPES.splitlines():
        match = re.match(r"interface (\w+) ", line)
        if match:
            blocks[match.group(1)] = doc + line
            doc = ""
        elif line.startswith("/**"):
            doc = line + "\n"
    return blocks


def _result_interfaces(result_type: str, blocks: Dict[str, str]) -> List[str]:
    """The interfaces that a result type uses, and the interfaces that those use, in order."""
    order: List[str] = []
    todo = re.findall(r"[A-Za-z]+", result_type)
    while todo:
        name = todo.pop(0)
        if name in blocks and name not in order:
            order.append(name)
            todo += re.findall(r"[A-Za-z]+", blocks[name].split(" { ", 1)[1])
    return [blocks[name] for name in order]


def _signature(tool: Any) -> str:
    schema = getattr(tool, "parameters", None) or {}
    required = set(schema.get("required") or [])
    names = [name if name in required else f"{name}?" for name in (schema.get("properties") or {})]
    return f"{tool.name}({{{', '.join(names)}}}): {_RESULT_TYPE_NAMES.get(tool.name, 'any')}"


def build_help(tools: Iterable[Any]) -> Dict[str, str]:
    """Texts for tools.help() in a script: key '' is the tool list; each tool name gives that tool's declaration."""
    ordered = sorted(tools, key=lambda t: t.name)
    blocks = _interface_blocks()
    texts = {"": "\n".join([HELP_INTRO] + [_signature(tool) for tool in ordered])}
    for tool in ordered:
        parts = ["\n".join(_tool_declaration(tool)).replace("\n  ", "\n").strip()]
        parts += _result_interfaces(_RESULT_TYPE_NAMES.get(tool.name, ""), blocks)
        texts[tool.name] = "\n".join(parts)
    return texts
