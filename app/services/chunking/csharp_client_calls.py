"""
C# HTTP client call sites whose URL is not a literal in the call.

Recognizes:
- `new HttpRequestMessage(HttpMethod.Post, url)`, `new HttpRequestMessage(new HttpMethod("PATCH"), "api/x")`, and
  wrappers such as `_core.SendAsync<T>(HttpMethod.Post, $"{Base}/{id}/publish", body)`
- `_apiClient.GetAsync(url)` / `PostAsJsonAsync(url, body)` with a variable or an interpolated string (`$"api/items/{id}"`)

A variable is resolved from its nearest assignment in the lines before the call (`string url = cond ? $"a" : $"b";`).
Each string literal in that statement gives one call (both branches of a conditional are callers).
"""

import re
from typing import Dict, List, Optional, Tuple

_LOOKBACK_LINES = 40
_STATEMENT_LINES = 6
_VERBS = ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS")

# A C# string literal: "x", $"x/{id}", @"x", $@"x". Group 1 is the content.
_CS_LITERAL = r'(?:\$@|@\$|\$|@)?"((?:[^"\\\n]|\\.)*)"'
# `"api/items/" + id` adds a path segment; `+ Http.BuildQuery(args)` (a call with arguments) does not.
_LITERAL_RE = re.compile(_CS_LITERAL + r'(\s*\+\s*[A-Za-z_][\w.]*(?:\(\))?(?![\w.(]))?')
_IDENTIFIER = r'[A-Za-z_][\w.]*'
_ARGUMENT = r'(' + _CS_LITERAL + r'(?:\s*\+\s*' + _IDENTIFIER + r'(?:\(\))?)?|' + _IDENTIFIER + r')'

# `new HttpRequestMessage(HttpMethod.Post, url)` or a wrapper such as `_core.SendAsync<T>(HttpMethod.Post, url, body)`.
_REQUEST_MESSAGE = re.compile(
    r'\b\w+\s*(?:<[^()]*>)?\s*\(\s*(?:HttpMethod\.(\w+)|new\s+HttpMethod\s*\(\s*"(\w+)"\s*\))\s*,\s*'
    + _ARGUMENT,
)
_CLIENT_METHOD = re.compile(
    r'\b\w*client\.(Get|Post|Put|Delete|Patch)\w*Async\s*(?:<[^<>()]*>)?\(\s*' + _ARGUMENT + r'\s*[,)]',
    re.IGNORECASE,
)


def _looks_like_path(text: str) -> bool:
    return "/" in text and " " not in text.strip() and not text.startswith("//")


def _literal_urls(statement: str) -> List[str]:
    """URL-like string literals of a statement; `"api/items/" + id` becomes `api/items/{id}`."""
    urls = []
    for m in _LITERAL_RE.finditer(statement):
        text = m.group(1)
        if m.group(2):
            text = text.rstrip("/") + "/{" + m.group(2).split("+", 1)[1].strip().split(".")[0].rstrip("()") + "}"
        if _looks_like_path(text):
            urls.append(text)
    return urls


def _resolve_variable(name: str, lines: List[str], line_no: int) -> List[str]:
    """URL literals assigned to `name` in the nearest assignment above line `line_no` (1-based)."""
    short = name.rsplit(".", 1)[-1]
    assign = re.compile(r'\b' + re.escape(short) + r'\s*=(?![=>])')
    first = max(0, line_no - 1 - _LOOKBACK_LINES)
    for idx in range(line_no - 1, first - 1, -1):
        m = assign.search(lines[idx])
        if not m:
            continue
        statement = "\n".join(lines[idx:idx + _STATEMENT_LINES])[m.end():]
        statement = statement.split(";", 1)[0]
        return _literal_urls(statement)
    return []


def _urls_for_argument(arg: str, lines: List[str], line_no: int, consts: Optional[Dict[str, str]] = None) -> List[str]:
    if '"' in arg:
        return _literal_urls(arg)
    if consts and arg in consts:
        return [consts[arg]] if _looks_like_path(consts[arg]) else []
    return _resolve_variable(arg, lines, line_no)


def extract_csharp_client_calls(
    line: str, lines: List[str], line_no: int, consts: Optional[Dict[str, str]] = None,
) -> List[Tuple[Optional[str], str]]:
    """(http_method, url) pairs for a C# line with an HttpRequestMessage or `*Client.<Verb>*Async(...)` call."""
    m_req = _REQUEST_MESSAGE.search(line)
    if m_req:
        verb = (m_req.group(1) or m_req.group(2) or "").upper()
        method = verb if verb in _VERBS else None
        return [(method, url) for url in _urls_for_argument(m_req.group(3), lines, line_no, consts)]
    m_client = _CLIENT_METHOD.search(line)
    if m_client:
        method = m_client.group(1).upper()
        return [(method, url) for url in _urls_for_argument(m_client.group(2), lines, line_no, consts)]
    return []
