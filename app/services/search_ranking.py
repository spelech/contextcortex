"""Hybrid search score fusion, candidate pool sizing, and low-signal asset demotion."""

import os
import re
from typing import Any, Dict, Optional

DEFAULT_HYBRID_CANDIDATE_MULTIPLIER = 5
DEFAULT_HYBRID_MIN_CANDIDATES = 25
MAX_HYBRID_CANDIDATES = 250

LEXICAL_ONLY_DAMPING = 0.45
LEXICAL_ONLY_RANK_DECAY = 0.15
PLAIN_LANGUAGE_DIAGNOSTIC_DENSE_WEIGHT = 0.80

_FIXTURE_DIRS = frozenset({
    "fixtures",
    "__fixtures__",
    "fixture",
    "testdata",
    "test_data",
    "test-data",
    "snapshots",
    "__snapshots__",
    "mockdata",
    "mock_data",
    "mock-data",
    "seed_data",
    "sample_data",
})

_MINIFIED_SUFFIXES = (
    ".min.js",
    ".min.css",
    ".min.mjs",
    ".min.cjs",
    ".bundle.js",
    ".bundle.css",
    ".chunk.js",
    ".js.map",
    ".css.map",
)

_STYLESHEET_EXTS = frozenset({".css", ".scss", ".sass", ".less", ".styl"})
_MARKUP_EXTS = frozenset({".html", ".htm", ".xhtml", ".svg", ".xml", ".xsl", ".xslt"})
_DATA_EXTS = frozenset({".json", ".csv", ".tsv", ".jsonl", ".ndjson", ".lock"})

_ASSET_QUERY_TERMS = {
    "minified": ("minified", ".min.", "bundle", "sourcemap", "source map"),
    "fixture": ("fixture", "fixtures", "snapshot", "snapshots", "testdata", "cypress", "mockdata", "mock data"),
    "stylesheet": ("css", "scss", "sass", "less", "stylesheet", "styles", "styling", "selector", "tailwind", ".css", ".scss", ".less"),
    "markup": ("html", "htm", "svg", "xml", "xhtml", "markup", "dom", ".html", ".svg", ".xml"),
    "data": ("json", "csv", "tsv", "jsonl", "lockfile", ".json", ".csv", "package-lock", "yarn.lock"),
    "summary": ("summary", "summaries", "overview", "file summary"),
}

_LANGUAGE_ASSET_MAP = {
    "css": "stylesheet",
    "scss": "stylesheet",
    "sass": "stylesheet",
    "less": "stylesheet",
    "html": "markup",
    "xml": "markup",
    "svg": "markup",
    "json": "data",
}

_WORD_RE = re.compile(r"[a-z0-9_.+-]+")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_OR_REGION_RE = re.compile(r"(?m)(?://[^\n]*|#\s*(?:end)?region[^\n]*|#[^\n]*)")
_IDENT_CHAR_RE = re.compile(r"[A-Za-z0-9_]")
_LOW_VALUE_CHUNK_KINDS = frozenset({"file_header", "file_context"})


def is_substantive_code_fragment(text: Optional[str], min_ident_chars: int = 4) -> bool:
    """False for tiny closing fragments (`#endregion }`, bare braces, or comment-only tails) with no real code."""
    if not text or not text.strip():
        return False
    if text.strip() == "...":
        return True
    stripped = _BLOCK_COMMENT_RE.sub(" ", text)
    stripped = _LINE_COMMENT_OR_REGION_RE.sub(" ", stripped)
    return len(_IDENT_CHAR_RE.findall(stripped)) >= min_ident_chars


def is_low_value_chunk_kind(payload: Optional[Dict[str, Any]]) -> bool:
    return isinstance(payload, dict) and payload.get("kind") in _LOW_VALUE_CHUNK_KINDS


def demote_trivial_code_results(results: list) -> list:
    """Demotes `#endregion }`-style fragments and header/gap chunks so real code ranks first even in semantic mode."""
    if not results:
        return results
    changed = False
    for r in results:
        p = getattr(r, "payload", None) or {}
        if not isinstance(p, dict):
            continue
        is_code = p.get("doc_type") == "code" or bool(p.get("language"))
        if not is_code:
            continue
        mult = 1.0
        if is_low_value_chunk_kind(p):
            mult = min(mult, 0.15)
        content = p.get("content")
        if isinstance(content, str) and content.strip() and not is_substantive_code_fragment(content):
            mult = min(mult, 0.05)
        if mult < 1.0:
            r.score = round(float(r.score or 0.0) * mult, 4)
            changed = True
    if changed:
        results.sort(key=lambda item: float(item.score or 0.0), reverse=True)
    return results


def hybrid_candidate_limit(
    limit: int,
    min_pool: int = DEFAULT_HYBRID_MIN_CANDIDATES,
    max_pool: int = MAX_HYBRID_CANDIDATES,
) -> int:
    """Returns an expanded per-track candidate pool size (default 5x limit, at least 25) before fusion."""
    safe_limit = max(1, int(limit or 5))
    return min(max_pool, max(safe_limit * DEFAULT_HYBRID_CANDIDATE_MULTIPLIER, min_pool))


def _normalize_path(path: str) -> str:
    cleaned = (path or "").replace("\\", "/").strip()
    if "://" in cleaned:
        cleaned = cleaned.split("://", 1)[1]
    return cleaned.lstrip("/").lower()


def is_fixture_path(path: str) -> bool:
    """Returns True for test fixture, snapshot, or mock-data file paths."""
    norm = _normalize_path(path)
    if not norm:
        return False
    parts = [p for p in norm.split("/") if p]
    if any(seg in _FIXTURE_DIRS for seg in parts[:-1]):
        return True
    name = parts[-1] if parts else ""
    if name.endswith((".snap", ".fixture")) or ".fixture." in name or "_fixture." in name:
        return True
    return False


def is_minified_path(path: str) -> bool:
    """Returns True for minified/bundled assets and source maps."""
    norm = _normalize_path(path)
    if not norm:
        return False
    name = os.path.basename(norm)
    return name.endswith(_MINIFIED_SUFFIXES)


def is_summary_payload(payload: Optional[Dict[str, Any]]) -> bool:
    """Returns True when a search hit represents a generated file summary rather than a concrete chunk."""
    if not isinstance(payload, dict):
        return False
    return payload.get("doc_type") == "summary" or bool(payload.get("is_summary"))


def asset_kind_for_path(path: str) -> Optional[str]:
    """Classifies low-signal non-logic asset extensions into 'stylesheet', 'markup', 'data', or None."""
    norm = _normalize_path(path)
    if not norm:
        return None
    _, ext = os.path.splitext(norm)
    if ext in _STYLESHEET_EXTS:
        return "stylesheet"
    if ext in _MARKUP_EXTS:
        return "markup"
    if ext in _DATA_EXTS:
        return "data"
    return None


def query_explicitly_targets_asset(query_text: str, kind: str, language: Optional[str] = None) -> bool:
    """Returns True if the query text or explicit language filter asks for the given asset category."""
    if language and _LANGUAGE_ASSET_MAP.get(language.strip().lower()) == kind:
        return True
    q_low = (query_text or "").lower()
    if not q_low:
        return False
    terms = _ASSET_QUERY_TERMS.get(kind, ())
    tokens = set(_WORD_RE.findall(q_low))
    for term in terms:
        if "." in term or " " in term:
            if term in q_low:
                return True
        elif term in tokens:
            return True
    return False


def low_signal_multiplier(
    payload: Optional[Dict[str, Any]],
    query_text: str = "",
    doc_type: Optional[str] = None,
    language: Optional[str] = None,
    for_diagnostics: bool = False,
) -> float:
    """Returns a score multiplier in (0, 1] demoting fixtures, minified files, CSS/HTML/data assets, and summaries."""
    if not isinstance(payload, dict):
        return 1.0

    path = str(payload.get("rel_path") or payload.get("path") or "")
    mult = 1.0

    if is_minified_path(path) and not query_explicitly_targets_asset(query_text, "minified", language):
        mult = min(mult, 0.15)

    if is_fixture_path(path) and not query_explicitly_targets_asset(query_text, "fixture", language):
        mult = min(mult, 0.25)

    kind = asset_kind_for_path(path)
    if kind and not query_explicitly_targets_asset(query_text, kind, language):
        if doc_type == "code" or for_diagnostics:
            kind_mult = {"stylesheet": 0.25, "markup": 0.35, "data": 0.30}[kind]
        else:
            kind_mult = {"stylesheet": 0.30, "markup": 0.45, "data": 0.45}[kind]
        mult = min(mult, kind_mult)

    if is_summary_payload(payload) and not query_explicitly_targets_asset(query_text, "summary", language):
        mult = min(mult, 0.20 if mult < 1.0 else 0.65)

    if is_low_value_chunk_kind(payload):
        mult = min(mult, 0.15)

    is_code = doc_type == "code" or payload.get("doc_type") == "code"
    content = payload.get("content")
    if is_code and isinstance(content, str) and content.strip() and not is_substantive_code_fragment(content):
        mult = min(mult, 0.05)

    return mult


def is_low_signal_diagnostic_hit(payload: Optional[Dict[str, Any]], query_text: str = "") -> bool:
    """Returns True when a hit should be excluded from diagnose_issue semantic candidates."""
    if not isinstance(payload, dict):
        return False
    if is_summary_payload(payload) or is_low_value_chunk_kind(payload):
        return True
    content = payload.get("content")
    if isinstance(content, str) and content.strip() and not is_substantive_code_fragment(content):
        return True
    path = str(payload.get("rel_path") or payload.get("path") or "")
    if not path:
        return False
    if is_minified_path(path) and not query_explicitly_targets_asset(query_text, "minified"):
        return True
    if is_fixture_path(path) and not query_explicitly_targets_asset(query_text, "fixture"):
        return True
    kind = asset_kind_for_path(path)
    if kind and not query_explicitly_targets_asset(query_text, kind):
        return True
    return False


def compute_hybrid_score(
    alpha: float,
    dense_score: float,
    sparse_score: float,
    *,
    has_dense: bool,
    has_sparse: bool,
    sparse_rank: Optional[int] = None,
    payload: Optional[Dict[str, Any]] = None,
    query_text: str = "",
    doc_type: Optional[str] = None,
    language: Optional[str] = None,
) -> float:
    """Fuses dense and sparse scores while dampening lexical-only hits and low-signal assets."""
    a = max(0.0, min(1.0, float(alpha)))
    d = max(0.0, min(1.0, float(dense_score or 0.0)))
    s = max(0.0, min(1.0, float(sparse_score or 0.0)))

    if a >= 1.0:
        return d
    if a <= 0.0:
        return s

    if has_dense and has_sparse:
        base = (a * d) + ((1.0 - a) * s)
    elif has_dense:
        base = a * d
    elif has_sparse:
        rank_decay = 1.0 / (1.0 + LEXICAL_ONLY_RANK_DECAY * max(0, (sparse_rank or 1) - 1))
        base = (1.0 - a) * s * LEXICAL_ONLY_DAMPING * rank_decay
    else:
        base = 0.0

    if payload:
        base *= low_signal_multiplier(payload, query_text=query_text, doc_type=doc_type, language=language)

    return max(0.0, min(1.0, base))
