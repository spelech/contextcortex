import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.services.vector_store.base import VectorSearchResult

_INTERROGATIVES = frozenset({
    "how", "what", "why", "where", "when", "which", "who", "whom", "whose",
})

_PROSE_AUX_VERBS = frozenset({
    "is", "are", "was", "were", "be", "been", "being", "am",
    "do", "does", "did", "can", "could", "should", "would",
    "will", "shall", "might", "must", "have", "has", "had",
    "explain", "describe", "summarize", "understand",
})

_PROSE_STOPWORDS = frozenset({
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "from", "with", "by",
    "about", "into", "onto", "upon", "through", "across", "between", "among",
    "before", "after", "during", "without", "against", "under", "over",
    "and", "or", "but", "if", "then", "else", "than", "that", "this", "these",
    "those", "it", "its", "we", "our", "us", "you", "your", "they", "their",
    "i", "my", "me", "not", "no", "nor", "only", "just", "also", "very", "too",
    "more", "most", "some", "any", "all", "each", "every", "both", "same",
    "such", "already", "there", "here", "because", "since", "while", "although",
    "though", "unless", "until", "as",
})

_CODE_DELIM_RE = re.compile(r"(::|->|=>|\(\)|\[\]|/|\\|@|[A-Za-z0-9_]\.[A-Za-z0-9_])")
_CAMEL_BOUNDARY_RE = re.compile(r"[a-z][A-Z]|[A-Z]{2,}[a-z]")
_ERROR_CODE_RE = re.compile(r"^[A-Z]{1,6}[-_]?\d{2,6}$")
_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_QUOTED_RE = re.compile(r'^["\'](.+)["\']$')


@dataclass(frozen=True)
class QueryPlan:
    raw_query: str
    intent: str  # "lexical_exact" | "lexical_keywords" | "semantic_prose"
    raw_terms: List[str]
    content_tokens: List[str]
    exact_phrase: Optional[str]
    stopword_ratio: float
    has_code_syntax: bool


def split_identifier_tokens(text: str, min_len: int = 2) -> List[str]:
    """Splits prose and CamelCase/snake_case/dotted identifiers into lowercase word tokens, preserving whole identifiers."""
    if not text:
        return []
    raw_pieces = re.findall(r"[A-Za-z0-9]+", text)
    tokens: List[str] = []
    seen = set()
    for piece in raw_pieces:
        sub_parts = _CAMEL_SPLIT_RE.split(piece)
        if len(sub_parts) > 1:
            ordered = [piece.lower()] + [sp.lower() for sp in sub_parts if sp]
        else:
            ordered = [piece.lower()]
        for tok in ordered:
            if len(tok) >= min_len and tok not in seen:
                seen.add(tok)
                tokens.append(tok)
    return tokens


def _has_term_code_syntax(term: str) -> bool:
    if _CODE_DELIM_RE.search(term):
        return True
    if _CAMEL_BOUNDARY_RE.search(term):
        return True
    if "_" in term and len([p for p in term.split("_") if p]) >= 2:
        return True
    if _ERROR_CODE_RE.match(term):
        return True
    return False


def classify_query_intent(query_text: str) -> QueryPlan:
    """Classifies queries using word tokens and identifier morphology into lexical_exact, lexical_keywords, or semantic_prose."""
    cleaned = (query_text or "").strip()
    if not cleaned:
        return QueryPlan(cleaned, "semantic_prose", [], [], None, 0.0, False)

    quoted_match = _QUOTED_RE.match(cleaned)
    exact_phrase = quoted_match.group(1).strip() if quoted_match else None
    working = exact_phrase or cleaned

    raw_terms = working.split()
    lower_words = [re.sub(r"^[^\w]+|[^\w]+$", "", t.lower()) for t in raw_terms]
    lower_words = [w for w in lower_words if w]

    all_tokens = split_identifier_tokens(working, min_len=2)
    filtered_tokens = [t for t in all_tokens if t not in _PROSE_STOPWORDS and t not in _INTERROGATIVES]
    content_tokens = filtered_tokens if filtered_tokens else all_tokens

    has_code_syntax = any(_has_term_code_syntax(t) for t in raw_terms)
    stopword_hits = sum(1 for w in lower_words if w in _PROSE_STOPWORDS)
    stopword_ratio = stopword_hits / max(1, len(lower_words))

    has_interrogative = any(w in _INTERROGATIVES for w in lower_words)
    has_aux_verb = any(w in _PROSE_AUX_VERBS for w in lower_words)
    ends_qmark = cleaned.endswith("?")

    if exact_phrase:
        intent = "lexical_exact"
    elif len(raw_terms) == 1:
        single_w = lower_words[0] if lower_words else cleaned.lower()
        if single_w in _INTERROGATIVES or single_w in _PROSE_AUX_VERBS or single_w in _PROSE_STOPWORDS:
            intent = "semantic_prose"
        else:
            intent = "lexical_exact"
    elif has_code_syntax and len(raw_terms) <= 3 and not (has_interrogative or has_aux_verb or ends_qmark):
        intent = "lexical_exact"
    elif ends_qmark or has_interrogative or has_aux_verb:
        intent = "semantic_prose"
    elif stopword_hits >= 2 and (stopword_ratio > 0.25 or len(lower_words) >= 7):
        intent = "semantic_prose"
    elif len(content_tokens) >= 1:
        intent = "lexical_keywords"
    else:
        intent = "semantic_prose"

    return QueryPlan(
        raw_query=cleaned,
        intent=intent,
        raw_terms=raw_terms,
        content_tokens=content_tokens,
        exact_phrase=exact_phrase,
        stopword_ratio=stopword_ratio,
        has_code_syntax=has_code_syntax,
    )


def compute_token_coverage(
    query_tokens: List[str],
    rel_path: Optional[str],
    symbol: Optional[str],
    heading: Optional[str],
    content: Optional[str],
    raw_query: Optional[str] = None,
) -> Tuple[float, Dict[str, Any]]:
    """Computes normalized word-token coverage across path/symbol/heading and chunk body."""
    if not query_tokens:
        return 0.0, {"coverage": 0.0, "header_hits": 0, "body_hits": 0, "matched_count": 0}

    header_tokens = set(split_identifier_tokens(f"{rel_path or ''} {symbol or ''} {heading or ''}", min_len=2))
    body_tokens = set(split_identifier_tokens(content or "", min_len=2))
    combined_tokens = header_tokens | body_tokens

    matched_all = [t for t in query_tokens if t in combined_tokens]
    matched_header = [t for t in query_tokens if t in header_tokens]
    matched_body = [t for t in query_tokens if t in body_tokens]

    n_tokens = len(query_tokens)
    coverage = len(matched_all) / n_tokens
    header_ratio = len(matched_header) / n_tokens
    body_ratio = len(matched_body) / n_tokens

    score = 0.55 * coverage + 0.25 * header_ratio + 0.20 * body_ratio
    if raw_query:
        q_low = raw_query.strip().lower()
        sym_low = (symbol or "").strip().lower()
        path_low = (rel_path or "").strip().lower()
        content_low = (content or "").lower()
        if sym_low and (sym_low == q_low or sym_low.endswith(f".{q_low}")):
            score = max(score, 0.98)
        elif q_low and len(q_low) >= 4 and ((sym_low and q_low in sym_low) or (path_low and q_low in path_low)):
            score = max(score, 0.92)
        elif q_low and len(q_low) >= 4 and q_low in content_low:
            score = min(1.0, score + 0.15)

    meta = {
        "coverage": round(coverage, 4),
        "header_hits": len(matched_header),
        "body_hits": len(matched_body),
        "matched_count": len(matched_all),
        "total_tokens": n_tokens,
    }
    return round(min(1.0, score), 4), meta


def should_early_return_lexical(plan: QueryPlan, track_a_results: List[VectorSearchResult]) -> bool:
    """Confidence gate deciding whether Track A can return immediately without waiting for Track B embeddings."""
    if not track_a_results:
        return False

    top = track_a_results[0]
    p = top.payload or {}
    meta = p.get("_lexical_meta")
    if not isinstance(meta, dict):
        _, meta = compute_token_coverage(
            plan.content_tokens,
            rel_path=p.get("rel_path") or p.get("path"),
            symbol=p.get("full_symbol") or p.get("symbol"),
            heading=p.get("heading"),
            content=p.get("content"),
            raw_query=plan.exact_phrase or plan.raw_query,
        )

    if plan.intent == "lexical_exact":
        return float(top.score or 0.0) >= 0.50 and meta.get("matched_count", 0) >= 1

    if plan.intent == "lexical_keywords":
        coverage = float(meta.get("coverage", 0.0))
        header_hits = int(meta.get("header_hits", 0))
        body_hits = int(meta.get("body_hits", 0))
        total_tokens = len(plan.content_tokens)

        if total_tokens <= 1:
            return coverage >= 1.0 and (header_hits >= 1 or body_hits >= 1)
        if total_tokens == 2:
            return coverage >= 1.0 and body_hits >= 1 and (header_hits >= 1 or body_hits >= 2)
        return (coverage >= 0.75 and body_hits >= 2) or (coverage >= 0.80 and header_hits >= 1 and body_hits >= 1)

    return False


def strip_internal_metadata(results: List[VectorSearchResult]) -> List[VectorSearchResult]:
    for r in results:
        if isinstance(r.payload, dict):
            r.payload.pop("_lexical_meta", None)
    return results


def _result_dedup_key(res: VectorSearchResult) -> Tuple[str, str, int]:
    p = res.payload or {}
    repo = str(p.get("repo") or "")
    raw_path = str(p.get("rel_path") or p.get("path") or "").replace("\\", "/")
    if "://" in raw_path:
        raw_path = raw_path.split("://", 1)[1]
    if repo and raw_path.startswith(f"{repo}/"):
        raw_path = raw_path[len(repo) + 1 :]
    s_line = int(p.get("start_line") or 0)
    bucket = s_line // 15 if s_line > 0 else 0
    return (repo, raw_path, bucket)


def fuse_search_results(
    track_a: List[VectorSearchResult],
    track_b: List[VectorSearchResult],
    limit: int,
    intent: str,
) -> List[VectorSearchResult]:
    """Combines Track A fast lexical hits and Track B semantic/hybrid hits with agreement boost."""
    if not track_a:
        return strip_internal_metadata(list(track_b[:limit]))
    if not track_b:
        return strip_internal_metadata(list(track_a[:limit]))

    a_weight = 0.90 if intent in ("lexical_exact", "lexical_keywords") else 0.78
    merged: Dict[Tuple[str, str, int], VectorSearchResult] = {}

    for item in track_b:
        key = _result_dedup_key(item)
        copy_item = VectorSearchResult(
            id=item.id,
            score=float(item.score or 0.0),
            dense_score=item.dense_score,
            sparse_score=item.sparse_score,
            dense_rank=item.dense_rank,
            sparse_rank=item.sparse_rank,
            payload=dict(item.payload or {}),
        )
        merged[key] = copy_item

    for a_idx, a_item in enumerate(track_a, start=1):
        key = _result_dedup_key(a_item)
        a_score = float(a_item.score or 0.0)
        if key in merged:
            existing = merged[key]
            base_b = float(existing.score or 0.0)
            boosted = min(1.0, max(base_b, a_score * a_weight) + 0.15 * min(base_b, a_score))
            existing.score = round(boosted, 4)
            if not existing.sparse_score:
                existing.sparse_score = round(a_score, 4)
            if existing.sparse_rank is None:
                existing.sparse_rank = a_idx
        else:
            copy_a = VectorSearchResult(
                id=a_item.id,
                score=round(min(1.0, a_score * a_weight), 4),
                dense_score=a_item.dense_score,
                sparse_score=a_item.sparse_score or round(a_score, 4),
                dense_rank=a_item.dense_rank,
                sparse_rank=a_item.sparse_rank or a_idx,
                payload=dict(a_item.payload or {}),
            )
            merged[key] = copy_a

    ranked = sorted(merged.values(), key=lambda r: float(r.score or 0.0), reverse=True)
    return strip_internal_metadata(ranked[:limit])
