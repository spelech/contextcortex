"""
HTTP client call-site extraction (frontend and service code) for find_api_callers and cross-repo trace_path.

Recognizes fetch/axios/requests/httpx/Go http/C# HttpClient calls (also HttpRequestMessage and URL
variables, see csharp_client_calls), and project-specific JS/TS request helpers (for example getJson(`/api/accounts/${id}`) or apiClient.post('/api/items', ...)).
"""

import re
from typing import List, Optional

from app.models.schemas import ApiClientCallRecord, CodeSymbol

_JS_LANGUAGES = ("javascript", "typescript", "tsx")
_CS_LANGUAGES = ("c_sharp", "csharp")
# The call itself only: `httpRequest.Headers.Add("x")` is not a request (optional generic: requestJson<T>(...)).
_FETCH_CALL = re.compile(r'\b(?:fetch|apiRequest|httpRequest|requestJson)\s*(?:<[^<>()]*>)?\s*\(\s*(["\'`]([^"\'`]+)["\'`])')
_AXIOS_CALL = re.compile(r'\baxios\.(get|post|put|delete|patch|options|head)\s*\(\s*(["\'`]([^"\'`]+)["\'`])', re.IGNORECASE)
_PY_CALL = re.compile(r'\b(?:requests|httpx|client)\.(get|post|put|delete|patch|options|head)\s*\(\s*f?["\']([^"\']+)["\']', re.IGNORECASE)
_GO_CALL = re.compile(r'\bhttp\.(Get|Post|Head)\s*\(\s*["\']([^"\']+)["\']')
_CS_CALL = re.compile(
    r'\b(?:httpClient|_httpClient|client)\.(GetAsync|PostAsync|PutAsync|DeleteAsync|GetFromJsonAsync|PostAsJsonAsync)\s*\(\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_METHOD_OPTION = re.compile(r'method\s*:\s*["\'](GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)["\']', re.IGNORECASE)

# JS/TS helper call whose first argument is a URL literal: name(<T>)?( '/path' | `/path/${x}` | "https://..." )
_JS_HELPER_CALL = re.compile(
    r'\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*(?:<[^<>()]*>)?\(\s*(["\'`])((?:/|https?://|\$\{)[^"\'`]*)\2'
)
_HTTP_LIKE_NAME = re.compile(r'get|post|put|patch|delete|fetch|request|json|http|api', re.IGNORECASE)
_NON_HTTP_NAME = re.compile(
    r'(?:navigate|redirect|route|link|push|replace|history|import|require|resolve|join|startswith|endswith|'
    r'includes|indexof|match|split|log|warn|error|debug|info|getelementbyid|queryselector|getitem|setitem)$',
    re.IGNORECASE,
)
_NAME_METHODS = ("get", "post", "put", "patch", "delete")
# JS/TS call whose first argument is a variable: sendHttpRequest(url, { method: "POST" }) or fetch(url).
_JS_VARIABLE_CALL = re.compile(r'\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*(?:<[^<>()]*>)?\(\s*([A-Za-z_$][\w$]*)\s*[,)]')


def _call_arguments(tail: str, lines: List[str], line_no: int) -> str:
    """Text from inside the call's opening parenthesis to its closing one (this line and up to 4 more lines)."""
    text = tail + "\n" + "\n".join(lines[line_no:min(len(lines), line_no + 4)])
    depth = 1
    for idx, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[:idx]
    return text.split(";")[0]


def _method_from_window(tail: str, lines: List[str], line_no: int, default: str = "GET") -> str:
    """Finds `method: 'POST'` in the arguments of this call only (an options object can span lines)."""
    m_method = _METHOD_OPTION.search(_call_arguments(tail, lines, line_no))
    return m_method.group(1).upper() if m_method else default


def _method_from_helper_name(callee: str) -> Optional[str]:
    last = callee.rsplit(".", 1)[-1].lower()
    for verb in _NAME_METHODS:
        if last.startswith(verb):
            return verb.upper()
    return None


def _js_helper_call(line: str):
    """Returns (callee, url, match) for a JS/TS request-helper call with a URL literal, else None."""
    for m in _JS_HELPER_CALL.finditer(line):
        callee, url = m.group(1), m.group(3)
        last = callee.rsplit(".", 1)[-1]
        if _NON_HTTP_NAME.search(last) or not _HTTP_LIKE_NAME.search(last):
            continue
        if url in ("/", "") or url.startswith("//"):
            continue
        return callee, url, m
    return None


def _js_variable_call(line: str):
    """Returns (callee, variable, match) for an HTTP-like JS/TS call whose first argument is a variable, else None."""
    for m in _JS_VARIABLE_CALL.finditer(line):
        callee, variable = m.group(1), m.group(2)
        last = callee.rsplit(".", 1)[-1]
        if last != "fetch" and (_NON_HTTP_NAME.search(last) or not _HTTP_LIKE_NAME.search(last)):
            continue
        return callee, variable, m
    return None


def extract_client_calls(
    lines: List[str],
    repo: str,
    filepath: str,
    symbols: List[CodeSymbol],
    language: Optional[str],
) -> List[ApiClientCallRecord]:
    """Extracts HTTP client call sites line by line."""
    from app.services.chunking.api_route_extractor import find_enclosing_symbol, normalize_path_pattern
    from app.services.chunking.client_url_resolution import expand_constants, js_variable_urls, string_constants
    from app.services.chunking.csharp_client_calls import extract_csharp_client_calls

    calls: List[ApiClientCallRecord] = []
    consts = string_constants(lines, language)

    def add(method: Optional[str], url_raw: str, line_no: int) -> None:
        calls.append(ApiClientCallRecord(
            repo=repo, filepath=filepath, http_method=method,
            url_pattern=normalize_path_pattern(expand_constants(url_raw, consts, language)), caller_symbol=find_enclosing_symbol(line_no, symbols),
            line_number=line_no,
        ))

    for i, line in enumerate(lines, start=1):
        m_fetch = _FETCH_CALL.search(line)
        if m_fetch:
            add(_method_from_window(line[m_fetch.end():], lines, i), m_fetch.group(2), i)
            continue

        m_axios = _AXIOS_CALL.search(line)
        if m_axios:
            add(m_axios.group(1).upper(), m_axios.group(3), i)
            continue

        m_req = _PY_CALL.search(line)
        if m_req:
            add(m_req.group(1).upper(), m_req.group(2), i)
            continue

        m_go_http = _GO_CALL.search(line)
        if m_go_http:
            add(m_go_http.group(1).upper(), m_go_http.group(2), i)
            continue

        m_cs_client = _CS_CALL.search(line)
        if m_cs_client:
            raw = m_cs_client.group(1)
            method = "GET" if "Get" in raw else "POST" if "Post" in raw else "PUT" if "Put" in raw else "DELETE" if "Delete" in raw else None
            add(method, m_cs_client.group(2), i)
            continue

        if language in _CS_LANGUAGES:
            for method, url in extract_csharp_client_calls(line, lines, i, consts):
                add(method, url, i)
            continue

        if language in _JS_LANGUAGES:
            helper = _js_helper_call(line)
            if helper:
                callee, url, m_helper = helper
                default = _method_from_helper_name(callee) or "GET"
                add(_method_from_window(line[m_helper.end():], lines, i, default), url, i)
                continue
            var_call = _js_variable_call(line)
            if var_call:
                callee, variable, m_var = var_call
                default = _method_from_helper_name(callee) or "GET"
                method = _method_from_window(line[m_var.end():], lines, i, default)
                for url in js_variable_urls(variable, lines, i):
                    add(method, url, i)

    return calls
