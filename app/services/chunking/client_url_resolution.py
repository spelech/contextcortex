"""
Client URL resolution for find_api_callers: string constants and URL variables.

Clients seldom write the full path in the call. They build it from constants and variables:

    const API_BASE = `${HOST}/api/v2`;                         // TypeScript constant
    const url = `${API_BASE}/Assistants/${id}/publish`;        // URL variable
    await sendHttpRequest(url, { method: "POST" });

    private const string Base = "api/v2/Assistants";           // C# constant
    _core.SendAsync<T>(HttpMethod.Post, $"{Base}/{id}/publish", body, ct);

This module expands same-file string constants in a URL and resolves a URL variable from its nearest
assignment. A base that cannot be resolved (an import or a parameter) stays as a leading `{name}`
segment; match_route_and_call then compares the rest of the path with the end of the route.
"""

import re
from typing import Dict, List, Optional

_LOOKBACK_LINES = 40
_STATEMENT_LINES = 6
_JS_LANGUAGES = ("javascript", "typescript", "tsx")
_CS_LANGUAGES = ("c_sharp", "csharp")

_JS_CONST = re.compile(
    r'^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::\s*string\s*)?=\s*(["\'`])([^"\'`\n]*)\2\s*;?\s*$'
)
_CS_CONST = re.compile(
    r'\b(?:const\s+string|static\s+readonly\s+string|readonly\s+static\s+string)\s+([A-Za-z_]\w*)\s*=\s*@?"([^"\n]*)"\s*;'
)
_JS_PLACEHOLDER = re.compile(r'\$\{\s*([A-Za-z_$][\w$]*)\s*\}')
_CS_PLACEHOLDER = re.compile(r'\{([A-Za-z_]\w*)\}')
_JS_LITERAL = re.compile(r'(["\'`])((?:(?!\1)[^\\\n]|\\.)*)\1')


def string_constants(lines: List[str], language: Optional[str]) -> Dict[str, str]:
    """Single-line string constants of a file: `const X = "..."` (JS/TS) or `const string X = "..."` (C#)."""
    consts: Dict[str, str] = {}
    if language in _JS_LANGUAGES:
        for line in lines:
            m = _JS_CONST.match(line)
            if m:
                consts.setdefault(m.group(1), m.group(3))
    elif language in _CS_LANGUAGES:
        for line in lines:
            for m in _CS_CONST.finditer(line):
                consts.setdefault(m.group(1), m.group(2))
    return consts


def expand_constants(url: str, consts: Dict[str, str], language: Optional[str]) -> str:
    """Replaces `${X}` (JS/TS) or `{X}` (C#) with the value of constant X, recursively; other placeholders stay."""
    if not url or not consts:
        return url
    placeholder = _CS_PLACEHOLDER if language in _CS_LANGUAGES else _JS_PLACEHOLDER
    for _ in range(4):
        expanded = placeholder.sub(lambda m: consts.get(m.group(1), m.group(0)), url)
        if expanded == url:
            break
        url = expanded
    return url


def _looks_like_js_url(text: str) -> bool:
    """A path or URL: starts with '/', 'http', or a `${...}` base, and has no spaces ('application/json' is not one)."""
    text = text.strip()
    if " " in text or "/" not in text or text.startswith("//"):
        return False
    return text.startswith(("/", "http://", "https://", "${"))


def js_variable_urls(name: str, lines: List[str], line_no: int) -> List[str]:
    """URL literals assigned to the JS/TS variable `name` in the nearest assignment above line `line_no` (1-based)."""
    assign = re.compile(r'(?<![\w$.])' + re.escape(name) + r'\s*=(?![=>])')
    first = max(0, line_no - 1 - _LOOKBACK_LINES)
    for idx in range(line_no - 1, first - 1, -1):
        m = assign.search(lines[idx])
        if not m:
            continue
        statement = "\n".join(lines[idx:idx + _STATEMENT_LINES])[m.end():].split(";", 1)[0]
        return [lit.group(2) for lit in _JS_LITERAL.finditer(statement) if _looks_like_js_url(lit.group(2))]
    return []
