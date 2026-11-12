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

def match_route_and_call(route_path: str, call_url: str) -> bool:
    """Checks if a client call URL matches a server route pattern."""
    norm_route = normalize_path_pattern(route_path)
    norm_call = normalize_path_pattern(call_url)
    if norm_route == norm_call:
        return True
    rx = route_pattern_to_regex(norm_route)
    return bool(rx.match(norm_call))

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

    for i, line in enumerate(lines, start=1):
        # fetch(...) or apiRequest<T>(...) / httpRequest(...) in JS/TS
        m_fetch = re.search(r'\b(?:fetch|apiRequest|httpRequest|requestJson)\b[\s\S]*?\(\s*(["\'`]([^"\'`]+)["\'`])', line)
        if m_fetch:
            url_raw = m_fetch.group(2)
            url_pattern = normalize_path_pattern(url_raw)
            # Infer method if method: 'POST' is on same line or within options object in next 4 lines
            tail_on_line = line[m_fetch.end():]
            next_lines = "\n".join(lines[i:min(len(lines), i + 4)])
            call_window = tail_on_line + "\n" + next_lines
            # Stop at semicolon closing statement so we don't bleed into a subsequent fetch call
            stmt_window = call_window.split(";")[0]
            m_method = re.search(r'method\s*:\s*["\'](GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)["\']', stmt_window, re.IGNORECASE)
            method = m_method.group(1).upper() if m_method else "GET"
            caller = find_enclosing_symbol(i, symbols)
            calls.append(ApiClientCallRecord(
                repo=repo, filepath=filepath, http_method=method,
                url_pattern=url_pattern, caller_symbol=caller, line_number=i
            ))
            continue

        # axios.get / post / etc.
        m_axios = re.search(r'\baxios\.(get|post|put|delete|patch|options|head)\s*\(\s*(["\'`]([^"\'`]+)["\'`])', line, re.IGNORECASE)
        if m_axios:
            method = m_axios.group(1).upper()
            url_raw = m_axios.group(3)
            url_pattern = normalize_path_pattern(url_raw)
            caller = find_enclosing_symbol(i, symbols)
            calls.append(ApiClientCallRecord(
                repo=repo, filepath=filepath, http_method=method,
                url_pattern=url_pattern, caller_symbol=caller, line_number=i
            ))
            continue

        # Python requests / httpx
        m_req = re.search(r'\b(?:requests|httpx|client)\.(get|post|put|delete|patch|options|head)\s*\(\s*f?["\']([^"\']+)["\']', line, re.IGNORECASE)
        if m_req:
            method = m_req.group(1).upper()
            url_raw = m_req.group(2)
            url_pattern = normalize_path_pattern(url_raw)
            caller = find_enclosing_symbol(i, symbols)
            calls.append(ApiClientCallRecord(
                repo=repo, filepath=filepath, http_method=method,
                url_pattern=url_pattern, caller_symbol=caller, line_number=i
            ))
            continue

        # Go http client
        m_go_http = re.search(r'\bhttp\.(Get|Post|Head)\s*\(\s*["\']([^"\']+)["\']', line)
        if m_go_http:
            method = m_go_http.group(1).upper()
            url_raw = m_go_http.group(2)
            url_pattern = normalize_path_pattern(url_raw)
            caller = find_enclosing_symbol(i, symbols)
            calls.append(ApiClientCallRecord(
                repo=repo, filepath=filepath, http_method=method,
                url_pattern=url_pattern, caller_symbol=caller, line_number=i
            ))
            continue

        # C# HttpClient (GetAsync, PostAsync, etc.)
        m_cs_client = re.search(r'\b(?:httpClient|_httpClient|client)\.(GetAsync|PostAsync|PutAsync|DeleteAsync|GetFromJsonAsync|PostAsJsonAsync)\s*\(\s*["\']([^"\']+)["\']', line, re.IGNORECASE)
        if m_cs_client:
            method_raw = m_cs_client.group(1)
            method = "GET" if "Get" in method_raw else "POST" if "Post" in method_raw else "PUT" if "Put" in method_raw else "DELETE" if "Delete" in method_raw else None
            url_raw = m_cs_client.group(2)
            url_pattern = normalize_path_pattern(url_raw)
            caller = find_enclosing_symbol(i, symbols)
            calls.append(ApiClientCallRecord(
                repo=repo, filepath=filepath, http_method=method,
                url_pattern=url_pattern, caller_symbol=caller, line_number=i
            ))
            continue

    return routes, calls

