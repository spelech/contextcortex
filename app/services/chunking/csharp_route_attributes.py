"""General resolution of custom C# route and HTTP-method attributes from source definitions.

Instead of hardcoding framework- or project-specific attribute names (such as `[V3ApiController]`
or `[RestGetById]`), this module parses C# attribute class declarations (`class <Name>Attribute : ...`)
to determine:
1. Whether a class-level attribute implements `IRouteTemplateProvider` / `RouteAttribute` (or inherits
   from a custom attribute that does) and what its route `Template` string is (resolving constructor
   parameters, default values, constants, and `: base(...)` argument forwarding).
2. Whether a method-level attribute implements `IActionHttpMethodProvider` / `IRouteTemplateProvider`
   or inherits from `HttpGetAttribute`, `HttpPostAttribute`, `HttpPutAttribute`, `HttpDeleteAttribute`,
   `HttpPatchAttribute`, or `HttpMethodAttribute`, and what its HTTP verb and sub-route template are.
"""

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_BUILTIN_METHOD_ATTRS: Dict[str, str] = {
    "HttpGet": "GET",
    "HttpPost": "POST",
    "HttpPut": "PUT",
    "HttpDelete": "DELETE",
    "HttpPatch": "PATCH",
    "HttpOptions": "OPTIONS",
    "HttpHead": "HEAD",
}

_ROUTE_INTERFACES = frozenset({
    "IRouteTemplateProvider",
    "RouteAttribute",
    "Route",
})

_METHOD_INTERFACES = frozenset({
    "IActionHttpMethodProvider",
    "HttpMethodAttribute",
})

_CLASS_DECL_RE = re.compile(
    r"\bclass\s+([A-Za-z_]\w*Attribute)\s*(?::\s*([^{]+))?\{"
)
_CONST_STRING_RE = re.compile(
    r'\bconst\s+string\s+([A-Za-z_]\w*)\s*=\s*"([^"]*)"\s*;'
)
_TEMPLATE_ASSIGN_RE = re.compile(
    r'\bTemplate\s*(?:=>|=)\s*(\$?"[^"]*")\s*;'
)
_HTTP_METHODS_RE = re.compile(
    r'\bHttpMethods\b[^{;]*(?:\{\s*get[^;]*\}|=>)?[^{;]*\{\s*"(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)"',
    re.IGNORECASE,
)


@dataclass
class CSharpAttributeSpec:
    """Resolved or raw declaration metadata for a custom C# attribute class."""

    short_name: str
    class_name: str
    base_types: List[str] = field(default_factory=list)
    constants: Dict[str, str] = field(default_factory=dict)
    ctor_params: List[Tuple[str, Optional[str]]] = field(default_factory=list)
    base_call_args: List[str] = field(default_factory=list)
    raw_template: Optional[str] = None
    http_method: Optional[str] = None
    is_route_provider: bool = False


def _strip_attr_suffix(name: str) -> str:
    clean = name.strip().split(".")[-1]
    return clean[:-9] if clean.endswith("Attribute") and len(clean) > 9 else clean


def _find_matching_brace(text: str, open_idx: int) -> int:
    depth = 0
    for idx in range(open_idx, len(text)):
        if text[idx] == "{":
            depth += 1
        elif text[idx] == "}":
            depth -= 1
            if depth == 0:
                return idx
    return len(text)


def _split_top_level_commas(text: str) -> List[str]:
    parts: List[str] = []
    cur: List[str] = []
    depth = 0
    in_str = False
    for ch in text:
        if ch == '"':
            in_str = not in_str
            cur.append(ch)
        elif not in_str:
            if ch in "(<[{":
                depth += 1
                cur.append(ch)
            elif ch in ")>]}":
                depth = max(0, depth - 1)
                cur.append(ch)
            elif ch == "," and depth == 0:
                parts.append("".join(cur).strip())
                cur = []
            else:
                cur.append(ch)
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur).strip())
    return [p for p in parts if p]


def _resolve_value_token(token: str, constants: Dict[str, str], env: Dict[str, str]) -> str:
    t = token.strip()
    if t.startswith('$"') and t.endswith('"'):
        inner = t[2:-1]
        return re.sub(
            r"\{([A-Za-z_]\w*)\}",
            lambda m: env.get(m.group(1), constants.get(m.group(1), m.group(0))),
            inner,
        )
    if t.startswith('"') and t.endswith('"'):
        return t[1:-1]
    if t in env:
        return env[t]
    if t in constants:
        return constants[t]
    return t


def parse_csharp_attribute_specs(code: str) -> Dict[str, CSharpAttributeSpec]:
    """Extracts C# `*Attribute` class definitions from a source string."""
    specs: Dict[str, CSharpAttributeSpec] = {}
    if "Attribute" not in code:
        return specs

    for m_cls in _CLASS_DECL_RE.finditer(code):
        cls_name = m_cls.group(1)
        short = _strip_attr_suffix(cls_name)
        bases_raw = m_cls.group(2) or ""
        bases = [
            re.sub(r"<.*>", "", b).strip().split(".")[-1]
            for b in _split_top_level_commas(bases_raw)
            if b.strip()
        ]
        body_start = m_cls.end() - 1
        body_end = _find_matching_brace(code, body_start)
        body = code[body_start + 1 : body_end]

        consts: Dict[str, str] = {
            m_c.group(1): m_c.group(2) for m_c in _CONST_STRING_RE.finditer(body)
        }

        ctor_params: List[Tuple[str, Optional[str]]] = []
        base_args: List[str] = []
        ctor_re = re.compile(
            r"\bpublic\s+"
            + re.escape(cls_name)
            + r"\s*\(([^)]*)\)\s*(?::\s*base\s*\(([^)]*)\))?"
        )
        m_ctor = ctor_re.search(body)
        if m_ctor:
            raw_params = _split_top_level_commas(m_ctor.group(1))
            for rp in raw_params:
                eq_parts = rp.split("=", 1)
                lhs = eq_parts[0].strip()
                p_name = lhs.split()[-1].strip() if lhs else ""
                default_val: Optional[str] = None
                if len(eq_parts) == 2:
                    default_val = _resolve_value_token(eq_parts[1].strip(), consts, {})
                if p_name:
                    ctor_params.append((p_name, default_val))
            if m_ctor.group(2) is not None:
                base_args = _split_top_level_commas(m_ctor.group(2))

        raw_template: Optional[str] = None
        m_tpl = _TEMPLATE_ASSIGN_RE.search(body)
        if m_tpl:
            raw_template = m_tpl.group(1)

        http_method: Optional[str] = None
        m_verb = _HTTP_METHODS_RE.search(body)
        if m_verb:
            http_method = m_verb.group(1).upper()

        is_route = any(b in _ROUTE_INTERFACES for b in bases) or raw_template is not None
        for b in bases:
            b_short = _strip_attr_suffix(b)
            if b_short in _BUILTIN_METHOD_ATTRS:
                http_method = _BUILTIN_METHOD_ATTRS[b_short]
                is_route = True
            elif b in _METHOD_INTERFACES:
                is_route = True

        spec = CSharpAttributeSpec(
            short_name=short,
            class_name=cls_name,
            base_types=bases,
            constants=consts,
            ctor_params=ctor_params,
            base_call_args=base_args,
            raw_template=raw_template,
            http_method=http_method,
            is_route_provider=is_route,
        )
        specs[short] = spec
        specs[cls_name] = spec

    return specs


def evaluate_attribute_usage(
    attr_name: str,
    call_args_raw: Optional[str],
    specs: Dict[str, CSharpAttributeSpec],
    depth: int = 0,
) -> Optional[Tuple[Optional[str], str]]:
    """Resolves `[AttrName(args)]` against parsed `CSharpAttributeSpec` definitions.

    Returns `(http_method_or_none, route_template)` if the attribute is a route or
    HTTP action attribute, or `None` if it is an unrelated attribute (e.g., `[SkipValidation]`).
    """
    if depth > 6:
        return None

    short = _strip_attr_suffix(attr_name)
    call_args = _split_top_level_commas(call_args_raw or "")

    if short == "Route":
        tpl = _resolve_value_token(call_args[0], {}, {}) if call_args else ""
        return None, tpl

    if short in _BUILTIN_METHOD_ATTRS:
        tpl = _resolve_value_token(call_args[0], {}, {}) if call_args else ""
        return _BUILTIN_METHOD_ATTRS[short], tpl

    spec = specs.get(short) or specs.get(attr_name)
    if spec is None:
        return None

    # Bind constructor parameters using call_args or defaults
    env: Dict[str, str] = {}
    for idx, (p_name, p_default) in enumerate(spec.ctor_params):
        if idx < len(call_args):
            env[p_name] = _resolve_value_token(call_args[idx], spec.constants, env)
        elif p_default is not None:
            env[p_name] = p_default
        # Also bind capitalized property alias (e.g., `version` -> `Version` when `Version = version;`)
        if p_name in env and p_name[0].islower():
            env.setdefault(p_name[0].upper() + p_name[1:], env[p_name])

    # Check if this attribute delegates to a base attribute class
    for b in spec.base_types:
        b_short = _strip_attr_suffix(b)
        if b_short in _BUILTIN_METHOD_ATTRS or b_short == "Route" or b_short in specs or b in specs:
            resolved_base_args = [
                f'"{_resolve_value_token(arg, spec.constants, env)}"'
                for arg in spec.base_call_args
            ]
            base_res = evaluate_attribute_usage(
                b_short,
                ", ".join(resolved_base_args),
                specs,
                depth=depth + 1,
            )
            if base_res is not None:
                base_method, base_tpl = base_res
                return spec.http_method or base_method, base_tpl

    if not spec.is_route_provider and spec.http_method is None:
        return None

    tpl_out = ""
    if spec.raw_template is not None:
        tpl_out = _resolve_value_token(spec.raw_template, spec.constants, env)
    elif call_args:
        tpl_out = _resolve_value_token(call_args[0], spec.constants, env)

    return spec.http_method, tpl_out


_REPO_ATTR_CACHE: Dict[str, Dict[str, CSharpAttributeSpec]] = {}


def load_repo_csharp_attributes(filepath: str, code: str) -> Dict[str, CSharpAttributeSpec]:
    """Loads C# custom attribute specs from the current file and any `*Attribute*.cs` files in the same repo tree."""
    local_specs = parse_csharp_attribute_specs(code)
    norm_fp = (filepath or "").replace("\\", "/")
    if "://" in norm_fp or not os.path.isabs(norm_fp):
        return local_specs

    # Walk up to find the repository/solution root directory
    cur_dir = os.path.dirname(norm_fp)
    repo_root: Optional[str] = None
    for _ in range(8):
        if not cur_dir or cur_dir == "/":
            break
        if os.path.exists(os.path.join(cur_dir, ".git")) or any(
            f.endswith(".sln") for f in (os.listdir(cur_dir) if os.path.isdir(cur_dir) else ())
        ):
            repo_root = cur_dir
            break
        parent = os.path.dirname(cur_dir)
        if parent == cur_dir:
            break
        cur_dir = parent

    if not repo_root:
        return local_specs

    if repo_root not in _REPO_ATTR_CACHE:
        scanned: Dict[str, CSharpAttributeSpec] = {}
        try:
            for root, dirs, files in os.walk(repo_root):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("bin", "obj", "node_modules", ".git")]
                for fname in files:
                    if fname.endswith(".cs") and "Attribute" in fname:
                        fpath = os.path.join(root, fname)
                        try:
                            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                                scanned.update(parse_csharp_attribute_specs(f.read()))
                        except Exception:
                            pass
        except Exception:
            pass
        _REPO_ATTR_CACHE[repo_root] = scanned

    merged = dict(_REPO_ATTR_CACHE[repo_root])
    merged.update(local_specs)
    return merged


def cache_repo_csharp_attributes(repo: str, root_dir: str) -> Dict[str, CSharpAttributeSpec]:
    """Scans a cloned repository directory for `*Attribute*.cs` files and caches specs under `repo`."""
    scanned: Dict[str, CSharpAttributeSpec] = {}
    if os.path.isdir(root_dir):
        try:
            for root, dirs, files in os.walk(root_dir):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("bin", "obj", "node_modules", ".git")]
                for fname in files:
                    if fname.endswith(".cs") and "Attribute" in fname:
                        fpath = os.path.join(root, fname)
                        try:
                            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                                scanned.update(parse_csharp_attribute_specs(f.read()))
                        except Exception:
                            pass
        except Exception:
            pass
    _REPO_ATTR_CACHE[f"repo:{repo}"] = scanned
    _REPO_ATTR_CACHE[root_dir.replace("\\", "/")] = scanned
    return scanned


def get_cached_csharp_attributes(repo: str, filepath: str, code: str) -> Dict[str, CSharpAttributeSpec]:
    """Returns merged custom attribute specs from repo cache, disk tree (if local), and current file."""
    specs: Dict[str, CSharpAttributeSpec] = {}
    repo_key = f"repo:{repo}"
    if repo_key in _REPO_ATTR_CACHE:
        specs.update(_REPO_ATTR_CACHE[repo_key])
    specs.update(load_repo_csharp_attributes(filepath, code))
    return specs


_ATTR_USAGE_RE = re.compile(r"\[\s*([A-Za-z_]\w*)\s*(?:\(([^)\]]*)\))?\s*\]")


def resolve_controller_route_from_attributes(
    lines: List[str],
    class_line_idx: int,
    specs: Dict[str, CSharpAttributeSpec],
) -> str:
    """Resolves custom or `[Route(...)]` class-level route template above a C# controller class declaration."""
    start_idx = max(0, class_line_idx - 10)
    for idx in range(start_idx, class_line_idx + 1):
        for m_attr in _ATTR_USAGE_RE.finditer(lines[idx]):
            attr_name = m_attr.group(1)
            attr_args = m_attr.group(2)
            res = evaluate_attribute_usage(attr_name, attr_args, specs)
            if res is not None:
                method, tpl = res
                if method is None and tpl:
                    return tpl
    return ""


def resolve_method_route_from_attribute_line(
    line: str,
    specs: Dict[str, CSharpAttributeSpec],
) -> Optional[Tuple[str, str]]:
    """Resolves a method-level HTTP verb and sub-route template from a line with `[SomeAttr(...)]`."""
    for m_attr in _ATTR_USAGE_RE.finditer(line):
        attr_name = m_attr.group(1)
        attr_args = m_attr.group(2)
        res = evaluate_attribute_usage(attr_name, attr_args, specs)
        if res is not None and res[0] is not None:
            return res[0], res[1]
    return None

