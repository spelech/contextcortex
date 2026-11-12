import os
from typing import Optional, Dict, Any, List, Tuple

COMPILED_BUNDLE_SEGMENTS = (
    "/www/assets/",
    "www/assets/",
    "/wwwroot/_framework/",
    "wwwroot/_framework/",
    "/wwwroot/assets/",
    "wwwroot/assets/",
    "/dist/assets/",
    "dist/assets/",
    "/build/static/",
    "build/static/",
    "/node_modules/",
    "node_modules/",
    "/.next/static/",
    ".next/static/",
    "/.nuxt/",
    ".nuxt/",
)

COMPILED_BUNDLE_SUFFIXES = (
    ".min.js",
    ".min.mjs",
    ".min.css",
    ".bundle.js",
    ".chunk.js",
    ".wasm",
    ".js.map",
    ".css.map",
)

CLASS_LIKE_AST_KINDS = {
    "class",
    "class_declaration",
    "interface",
    "interface_declaration",
    "struct",
    "struct_declaration",
    "enum",
    "enum_declaration",
    "trait",
    "type",
    "type_alias_declaration",
    "record",
    "record_declaration",
    "record_definition",
    "program",
    "program_definition",
}

EDGE_PRIORITY = {
    "ROUTES_TO": 0,
    "HANDLES": 1,
    "IMPORTS": 2,
    "CALLS": 3,
    "DOC_LINKS_TO": 4,
    "DEFINES": 5,
}

MAX_TOPOLOGY_NODES = 1500
MAX_TOPOLOGY_EDGES = 2500


def is_compiled_bundle_path(filepath: Optional[str]) -> bool:
    """Returns True if filepath points to a compiled bundle, framework artifact, or minified asset."""
    if not filepath:
        return False
    norm = filepath.replace("\\", "/").strip().lower()
    for seg in COMPILED_BUNDLE_SEGMENTS:
        if seg in norm or norm.startswith(seg.lstrip("/")):
            return True
    for suffix in COMPILED_BUNDLE_SUFFIXES:
        if norm.endswith(suffix):
            return True
    return False


def classify_symbol_node_type(kind: Optional[str]) -> str:
    """Maps Tree-sitter and multi-language AST symbol kinds onto topology node categories."""
    kind_lower = (kind or "").strip().lower()
    if kind_lower in CLASS_LIKE_AST_KINDS:
        return "class"
    return "function"


def cap_topology_edges(
    edges: List[Dict[str, Any]],
    max_edges: int = MAX_TOPOLOGY_EDGES,
) -> List[Dict[str, Any]]:
    """Caps total edges while preserving highest-signal cross-service and dependency edges first."""
    if len(edges) <= max_edges:
        return edges
    ordered = sorted(edges, key=lambda e: EDGE_PRIORITY.get(e.get("type", "DEFINES"), 9))
    return ordered[:max_edges]


def resolve_doc_link_target(
    rel_repo: str,
    clean_src_fp: str,
    tgt_sym: str,
    file_id_by_path: Dict[Tuple[str, str], str],
) -> Optional[str]:
    """Resolves Markdown/Wikilink DOC_LINKS_TO target symbol/path to an indexed file node ID."""
    if not tgt_sym:
        return None

    if (rel_repo, tgt_sym) in file_id_by_path:
        return file_id_by_path.get((rel_repo, tgt_sym))

    src_dir = os.path.dirname(clean_src_fp)
    norm_tgt = os.path.normpath(os.path.join(src_dir, tgt_sym)).replace("\\", "/")
    if (rel_repo, norm_tgt) in file_id_by_path:
        return file_id_by_path.get((rel_repo, norm_tgt))

    for ext in (".md", ".txt", ".markdown"):
        cand = tgt_sym + ext
        if (rel_repo, cand) in file_id_by_path:
            return file_id_by_path.get((rel_repo, cand))
        norm_cand = os.path.normpath(os.path.join(src_dir, cand)).replace("\\", "/")
        if (rel_repo, norm_cand) in file_id_by_path:
            return file_id_by_path.get((rel_repo, norm_cand))

    tgt_base = os.path.splitext(os.path.basename(tgt_sym))[0].lower()
    tgt_clean = tgt_sym.lower().replace("-", " ").replace("_", " ")
    for (f_repo, f_path), f_id in file_id_by_path.items():
        if f_repo == rel_repo:
            f_base = os.path.splitext(os.path.basename(f_path))[0].lower()
            f_clean = f_base.replace("-", " ").replace("_", " ")
            if f_base == tgt_base or f_clean == tgt_clean or f_path.lower().endswith(tgt_sym.lower()):
                return f_id

    for (_f_repo, f_path), f_id in file_id_by_path.items():
        f_base = os.path.splitext(os.path.basename(f_path))[0].lower()
        if f_base == tgt_base:
            return f_id

    return None
