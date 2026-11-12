import re
from typing import List, Dict, Any, Optional, Tuple
from app.models.schemas import ApiRouteRecord, ApiClientCallRecord, CodeSymbol
from app.services.chunking.tree_sitter_loader import detect_language

def normalize_path_pattern(path: str) -> str:
    """
    Normalizes path patterns across route definitions and client calls.
    Converts ASP.NET/FastAPI ({id:guid}), express (:id), template literal (${id}),
    django (<int:id>), and next.js ([id]) formats to canonical {id} format.
    """
    if not path:
        return "/"
    path = path.strip("'\"` ")
    # ASP.NET / FastAPI typed route constraints {id:guid}, {id:int}, {slug:str}
    path = re.sub(r'\{([a-zA-Z_][a-zA-Z0-9_]*):[^{}]+\}', r'{\1}', path)
    # Django <int:id> or <id>
    path = re.sub(r'<(?:\w+:)?([a-zA-Z_][a-zA-Z0-9_]*)>', r'{\1}', path)
    # Express style :param
    path = re.sub(r'(?:^|(?<=/)):([a-zA-Z_][a-zA-Z0-9_]*)', r'{\1}', path)
    # Template literal ${param}
    path = re.sub(r'\$\{([^{}]+)\}', r'{\1}', path)
    # Next.js [id]
    path = re.sub(r'\[([a-zA-Z_][a-zA-Z0-9_]*)\]', r'{\1}', path)

    # Ensure starting slash if relative path
    if not path.startswith("http://") and not path.startswith("https://") and not path.startswith("/"):
        path = "/" + path
    # Remove duplicate slashes (except after http://)
    path = re.sub(r'(?<!:)/{2,}', '/', path)
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path

def route_pattern_to_regex(pattern: str) -> re.Pattern:
    """Converts a normalized route pattern with {param} into a regex for matching client call URLs."""
    norm = normalize_path_pattern(pattern)
    norm_base = norm.rstrip('/') or '/'
    parts = re.split(r'(\{[\w\-]+\})', norm_base)
    regex_parts = []
    for part in parts:
        if part.startswith('{') and part.endswith('}'):
            regex_parts.append(r'(?:[^/?#]+)')
        else:
            regex_parts.append(re.escape(part))
    pattern_str = '^' + ''.join(regex_parts) + r'(?:/|\?.*|#.*)?$'
    return re.compile(pattern_str, re.IGNORECASE)

_PARAM_SEGMENT = re.compile(r'^\{[^{}/]+\}$')
_MIN_LITERAL_SEGMENTS_FOR_SUFFIX = 2


def _segment_regex(segment: str) -> re.Pattern:
    parts = re.split(r'(\{[^{}]+\})', segment)
    return re.compile('^' + ''.join('[^/]+' if p.startswith('{') else re.escape(p) for p in parts) + '$', re.IGNORECASE)


def _match_base_relative_call(norm_route: str, norm_call: str) -> bool:
    """
    A client URL that starts with a base it could not resolve (`{baseUrl}/api/v2/items/{id}`, `{API_HOST}/v2/items`)
    matches when the rest of its path matches the end of the route, segment by segment, with at least two literal
    segments (so `{base}/{id}` alone matches nothing).
    """
    call_segs = [s for s in norm_call.split("?", 1)[0].strip("/").split("/") if s]
    lead = 0
    while lead < len(call_segs) and _PARAM_SEGMENT.match(call_segs[lead]):
        lead += 1
    tail = call_segs[lead:]
    if lead == 0 or sum(1 for s in tail if not _PARAM_SEGMENT.match(s)) < _MIN_LITERAL_SEGMENTS_FOR_SUFFIX:
        return False
    route_segs = [s for s in norm_route.strip("/").split("/") if s]
    if len(tail) > len(route_segs):
        return False
    for call_seg, route_seg in zip(tail, route_segs[len(route_segs) - len(tail):]):
        if _PARAM_SEGMENT.match(route_seg):
            continue
        # A client parameter ({eid}) only fills a route parameter, never a literal segment such as `publish`.
        if _PARAM_SEGMENT.match(call_seg) or not _segment_regex(route_seg).match(call_seg):
            return False
    return True


def match_route_and_call(route_path: str, call_url: str) -> bool:
    """Checks if a client call URL matches a server route pattern (an absolute URL's host is ignored)."""
    norm_route = normalize_path_pattern(route_path)
    norm_call = normalize_path_pattern(re.sub(r'^https?://[^/]+', '', (call_url or '').strip("'\"` ")) or "/")
    if norm_route == norm_call:
        return True
    rx = route_pattern_to_regex(norm_route)
    if rx.match(norm_call):
        return True
    return _match_base_relative_call(norm_route, norm_call)

def find_enclosing_symbol(line_no: int, symbols: List[CodeSymbol]) -> Optional[str]:
    """Finds the most specific AST symbol enclosing a given line number."""
    best_symbol = None
    best_span = float('inf')
    for sym in symbols:
        if sym.start_line <= line_no <= sym.end_line:
            span = sym.end_line - sym.start_line
            if span < best_span:
                best_span = span
                best_symbol = sym.full_symbol or sym.name
    return best_symbol

def _is_test_filepath(filepath: str) -> bool:
    if not filepath:
        return False
    clean = (filepath.split("://", 1)[1] if "://" in filepath else filepath).replace("\\", "/").strip("/")
    parts = [p.lower() for p in clean.split("/") if p]
    if any(p in ("tests", "test", "__tests__") for p in parts[:-1]):
        return True
    bname = parts[-1] if parts else ""
    if bname.startswith("test_") or bname.endswith(("_test.py", "_test.go", ".test.ts", ".test.tsx", ".test.js", ".spec.ts", ".spec.tsx", ".spec.js", "tests.cs", "test.cs")):
        return True
    return False


def _join_route_prefix(prefix: str, sub_path: str) -> str:
    if not prefix:
        return sub_path or "/"
    if not sub_path or sub_path == "/":
        return prefix
    return f"{prefix.rstrip('/')}/{sub_path.lstrip('/')}"


def extract_api_routes_and_calls(
    code: str,
    filepath: str,
    repo: str = "default",
    symbols: Optional[List[CodeSymbol]] = None
) -> Tuple[List[ApiRouteRecord], List[ApiClientCallRecord]]:
    """
    Extracts server route definitions and client call sites across Python, JS/TS, Go, C#, Java, etc.
    """
    symbols = symbols or []
    lines = code.splitlines()
    routes: List[ApiRouteRecord] = []
    calls: List[ApiClientCallRecord] = []
    language = detect_language(filepath) if not _is_test_filepath(filepath) else None

    # ----------------------------------------------------
    # 1. SERVER ROUTE EXTRACTION
    # ----------------------------------------------------

    # Python: FastAPI / Starlette / Flask / Django
    if language == "python":
        router_prefixes: Dict[str, str] = {}
        for m_rtr in re.finditer(r'\b(\w+)\s*=\s*(?:[\w\.]*\.)?APIRouter\s*\(([\s\S]*?)\)', code):
            mp = re.search(r'prefix\s*=\s*["\']([^"\']*)["\']', m_rtr.group(2))
            router_prefixes[m_rtr.group(1)] = mp.group(1) if mp else ""
        for m_bp in re.finditer(r'\b(\w+)\s*=\s*(?:[\w\.]*\.)?Blueprint\s*\(([\s\S]*?)\)', code):
            mp = re.search(r'url_prefix\s*=\s*["\']([^"\']*)["\']', m_bp.group(2))
            router_prefixes[m_bp.group(1)] = mp.group(1) if mp else ""

        for i, line in enumerate(lines, start=1):
            window_text = " ".join(l.strip() for l in lines[i - 1:min(len(lines), i + 3)])
            # FastAPI / Starlette (supports APIRouter(prefix=...), custom router vars, and empty "" sub-paths)
            m_fastapi = re.search(r'@(\w+)\.(get|post|put|delete|patch|options|head|trace)\s*\(', line, re.IGNORECASE)
            if m_fastapi:
                rtr_var = m_fastapi.group(1)
                low_var = rtr_var.lower()
                if rtr_var in router_prefixes or low_var in ("app", "router", "api_router") or low_var.endswith("_router") or low_var.startswith("router_"):
                    m_path = re.search(
                        rf'@{re.escape(rtr_var)}\.(?:get|post|put|delete|patch|options|head|trace)\s*\(\s*(?:path\s*=\s*)?["\']([^"\']*)["\']',
                        window_text,
                        re.IGNORECASE,
                    )
                    if m_path:
                        method = m_fastapi.group(2).upper()
                        raw_path = _join_route_prefix(router_prefixes.get(rtr_var, ""), m_path.group(1))
                        path = normalize_path_pattern(raw_path)
                        handler = None
                        for offset in range(0, 12):
                            handler = find_enclosing_symbol(i + offset, symbols)
                            if handler:
                                break
                        routes.append(ApiRouteRecord(
                            repo=repo, filepath=filepath, framework="fastapi",
                            http_method=method, path_pattern=path, handler_symbol=handler,
                            start_line=i, end_line=i
                        ))
                        continue

            # Flask
            m_flask = re.search(r'@(\w+)\.route\s*\(\s*["\']([^"\']*)["\'](?:,\s*methods=\[([^\]]+)\])?', line, re.IGNORECASE)
            if m_flask:
                bp_var = m_flask.group(1)
                raw_path = _join_route_prefix(router_prefixes.get(bp_var, ""), m_flask.group(2))
                path = normalize_path_pattern(raw_path)
                methods_str = m_flask.group(3)
                methods = ["GET"]
                if methods_str:
                    methods = [m.strip(" \"'").upper() for m in methods_str.split(",") if m.strip(" \"'")]
                handler = find_enclosing_symbol(i + 1, symbols) or find_enclosing_symbol(i, symbols)
                for m in methods:
                    routes.append(ApiRouteRecord(
                        repo=repo, filepath=filepath, framework="flask",
                        http_method=m, path_pattern=path, handler_symbol=handler,
                        start_line=i, end_line=i
                    ))
                continue

            # Django
            m_django = re.search(r'(?:path|re_path)\s*\(\s*["\']([^"\']+)["\']\s*,\s*([\w\.]+)', line)
            if m_django:
                path = normalize_path_pattern(m_django.group(1))
                handler = m_django.group(2)
                routes.append(ApiRouteRecord(
                    repo=repo, filepath=filepath, framework="django",
                    http_method="ALL", path_pattern=path, handler_symbol=handler,
                    start_line=i, end_line=i
                ))

    # JavaScript / TypeScript / TSX
    elif language in ("javascript", "typescript", "tsx"):
        # Express.js
        for i, line in enumerate(lines, start=1):
            m_express = re.search(r'(?:app|router|server|express)\.(get|post|put|delete|patch|all|options|head)\s*\(\s*["\'`]([^"\'`]+)["\'`]', line, re.IGNORECASE)
            if m_express:
                method = m_express.group(1).upper()
                path = normalize_path_pattern(m_express.group(2))
                handler = find_enclosing_symbol(i, symbols)
                routes.append(ApiRouteRecord(
                    repo=repo, filepath=filepath, framework="express",
                    http_method=method, path_pattern=path, handler_symbol=handler,
                    start_line=i, end_line=i
                ))

        # NestJS: Controller prefix + decorators
        nest_prefix = ""
        for i, line in enumerate(lines, start=1):
            m_ctrl = re.search(r'@Controller\s*\(\s*(?:["\'`]([^"\'`]*)["\'`])?\s*\)', line)
            if m_ctrl:
                nest_prefix = m_ctrl.group(1) or ""

            m_nest = re.search(r'@(Get|Post|Put|Delete|Patch|All|Options|Head)\s*\(\s*(?:["\'`]([^"\'`]*)["\'`])?\s*\)', line, re.IGNORECASE)
            if m_nest:
                method = m_nest.group(1).upper()
                sub_path = m_nest.group(2) or ""
                full_path = normalize_path_pattern(_join_route_prefix(nest_prefix, sub_path))
                handler = find_enclosing_symbol(i + 1, symbols) or find_enclosing_symbol(i, symbols)
                routes.append(ApiRouteRecord(
                    repo=repo, filepath=filepath, framework="nestjs",
                    http_method=method, path_pattern=full_path, handler_symbol=handler,
                    start_line=i, end_line=i
                ))

        # Next.js App Router (route.ts / route.js)
        norm_fp = filepath.replace("\\", "/")
        if re.search(r'route\.(?:ts|js|tsx|jsx)$', norm_fp):
            route_base = re.sub(r'/route\.(?:ts|js|tsx|jsx)$', '', norm_fp)
            parts = route_base.split('/')
            raw_route_path = "/"
            for idx, part in enumerate(parts):
                if part in ("app", "pages") and idx + 1 < len(parts):
                    raw_route_path = "/" + "/".join(parts[idx + 1:])
                    break
            route_path = normalize_path_pattern(raw_route_path)
            for i, line in enumerate(lines, start=1):
                m_next = re.search(r'export\s+(?:async\s+)?function\s+(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\b', line)
                if m_next:
                    method = m_next.group(1).upper()
                    handler = find_enclosing_symbol(i, symbols) or m_next.group(1)
                    routes.append(ApiRouteRecord(
                        repo=repo, filepath=filepath, framework="nextjs",
                        http_method=method, path_pattern=route_path, handler_symbol=handler,
                        start_line=i, end_line=i
                    ))

    # Go: Gin / Echo / http.HandleFunc
    elif language == "go":
        for i, line in enumerate(lines, start=1):
            # Gin
            m_gin = re.search(r'(?:r|router|api|grp|g|engine|group)\.(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)\s*\(\s*["\']([^"\']+)["\']', line)
            if m_gin:
                method = m_gin.group(1).upper()
                path = normalize_path_pattern(m_gin.group(2))
                handler = find_enclosing_symbol(i, symbols)
                routes.append(ApiRouteRecord(
                    repo=repo, filepath=filepath, framework="gin",
                    http_method=method, path_pattern=path, handler_symbol=handler,
                    start_line=i, end_line=i
                ))
                continue

            # Echo
            m_echo = re.search(r'(?:e|echo|g|group)\.(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)\s*\(\s*["\']([^"\']+)["\']', line)
            if m_echo:
                method = m_echo.group(1).upper()
                path = normalize_path_pattern(m_echo.group(2))
                handler = find_enclosing_symbol(i, symbols)
                routes.append(ApiRouteRecord(
                    repo=repo, filepath=filepath, framework="echo",
                    http_method=method, path_pattern=path, handler_symbol=handler,
                    start_line=i, end_line=i
                ))
                continue

            # stdlib http.HandleFunc
            m_http = re.search(r'http\.HandleFunc\s*\(\s*["\']([^"\']+)["\']', line)
            if m_http:
                path = normalize_path_pattern(m_http.group(1))
                handler = find_enclosing_symbol(i, symbols)
                routes.append(ApiRouteRecord(
                    repo=repo, filepath=filepath, framework="go_http",
                    http_method="ALL", path_pattern=path, handler_symbol=handler,
                    start_line=i, end_line=i
                ))

    # C# / ASP.NET Core Controllers & Minimal APIs
    elif language in ("c_sharp", "csharp"):
        controller_route = ""
        controller_name = ""
        group_prefixes: Dict[str, str] = {}
        for i, line in enumerate(lines, start=1):
            m_class = re.search(r'class\s+([a-zA-Z0-9_]+Controller)\b', line)
            if m_class:
                c_full = m_class.group(1)
                controller_name = c_full[:-10].lower() if c_full.endswith("Controller") else c_full.lower()

            m_croute = re.search(r'\[Route\s*\(\s*["\']([^"\']+)["\']\s*\)\]', line, re.IGNORECASE)
            if m_croute and not controller_route:
                controller_route = m_croute.group(1)

            m_grp = re.search(r'\b(\w+)\s*=\s*(\w+)\.MapGroup\s*\(\s*["\']([^"\']*)["\']', line, re.IGNORECASE)
            if m_grp:
                grp_var, parent_var, grp_path = m_grp.group(1), m_grp.group(2), m_grp.group(3)
                parent_prefix = group_prefixes.get(parent_var, "")
                group_prefixes[grp_var] = _join_route_prefix(parent_prefix, grp_path)

        for i, line in enumerate(lines, start=1):
            # Attribute routes [HttpGet("save")], [HttpGet("{id:guid}")], [HttpPost], etc.
            m_asp = re.search(r'\[(HttpGet|HttpPost|HttpPut|HttpDelete|HttpPatch)\s*(?:\(\s*["\']([^"\']*)["\']\s*\))?\]', line, re.IGNORECASE)
            if m_asp:
                method = m_asp.group(1)[4:].upper()
                sub_path = m_asp.group(2) or ""
                c_route_resolved = controller_route.replace("[controller]", controller_name) if controller_route else ""
                if sub_path.startswith("/"):
                    full_p = sub_path
                elif c_route_resolved:
                    full_p = _join_route_prefix(c_route_resolved, sub_path)
                else:
                    full_p = sub_path or "/"
                path = normalize_path_pattern(full_p)
                handler = None
                for offset in range(1, 6):
                    handler = find_enclosing_symbol(i + offset, symbols)
                    if handler and "." in handler:
                        break
                if not handler:
                    handler = find_enclosing_symbol(i + 1, symbols) or find_enclosing_symbol(i, symbols)
                routes.append(ApiRouteRecord(
                    repo=repo, filepath=filepath, framework="aspnet",
                    http_method=method, path_pattern=path, handler_symbol=handler,
                    start_line=i, end_line=i
                ))
                continue

            # Chained Minimal API: app.MapGroup("/api/v1").MapGet("/{id:guid}", ...)
            m_chained = re.search(
                r'\b(\w+)\.MapGroup\s*\(\s*["\']([^"\']*)["\']\s*\)\.Map(Get|Post|Put|Delete|Patch)\s*\(\s*["\']([^"\']*)["\'](?:\s*,\s*([a-zA-Z_][\w\.]*))?',
                line,
                re.IGNORECASE,
            )
            if m_chained:
                parent_prefix = group_prefixes.get(m_chained.group(1), "")
                grp_prefix = _join_route_prefix(parent_prefix, m_chained.group(2))
                method = m_chained.group(3).upper()
                path = normalize_path_pattern(_join_route_prefix(grp_prefix, m_chained.group(4)))
                arg_handler = m_chained.group(5)
                if arg_handler and arg_handler.lower() in ("async", "static"):
                    arg_handler = None
                handler = find_enclosing_symbol(i, symbols) or arg_handler
                routes.append(ApiRouteRecord(
                    repo=repo, filepath=filepath, framework="aspnet",
                    http_method=method, path_pattern=path, handler_symbol=handler,
                    start_line=i, end_line=i
                ))
                continue

            # Minimal APIs: app.MapGet("/path", ...) or groupVar.MapPost("/{id:guid}", Handler)
            m_min = re.search(
                r'\b(\w+)\.Map(Get|Post|Put|Delete|Patch)\s*\(\s*["\']([^"\']*)["\'](?:\s*,\s*([a-zA-Z_][\w\.]*))?',
                line,
                re.IGNORECASE,
            )
            if m_min:
                recv = m_min.group(1)
                if recv in group_prefixes or recv.lower() in ("app", "routes", "builder", "endpoints") or recv.lower().endswith(("group", "routes", "api")):
                    method = m_min.group(2).upper()
                    raw_p = _join_route_prefix(group_prefixes.get(recv, ""), m_min.group(3))
                    path = normalize_path_pattern(raw_p)
                    arg_handler = m_min.group(4)
                    if arg_handler and arg_handler.lower() in ("async", "static"):
                        arg_handler = None
                    handler = find_enclosing_symbol(i, symbols) or arg_handler
                    routes.append(ApiRouteRecord(
                        repo=repo, filepath=filepath, framework="aspnet",
                        http_method=method, path_pattern=path, handler_symbol=handler,
                        start_line=i, end_line=i
                    ))

    # Java / Spring
    elif language == "java":
        spring_prefix = ""
        for i, line in enumerate(lines, start=1):
            m_req_cls = re.search(r'@RequestMapping\s*\(\s*(?:value\s*=\s*|path\s*=\s*)?["\']([^"\']*)["\']', line)
            if m_req_cls and not spring_prefix:
                spring_prefix = m_req_cls.group(1)

            m_spring = re.search(r'@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)\s*(?:\(\s*(?:value\s*=\s*|path\s*=\s*)?["\']([^"\']*)["\']\s*\))?', line)
            if m_spring:
                method = m_spring.group(1)[:-7].upper()
                sub_p = m_spring.group(2) or ""
                full_p = normalize_path_pattern(f"{spring_prefix}/{sub_p}".replace("//", "/"))
                handler = find_enclosing_symbol(i + 1, symbols) or find_enclosing_symbol(i, symbols)
                routes.append(ApiRouteRecord(
                    repo=repo, filepath=filepath, framework="spring",
                    http_method=method, path_pattern=full_p, handler_symbol=handler,
                    start_line=i, end_line=i
                ))

    # ----------------------------------------------------
    # 2. CLIENT CALL EXTRACTION
    # ----------------------------------------------------
    from app.services.chunking.api_client_calls import extract_client_calls
    calls.extend(extract_client_calls(lines, repo, filepath, symbols, language))

    return routes, calls

