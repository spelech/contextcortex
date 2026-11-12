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


def build_sdk_declarations(tools: Iterable[Any]) -> str:
    """`declare const tools: {...}` with one async function per tool (objects with name, description, parameters)."""
    lines = [HEADER, "declare const args: Record<string, any>;", "declare const tools: {"]
    for tool in sorted(tools, key=lambda t: t.name):
        schema = getattr(tool, "parameters", None) or {}
        lines += _doc(getattr(tool, "description", "") or "", "  ")
        has_required = bool(schema.get("required"))
        arg_lines = _args_type(schema, "  ")
        arg_lines[0] = f"  {tool.name}(args{'' if has_required else '?'}: {arg_lines[0]}"
        arg_lines[-1] = arg_lines[-1] + "): Promise<any>;"
        lines += arg_lines
    lines += [
        "  contextcortex: Omit<typeof tools, \"contextcortex\">;",
        "};",
        "declare const cc: { callTool(name: string, args?: Record<string, any>): Promise<any> };",
        "",
    ]
    return "\n".join(lines)
