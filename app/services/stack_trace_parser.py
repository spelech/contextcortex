import re
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

RE_PYTHON_FRAME = re.compile(
    r'File\s+["\'](?P<path>[^"\']+)["\'],\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<func>[a-zA-Z0-9_<>\.]+))?',
    re.IGNORECASE,
)

RE_CSHARP_FRAME = re.compile(
    r'(?:^\s*at\s+(?P<func>[A-Za-z_][A-Za-z0-9_<>`\.\$]*?)\s*(?:\([^)]*\))?\s+)?'
    r'\bin\s+(?P<path>(?:[A-Za-z]:[\\/])?[^\r\n:]+?\.csx?):line\s+(?P<line>\d+)',
    re.IGNORECASE,
)

RE_JAVA_FRAME = re.compile(
    r'at\s+(?P<pkg_class>[a-zA-Z0-9_\$]+(?:\.[a-zA-Z0-9_\$]+)*)\.(?P<method>[a-zA-Z0-9_<>\$]+)'
    r'\((?P<filename>[a-zA-Z0-9_\-]+\.(?:java|kt)):(?P<line>\d+)\)',
    re.IGNORECASE,
)

RE_NODE_PAREN_FRAME = re.compile(
    r'^\s*at\s+(?:async\s+)?(?P<func>[^\(\r\n]+?)\s+\((?P<loc>[^\)\r\n]+)\)\s*$',
    re.IGNORECASE,
)

RE_NODE_BARE_FRAME = re.compile(
    r'^\s*at\s+(?:async\s+)?(?P<loc>[^\s\(\)]+:\d+(?::\d+)?)\s*$',
    re.IGNORECASE,
)

RE_BROWSER_AT_SIGN_FRAME = re.compile(
    r'^\s*(?P<func>[a-zA-Z0-9_<>\.\$/]+)?@(?P<loc>(?:https?://|webpack://|vite://|file://|/)[^\s]+:\d+(?::\d+)?)\s*$',
    re.IGNORECASE,
)

RE_LOC_LINE_COL = re.compile(r'^(?P<path>.+?):(?P<line>\d+)(?::\d+)?$')

RE_COBOL_PARAGRAPH_FRAME = re.compile(
    r'\bIn\s+(?:paragraph|section)\s+(?P<func>[A-Za-z0-9_\-]+)\s+of\s+program\s+(?P<program>[A-Za-z0-9_\-]+)'
    r'\s*\((?P<path>[^\)\r\n:]+?\.(?:cbl|cob|cpy)):\s*(?P<line>\d+)\)',
    re.IGNORECASE,
)

RE_COBOL_ABEND_FRAME = re.compile(
    r'\b(?:ABEND\s+(?P<abend>[A-Z0-9]{3,8})\s+|IGZ\d+[A-Z]\s+.*?)?\bin\s+program\s+(?P<program>[A-Za-z0-9_\-]+)'
    r'(?:\s+(?:paragraph|section)\s+(?P<func>[A-Za-z0-9_\-]+))?'
    r'\s+at\s+(?:statement|line)\s+(?P<line>\d+)',
    re.IGNORECASE,
)

RE_COBOL_DIAG_FRAME = re.compile(
    r'^(?:libcob:\s*)?(?P<path>(?:[A-Za-z]:[\\/])?[A-Za-z0-9_.\-/\\]+?\.(?:cbl|cob|cpy)):\s*(?P<line>\d+)(?::\s*|\s+)',
    re.IGNORECASE,
)

RE_GENERIC_FRAME = re.compile(
    r'(?:^|[\s\(\[\'\"])(?P<path>(?:[A-Za-z]:[\\/])?(?:[a-zA-Z0-9_.\-]+[/\\])+[a-zA-Z0-9_.\-]+'
    r'\.(?:go|rs|py|ts|tsx|js|jsx|mjs|cjs|cs|csx|cbl|cob|cpy|java|kt|c|cpp|h|hpp|rb|php)):(?P<line>\d+)(?::\d+)?',
    re.IGNORECASE,
)

RE_NODE_AT_FRAME = RE_NODE_PAREN_FRAME

RE_QUOTED_ERROR = re.compile(r'["\']([^"\'\r\n]{6,120})["\']')
RE_EXCEPTION_NAME = re.compile(
    r'\b(?:[A-Z][A-Za-z0-9_]*(?:Error|Exception|Fault|Panic)|ABEND\s+[A-Z0-9]{3,8}|S0C[1479A-F]|IGZ\d{4}[A-Z])\b'
)
RE_SYMBOL_CANDIDATE = re.compile(
    r'\b(?:'
    r'[A-Z][A-Za-z0-9_]{2,}(?:\.[A-Za-z_][A-Za-z0-9_]{2,})+'
    r'|[a-z][a-z0-9_]{1,}_[a-z0-9_]{2,}'
    r'|[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]+'
    r'|[a-z]+[A-Z][A-Za-z0-9]+'
    r'|[0-9]{3,4}-[A-Z0-9][A-Z0-9\-]{2,}'
    r'|[A-Z]{2,}[0-9_\-]*-[A-Z0-9\-]{2,}'
    r')\b'
)
RE_HTTP_ROUTE = re.compile(
    r'(?:(GET|POST|PUT|DELETE|PATCH)\s+(?:https?://[^/\s]+)?)?(/[\w\-/{}:]+(?:/[\w\-/{}:]*)*)',
    re.IGNORECASE,
)

_STOP_IDENTIFIERS = {
    "RuntimeError", "ValueError", "TypeError", "KeyError", "AttributeError", "IndexError",
    "OperationalError", "DatabaseError", "IntegrityError", "HTTPException",
    "InvalidOperationException", "ArgumentException", "NullReferenceException",
    "Exception", "Error", "Traceback", "MostRecentCallLast",
}

_CONTAINER_BUILD_PREFIXES = (
    "/usr/src/app/",
    "/var/task/",
    "/workspace/",
    "/opt/app/",
    "/build/",
)

_APP_SUBROOT_DIRS = (
    "frontend/",
    "backend/",
    "src/",
    "packages/",
    "apps/",
    "node_modules/",
    "client/",
    "server/",
)


def normalize_stack_path(raw_path: Optional[str]) -> str:
    """Normalizes stack-trace paths across Windows, Docker containers, CI workspaces, and dev URLs."""
    if not raw_path:
        return ""
    p = raw_path.strip().strip("'\"()")
    if not p:
        return ""
    p = p.replace("\\", "/")

    if p.startswith(("http://", "https://", "webpack://", "webpack-internal://", "vite://", "file://")):
        parsed = urlparse(p)
        p = parsed.path or ""
    else:
        if "?" in p:
            p = p.split("?", 1)[0]
        if "#" in p:
            p = p.split("#", 1)[0]

    if "://" in p:
        scheme, rest = p.split("://", 1)
        if re.fullmatch(r"[A-Za-z0-9_.\-]+", scheme):
            p = rest

    if p.startswith("/@fs/"):
        p = p[len("/@fs/"):]
    p = re.sub(r"^/+([A-Za-z]:/)", r"\1", p)
    p = re.sub(r"^[A-Za-z]:/+", "", p)

    p_with_slash = "/" + p.lstrip("/")
    ci_match = re.match(
        r"^(?:/home/runner/work/[^/]+/[^/]+|/(?:azp/)?agent/_work/\d+/s|/actions-runner/_work/[^/]+/[^/]+)/(.+)$",
        p_with_slash,
    )
    if ci_match:
        p = ci_match.group(1)
    else:
        for prefix in _CONTAINER_BUILD_PREFIXES:
            if p_with_slash.startswith(prefix):
                p = p_with_slash[len(prefix):]
                break
        else:
            if p.startswith("/app/"):
                after_app = p[len("/app/"):]
                p = after_app if after_app.startswith(_APP_SUBROOT_DIRS) else p.lstrip("/")
            elif p.startswith("/"):
                p = p.lstrip("/")

    while p.startswith("./"):
        p = p[2:]
    return re.sub(r"/{2,}", "/", p).strip()


def _clean_diag_path(p: Optional[str]) -> str:
    if not p:
        return ""
    norm = p.replace("\\", "/")
    if "://" in norm and not norm.startswith(("http://", "https://", "webpack://", "vite://", "file://")):
        return norm.split("://", 1)[1].lstrip("/")
    return normalize_stack_path(norm)


def candidate_path_suffixes(filepath: str) -> List[str]:
    """Generates progressive relative suffixes from longest to basename for container/build prefix matching."""
    clean = _clean_diag_path(filepath).strip("/")
    if not clean:
        return []
    parts = [seg for seg in clean.split("/") if seg and seg != "."]
    suffixes: List[str] = []
    for idx in range(len(parts)):
        candidate = "/".join(parts[idx:])
        if candidate not in suffixes:
            suffixes.append(candidate)
    return suffixes


def _is_test_path(filepath: str) -> bool:
    norm = _clean_diag_path(filepath).lower()
    parts = [p for p in norm.split("/") if p]
    if any(
        p in ("tests", "test", "__tests__", "e2e", "spec", "specs")
        or p.endswith(".tests")
        or p.endswith("_tests")
        for p in parts
    ):
        return True
    fname = parts[-1] if parts else ""
    return (
        fname.startswith("test_")
        or fname.endswith(("_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", "tests.cs", "test.cs"))
    )


def _clean_csharp_func(func_raw: Optional[str]) -> Optional[str]:
    if not func_raw:
        return None
    fn = func_raw.strip()
    m_async = re.match(r"^(?P<prefix>.+)\.<(?P<method>[A-Za-z0-9_]+)>d__\d+(?:\.MoveNext)?$", fn)
    if m_async:
        return f"{m_async.group('prefix')}.{m_async.group('method')}"
    return re.sub(r"`\d+", "", fn)


def _extract_loc_path_and_line(loc: str) -> Optional[Tuple[str, int]]:
    loc_clean = loc.strip()
    if not loc_clean or loc_clean.startswith("<") or loc_clean.startswith("node:") or loc_clean.startswith("internal/"):
        return None
    m = RE_LOC_LINE_COL.match(loc_clean)
    if not m:
        return None
    norm_p = normalize_stack_path(m.group("path"))
    if not norm_p:
        return None
    return norm_p, int(m.group("line"))


def parse_stack_frames(text: str) -> List[Dict[str, Any]]:
    """Parses stack frames across Python, C#/.NET, TS/JS/React/Vite, COBOL, Java, Go, and Rust."""
    frames: List[Dict[str, Any]] = []
    seen = set()

    def _add_frame(raw_path: str, line_no: int, func: Optional[str] = None, extra: Optional[Dict[str, Any]] = None) -> None:
        norm_p = normalize_stack_path(raw_path)
        if not norm_p or line_no < 1:
            return
        clean_fn = func.strip() if isinstance(func, str) and func.strip() else None
        key = (norm_p, line_no, clean_fn)
        if key not in seen:
            seen.add(key)
            entry: Dict[str, Any] = {"path": norm_p, "line": line_no, "function": clean_fn}
            if extra:
                entry.update(extra)
            frames.append(entry)

    for line in (text or "").splitlines():
        trimmed = line.strip()
        if not trimmed:
            continue

        m_py = RE_PYTHON_FRAME.search(trimmed)
        if m_py:
            _add_frame(m_py.group("path"), int(m_py.group("line")), m_py.group("func"))
            continue

        m_cs = RE_CSHARP_FRAME.search(trimmed)
        if m_cs:
            _add_frame(m_cs.group("path"), int(m_cs.group("line")), _clean_csharp_func(m_cs.group("func")))
            continue

        m_cob_para = RE_COBOL_PARAGRAPH_FRAME.search(trimmed)
        if m_cob_para:
            _add_frame(
                m_cob_para.group("path"),
                int(m_cob_para.group("line")),
                m_cob_para.group("func"),
                extra={"program": m_cob_para.group("program")},
            )
            continue

        m_cob_abend = RE_COBOL_ABEND_FRAME.search(trimmed)
        if m_cob_abend:
            prog = m_cob_abend.group("program")
            para = m_cob_abend.group("func") or prog
            _add_frame(
                f"{prog}.CBL",
                int(m_cob_abend.group("line")),
                para,
                extra={"program": prog},
            )
            continue

        m_cob_diag = RE_COBOL_DIAG_FRAME.search(trimmed)
        if m_cob_diag:
            _add_frame(m_cob_diag.group("path"), int(m_cob_diag.group("line")), None)
            continue

        m_java = RE_JAVA_FRAME.search(trimmed)
        if m_java:
            pkg_c, meth = m_java.group("pkg_class"), m_java.group("method")
            fn = f"{pkg_c}.{meth}" if pkg_c and meth else (meth or pkg_c)
            _add_frame(m_java.group("filename"), int(m_java.group("line")), fn)
            continue

        m_node_p = RE_NODE_PAREN_FRAME.match(trimmed)
        if m_node_p:
            loc_res = _extract_loc_path_and_line(m_node_p.group("loc"))
            if loc_res:
                fn_raw = re.sub(r"^async\s+", "", m_node_p.group("func").strip(), flags=re.IGNORECASE)
                _add_frame(loc_res[0], loc_res[1], fn_raw)
                continue

        m_node_b = RE_NODE_BARE_FRAME.match(trimmed)
        if m_node_b:
            loc_res = _extract_loc_path_and_line(m_node_b.group("loc"))
            if loc_res:
                _add_frame(loc_res[0], loc_res[1], None)
                continue

        m_browser = RE_BROWSER_AT_SIGN_FRAME.match(trimmed)
        if m_browser:
            loc_res = _extract_loc_path_and_line(m_browser.group("loc"))
            if loc_res:
                _add_frame(loc_res[0], loc_res[1], m_browser.group("func"))
                continue

        m_gen = RE_GENERIC_FRAME.search(trimmed)
        if m_gen:
            _add_frame(m_gen.group("path"), int(m_gen.group("line")), None)

    return frames


def extract_diagnostic_signals(text: str) -> Dict[str, Any]:
    """Extracts quoted error strings, exception/abend identifiers, code symbols, and HTTP routes."""
    errors: List[str] = []
    exceptions: List[str] = []
    symbols: List[str] = []
    routes: List[Tuple[Optional[str], str]] = []
    seen_err, seen_exc, seen_sym, seen_routes = set(), set(), set(), set()

    src = text or ""
    for m in RE_QUOTED_ERROR.finditer(src):
        c = m.group(1).strip()
        if c and not re.search(r"\.(?:py|cs|ts|tsx|js|jsx|mjs|cjs|cbl|cob|cpy)$", c, re.IGNORECASE):
            if c not in seen_err:
                seen_err.add(c)
                errors.append(c)

    for m in RE_EXCEPTION_NAME.finditer(src):
        c = re.sub(r"\s+", " ", m.group(0).strip())
        if c and c not in seen_exc:
            seen_exc.add(c)
            exceptions.append(c)
            if c.upper().startswith("ABEND "):
                code_only = c.split(" ", 1)[1].strip()
                if code_only and code_only not in seen_exc:
                    seen_exc.add(code_only)
                    exceptions.append(code_only)

    for m in RE_COBOL_PARAGRAPH_FRAME.finditer(src):
        for grp in ("func", "program"):
            val = m.group(grp)
            if val and val not in seen_sym:
                seen_sym.add(val)
                symbols.append(val)

    for m in RE_COBOL_ABEND_FRAME.finditer(src):
        for grp in ("func", "program"):
            val = m.group(grp)
            if val and val not in seen_sym:
                seen_sym.add(val)
                symbols.append(val)

    for m in RE_SYMBOL_CANDIDATE.finditer(src):
        c = m.group(0).strip()
        if c and c not in _STOP_IDENTIFIERS and c not in seen_exc and c not in seen_sym:
            seen_sym.add(c)
            symbols.append(c)

    for line in src.splitlines():
        if "http://" in line or "https://" in line:
            if RE_NODE_BARE_FRAME.match(line.strip()) or RE_NODE_PAREN_FRAME.match(line.strip()):
                continue
        for m in RE_HTTP_ROUTE.finditer(line):
            meth = m.group(1).upper() if m.group(1) else None
            p = m.group(2).strip()
            if len(p) <= 1 or p.endswith("//") or p.startswith("//"):
                continue
            if not meth and any(
                p.lower().startswith(src_prefix)
                for src_prefix in ("/app/", "/src/", "/usr/", "/var/", "/opt/", "/home/", "/tmp/")
            ):
                continue
            key = (meth, p)
            if key not in seen_routes:
                seen_routes.add(key)
                routes.append(key)

    return {
        "quoted_errors": errors[:25],
        "exceptions": exceptions[:25],
        "symbols": symbols[:30],
        "routes": routes[:20],
    }


def build_semantic_query(issue_text: str, signals: Dict[str, Any], frames: List[Dict[str, Any]]) -> str:
    """Strips boilerplate stack-trace file/line formatting so hybrid search focuses on symbols and errors."""
    parts: List[str] = []
    for f in frames:
        if f.get("function"):
            parts.append(str(f["function"]))
        if f.get("program"):
            parts.append(str(f["program"]))
        if f.get("path"):
            parts.append(_clean_diag_path(str(f["path"])).split("/")[-1])
    parts.extend(signals.get("symbols", []))
    parts.extend(signals.get("exceptions", []))
    parts.extend(signals.get("quoted_errors", []))
    for _, route_path in signals.get("routes", []):
        parts.append(route_path)

    cleaned_lines: List[str] = []
    for line in (issue_text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("Traceback (most recent call last)"):
            continue
        if (
            RE_PYTHON_FRAME.search(s)
            or RE_CSHARP_FRAME.search(s)
            or RE_JAVA_FRAME.search(s)
            or RE_NODE_PAREN_FRAME.match(s)
            or RE_NODE_BARE_FRAME.match(s)
        ):
            continue
        cleaned_lines.append(s)
    if cleaned_lines:
        parts.append(" ".join(cleaned_lines))

    dedup_tokens = list(OrderedDict.fromkeys(p for p in parts if p))
    joined = " ".join(dedup_tokens) if dedup_tokens else (issue_text or "")
    return joined[:2000]
