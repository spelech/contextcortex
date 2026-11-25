"""Plain-language bug report expansion into 3-6 code-concept queries via CHAT_MODEL or corpus heuristic (#219, #222, #223)."""

import hashlib
import json
import logging
import os
import re
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from openai import OpenAI

from app.services.database import get_db_connection
from app.services.database.connection import get_chat_model, get_embedding_db_config
from app.services.diagnostic_error_terms import _STOP_WORDS, identifier_parts, is_data_value_token
from app.services.expanded_search import (
    ExpandedSearchOutcome,
    RRF_K,
    area_key_for_path,
    extract_evidence_line,
    run_expanded_code_search,
    should_auto_expand_search_query,
)
from app.services.llm_client import create_chat_completion, get_llm_call_stats, get_llm_extra_headers

logger = logging.getLogger("contextcortex.query_expansion")

DEFAULT_MAX_QUERIES = 6
MIN_EXPANSION_QUERIES = 3
MAX_EXPANSION_QUERIES = 6
_EXPANSION_CACHE_MAX = 256
_MAX_CORPUS_TOKENS = 24

_URL_RE = re.compile(r"https?://\S+")
_WORD_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")

_CLAUSE_SPLIT_MARKERS = (
    ";", ":", ", but ", ", however ", ", whereas ", ", except ", ", unless ", ", while ", ", when ",
    " but ", " however ", " whereas ", " unless ", " except ", " instead of ", " only when ", " when ",
)

_EXPANSION_STOP_WORDS = _STOP_WORDS | frozenset({
    "all", "and", "any", "are", "bug", "but", "can", "checked", "did", "didn", "does", "doesn",
    "don", "else", "enabled", "disabled", "for", "get", "has", "hasn", "had", "how", "its", "label",
    "labels", "not", "now", "off", "one", "our", "out", "over", "per", "see", "set", "she", "that",
    "the", "their", "them", "then", "there", "these", "they", "this", "those", "ticket", "toggle",
    "two", "ui", "url", "user", "via", "was", "wasn", "way", "were", "what", "who", "why", "won",
    "yes", "yet", "you", "your",
})

_SYSTEM_PROMPT = (
    "Rewrite this plain-language bug report as 3 to 6 short search queries in source-code concepts. "
    "The report's nouns are user/support terms (not class names): replace product names, part numbers, "
    "SKUs, filter values, and UI labels, and include 1-2 generic code synonyms for key user nouns and "
    "behaviors (for example: 'linked item' -> 'related', 'association'; 'missing' -> 'exclude', 'remove', 'filter'). "
    "Do NOT invent camelCase or PascalCase identifiers. "
    "Return ONLY a JSON array of 3 to 6 short plain-word strings (each 3 to 10 words)."
)

_ROUND2_SYSTEM_PROMPT = (
    "Rewrite this plain-language bug report as 2 to 4 short search queries grounded in the codebase's own "
    "vocabulary listed below (words extracted from indexed symbols returned in round 1). "
    "Prefer those exact vocabulary words and natural phrases; do NOT invent camelCase identifiers. "
    "Return ONLY a JSON array of 2 to 4 short plain-word strings (each 3 to 10 words)."
)

_EXPANSION_CACHE: "OrderedDict[Tuple[str, str, str, int], Tuple[List[str], str]]" = OrderedDict()
_LOGGED_LLM_FAILURES: Set[str] = set()
_CACHE_LOCK = threading.Lock()
_TEST_PATH_PATTERNS = (
    "%/test/%", "%/tests/%", "%/testdata/%", "%/test_data/%", "%/fixtures/%", "%tests.cs", "%test.py", "%.test.%",
)


def clear_expansion_cache() -> None:
    """Clears the in-memory report-to-query expansion cache and per-model warning state (used in tests)."""
    with _CACHE_LOCK:
        _EXPANSION_CACHE.clear()
        _LOGGED_LLM_FAILURES.clear()


def _cache_get(key: Tuple[str, str, str, int]) -> Optional[Tuple[List[str], str]]:
    with _CACHE_LOCK:
        val = _EXPANSION_CACHE.get(key)
        if val is not None:
            _EXPANSION_CACHE.move_to_end(key)
            return list(val[0]), val[1]
    return None


def _cache_set(key: Tuple[str, str, str, int], queries: List[str], source: str) -> None:
    with _CACHE_LOCK:
        _EXPANSION_CACHE[key] = (list(queries), source)
        _EXPANSION_CACHE.move_to_end(key)
        while len(_EXPANSION_CACHE) > _EXPANSION_CACHE_MAX:
            _EXPANSION_CACHE.popitem(last=False)


def _log_llm_failure(chat_model: str, stage: str, exc: Exception) -> None:
    key = (chat_model or "").strip().lower()
    with _CACHE_LOCK:
        first_time = key not in _LOGGED_LLM_FAILURES
        if first_time:
            _LOGGED_LLM_FAILURES.add(key)
    stats = get_llm_call_stats().get(chat_model) or {}
    ratio = f" ({stats.get('failures', 1)}/{stats.get('calls', 1)} failures/calls)" if stats else ""
    msg = f"LLM {stage} expansion failed for '{chat_model}'{ratio}: {exc}"
    if first_time:
        logger.warning(msg)
    else:
        logger.info(msg)


def _stem_token(token: str) -> str:
    """Lightweight O(1) English inflection stemmer for corpus symbol matching."""
    t = token.lower()
    if len(t) > 5 and t.endswith("ies"):
        return t[:-3]
    if len(t) > 4 and t.endswith("y") and t[-2] not in "aeiou":
        return t[:-1]
    if len(t) > 5 and t.endswith("ing"):
        return t[:-3]
    if len(t) > 4 and t.endswith("ed"):
        return t[:-2]
    if len(t) > 4 and t.endswith("es") and not t.endswith(("ses", "zes")):
        return t[:-1]
    return t[:-1] if (len(t) > 3 and t.endswith("s") and not t.endswith("ss")) else t


def _strip_list_marker(line: str) -> str:
    """Removes leading bullet or numeric list prefix without backtracking regex."""
    s = line.strip()
    if not s:
        return ""
    if s[0] in ("-", "*", "•"):
        return s[1:].strip()
    i = 0
    while i < len(s) and s[i].isdigit():
        i += 1
    return s[i + 1 :].strip() if (0 < i < len(s) and s[i] in (".", ")", ":")) else s


def _parse_llm_query_list(raw_text: str, max_queries: int) -> List[str]:
    """Parses a JSON string array (or bulleted/numbered list fallback) returned by the chat model."""
    text = (raw_text or "").strip()
    if not text:
        return []
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:] if (lines and lines[0].startswith("```")) else lines
        lines = lines[:-1] if (lines and lines[-1].strip().startswith("```")) else lines
        text = "\n".join(lines).strip()

    parsed: Optional[List[Any]] = None
    bracket_slice = text[text.find("[") : text.rfind("]") + 1] if "[" in text and "]" in text else ""
    for candidate in (text, bracket_slice):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
            if isinstance(obj, list):
                parsed = obj
                break
            if isinstance(obj, dict) and isinstance(obj.get("queries"), list):
                parsed = obj["queries"]
                break
        except Exception:
            continue

    raw_items = [str(item) for item in parsed] if parsed is not None else [_strip_list_marker(ln) for ln in text.splitlines()]
    cleaned, seen = [], set()
    for item in raw_items:
        q = " ".join(item.strip().strip("\"'").split())[:120]
        if len(q) >= 3 and q.lower() not in seen:
            seen.add(q.lower())
            cleaned.append(q)
            if len(cleaned) >= max_queries:
                break
    return cleaned


def _build_llm_client() -> Any:
    db_cfg: Dict[str, Any] = {}
    try:
        db_cfg = get_embedding_db_config()
    except Exception:
        pass
    base_url = (
        (db_cfg.get("openai_api_url") if db_cfg else None)
        or (db_cfg.get("litellm_url") if db_cfg else None)
        or os.getenv("OPENAI_API_URL")
        or os.getenv("OPENAI_BASE_URL")
        or os.getenv("LITELLM_URL")
        or "http://litellm:4000/v1"
    ).strip()
    api_key = (
        (db_cfg.get("litellm_api_key") if db_cfg else None)
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("LITELLM_API_KEY")
        or "dummy"
    ).strip()
    try:
        timeout_s = float(os.getenv("LLM_EXPANSION_TIMEOUT_SECONDS", "25"))
    except ValueError:
        timeout_s = 25.0
    return OpenAI(base_url=base_url, api_key=api_key, default_headers=get_llm_extra_headers(), timeout=max(5.0, timeout_s))


def _expand_with_llm(report_text: str, chat_model: str, max_queries: int) -> Optional[List[str]]:
    if not chat_model:
        return None
    try:
        client = _build_llm_client()
        response = create_chat_completion(
            client,
            model=chat_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": report_text[:3000]},
            ],
        )
        content = (response.choices[0].message.content or "").strip() if response.choices else ""
        queries = _parse_llm_query_list(content, max_queries=max_queries)
        return queries if queries else None
    except Exception as exc:
        _log_llm_failure(chat_model, "round-1", exc)
        return None


def expand_round2_with_llm(
    report_text: str,
    symbol_words: Sequence[str],
    max_queries: int = 4,
) -> Optional[List[str]]:
    """Uses CHAT_MODEL to rewrite a report into 2-4 queries grounded in round-1 codebase symbol words (#223)."""
    chat_model = get_chat_model()
    words = [w for w in symbol_words if w][:40]
    if not chat_model or len(words) < 2:
        return None
    norm_text = " ".join((report_text or "").split())[:3000]
    digest = hashlib.sha256(f"{norm_text}\n{' '.join(words)}".encode("utf-8")).hexdigest()
    cache_key = (digest, "", f"llm-r2:{chat_model}", max_queries)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached[0]
    try:
        client = _build_llm_client()
        user_msg = f"Codebase symbol words: {', '.join(words)}\n\nBug report:\n{norm_text}"
        response = create_chat_completion(
            client,
            model=chat_model,
            messages=[
                {"role": "system", "content": _ROUND2_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
        )
        content = (response.choices[0].message.content or "").strip() if response.choices else ""
        queries = _parse_llm_query_list(content, max_queries=max_queries)
        if queries:
            _cache_set(cache_key, queries, "llm")
            return queries
        return None
    except Exception as exc:
        _log_llm_failure(chat_model, "round-2", exc)
        return None


def _split_report_clauses(report_text: str) -> List[str]:
    """Splits a plain-language report into sentence and contrast/condition clauses."""
    cleaned = _URL_RE.sub(" ", report_text or "")
    for ch in ("#", "*", "`", ">"):
        cleaned = cleaned.replace(ch, " ")

    sentences: List[str] = []
    for raw_line in cleaned.splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        start = 0
        for idx, ch in enumerate(line):
            if ch in ".!?" and (idx + 1 == len(line) or line[idx + 1].isspace()):
                seg = line[start:idx].strip()
                if seg:
                    sentences.append(seg)
                start = idx + 1
        tail = line[start:].strip()
        if tail:
            sentences.append(tail)

    clauses: List[str] = []
    for sent in sentences:
        parts = [sent]
        for marker in _CLAUSE_SPLIT_MARKERS:
            next_parts: List[str] = []
            for p in parts:
                low = p.lower()
                pos = 0
                while True:
                    hit = low.find(marker, pos)
                    if hit < 0:
                        seg = p[pos:].strip(" ,;:-")
                        if seg:
                            next_parts.append(seg)
                        break
                    seg = p[pos:hit].strip(" ,;:-")
                    if seg:
                        next_parts.append(seg)
                    pos = hit + len(marker)
            parts = next_parts
        clauses.extend(parts)
    return clauses


def _extract_clause_tokens(clause: str) -> List[str]:
    """Extracts lowercase domain candidate tokens from a clause, dropping stop words and data values."""
    out: List[str] = []
    seen = set()
    for raw in _WORD_TOKEN_RE.findall(clause or ""):
        if is_data_value_token(raw):
            continue
        pieces = identifier_parts(raw) if ("_" in raw or "-" in raw or any(c.isupper() for c in raw[1:])) else [raw.lower()]
        for tok in pieces:
            low = tok.lower().strip()
            if len(low) < 3 or low in _EXPANSION_STOP_WORDS or is_data_value_token(low):
                continue
            if low not in seen:
                seen.add(low)
                out.append(low)
    return out


def _score_tokens_against_corpus(tokens: Sequence[str], repo: Optional[str]) -> Tuple[int, Dict[str, Tuple[int, int]]]:
    """Returns (total_ast_symbols, {token: (code_df, noise_df)}) from ast_symbols & indexed_files."""
    unique = list(OrderedDict.fromkeys(tokens))[:_MAX_CORPUS_TOKENS]
    if not unique:
        return 0, {}
    stems = [_stem_token(t) for t in unique]
    test_expr = " OR ".join("LOWER(REPLACE(filepath, '\\', '/')) LIKE ?" for _ in _TEST_PATH_PATTERNS)

    try:
        with get_db_connection() as conn:
            where_repo = " WHERE repo = ?" if repo else ""
            repo_params = [repo] if repo else []
            total_syms = int(conn.execute(f"SELECT COUNT(*) FROM ast_symbols{where_repo}", repo_params).fetchone()[0] or 0)
            if total_syms == 0:
                return 0, {}

            sym_cols: List[str] = []
            sym_params: List[Any] = []
            for idx, stem in enumerate(stems):
                pat = f"%{stem}%"
                sym_cols.append(
                    f"SUM(CASE WHEN (LOWER(name) LIKE ? OR LOWER(full_symbol) LIKE ?) AND NOT ({test_expr}) THEN 1 ELSE 0 END) AS p_{idx}"
                )
                sym_params.extend([pat, pat, *_TEST_PATH_PATTERNS])
                sym_cols.append(
                    f"SUM(CASE WHEN (LOWER(name) LIKE ? OR LOWER(full_symbol) LIKE ?) AND ({test_expr}) THEN 1 ELSE 0 END) AS t_{idx}"
                )
                sym_params.extend([pat, pat, *_TEST_PATH_PATTERNS])
            sym_params.extend(repo_params)
            sym_row = conn.execute(f"SELECT {', '.join(sym_cols)} FROM ast_symbols{where_repo}", sym_params).fetchone()

            file_cols: List[str] = []
            file_params: List[Any] = []
            for idx, stem in enumerate(stems):
                pat = f"%{stem}%"
                file_cols.append(
                    f"SUM(CASE WHEN LOWER(filepath) LIKE ? AND doc_type = 'code' AND NOT ({test_expr}) THEN 1 ELSE 0 END) AS fc_{idx}"
                )
                file_params.extend([pat, *_TEST_PATH_PATTERNS])
                file_cols.append(
                    f"SUM(CASE WHEN LOWER(filepath) LIKE ? AND (doc_type != 'code' OR ({test_expr})) THEN 1 ELSE 0 END) AS fd_{idx}"
                )
                file_params.extend([pat, *_TEST_PATH_PATTERNS])
            file_params.extend(repo_params)
            file_row = conn.execute(f"SELECT {', '.join(file_cols)} FROM indexed_files{where_repo}", file_params).fetchone()
    except Exception as exc:
        logger.debug(f"Corpus token frequency lookup skipped: {exc}")
        return 0, {}

    stats: Dict[str, Tuple[int, int]] = {}
    for idx, tok in enumerate(unique):
        prod_sym = int((sym_row[idx * 2] if sym_row else 0) or 0)
        test_sym = int((sym_row[idx * 2 + 1] if sym_row else 0) or 0)
        code_file = int((file_row[idx * 2] if file_row else 0) or 0)
        doc_file = int((file_row[idx * 2 + 1] if file_row else 0) or 0)
        stats[tok] = (prod_sym + code_file, test_sym + doc_file)
    return total_syms, stats


def _expand_with_heuristic(report_text: str, repo: Optional[str], max_queries: int) -> List[str]:
    """Splits a plain-language report by sentence/clause and keeps corpus-backed code concepts."""
    clauses = _split_report_clauses(report_text)
    clause_tokens = [_extract_clause_tokens(c) for c in clauses]
    all_tokens = list(OrderedDict.fromkeys(tok for toks in clause_tokens for tok in toks))
    if not all_tokens:
        fallback = " ".join((report_text or "").split())[:120]
        return [fallback] if fallback else []

    total_syms, df_stats = _score_tokens_against_corpus(all_tokens, repo=repo)
    kept_set = set(all_tokens)
    if total_syms > 0 and df_stats:
        pruned = {
            tok for tok in all_tokens
            if (code_df := df_stats.get(tok, (0, 0))[0]) > 0
            and not (code_df <= 1 and df_stats.get(tok, (0, 0))[1] >= 3)
        }
        if len(pruned) >= 2:
            kept_set = pruned

    def _token_priority(tok: str) -> Tuple[int, int]:
        code_df, noise_df = df_stats.get(tok, (0, 0))
        return (1 if code_df > 0 else 0, code_df - noise_df)

    ranked_tokens = sorted([t for t in all_tokens if t in kept_set], key=_token_priority, reverse=True)
    queries: List[str] = []
    seen_sets: List[frozenset] = []

    def _add_query(tokens: Sequence[str]) -> None:
        clean = list(OrderedDict.fromkeys(tokens))[:8]
        if not clean or len(queries) >= max_queries:
            return
        sig = frozenset(clean)
        if sig in seen_sets:
            return
        seen_sets.append(sig)
        queries.append(" ".join(clean))

    for toks in clause_tokens:
        surviving = [t for t in toks if t in kept_set]
        if len(surviving) >= 2:
            _add_query(surviving)

    if len(ranked_tokens) >= 2:
        _add_query(ranked_tokens[:6])

    if len(queries) < min(MIN_EXPANSION_QUERIES, max_queries) and len(ranked_tokens) >= 4:
        mid = len(ranked_tokens) // 2
        _add_query(ranked_tokens[: max(3, mid)])
        _add_query(ranked_tokens[mid:])
        if len(queries) < min(MIN_EXPANSION_QUERIES, max_queries):
            _add_query([ranked_tokens[0], ranked_tokens[-1], *ranked_tokens[1:3]])

    if not queries:
        _add_query(ranked_tokens or all_tokens)
    return queries[:max_queries]


def expand_report_to_code_queries(
    report_text: str,
    repo: Optional[str] = None,
    max_queries: int = DEFAULT_MAX_QUERIES,
    use_llm: bool = True,
) -> Tuple[List[str], str]:
    """Splits a plain-language report into 3-6 code-concept queries (cached by report hash)."""
    norm_text = " ".join((report_text or "").split())
    if not norm_text:
        return [], "heuristic"
    clamped_max = max(1, min(MAX_EXPANSION_QUERIES, int(max_queries or DEFAULT_MAX_QUERIES)))
    chat_model = get_chat_model() if use_llm else ""
    mode_tag = f"llm:{chat_model}" if chat_model else "heuristic"
    cache_key = (hashlib.sha256(norm_text.encode("utf-8")).hexdigest(), repo or "", mode_tag, clamped_max)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    if chat_model:
        llm_queries = _expand_with_llm(norm_text, chat_model=chat_model, max_queries=clamped_max)
        if llm_queries:
            _cache_set(cache_key, llm_queries, "llm")
            return llm_queries, "llm"
        # Do not cache transient LLM fallbacks under the LLM key (#228).
        return _expand_with_heuristic(norm_text, repo=repo, max_queries=clamped_max), "heuristic"

    heur_queries = _expand_with_heuristic(norm_text, repo=repo, max_queries=clamped_max)
    _cache_set(cache_key, heur_queries, "heuristic")
    return heur_queries, "heuristic"


__all__ = [
    "DEFAULT_MAX_QUERIES",
    "ExpandedSearchOutcome",
    "RRF_K",
    "_stem_token",
    "area_key_for_path",
    "clear_expansion_cache",
    "expand_report_to_code_queries",
    "expand_round2_with_llm",
    "extract_evidence_line",
    "run_expanded_code_search",
    "should_auto_expand_search_query",
]
