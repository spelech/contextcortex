"""Multi-round expanded code search, corpus-grounded PRF, RRF + per-query slot preservation, and area diversification (#219, #223, #224, #227, #228)."""

import contextvars
import logging
import os
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from app.services.diagnostic_error_terms import _STOP_WORDS, identifier_parts, is_data_value_token
from app.services.query_router import classify_query_intent
from app.services.search_ranking import cap_results_per_file
from app.services.stack_trace_parser import (
    RE_EXCEPTION_NAME, RE_SYMBOL_CANDIDATE, _is_test_path, extract_http_routes, parse_stack_frames,
)
from app.services.vector_store.base import VectorSearchResult

logger = logging.getLogger("contextcortex.expanded_search")

RRF_K = 60
_MAX_EVIDENCE_CHARS = 160
_MAX_ROUND2_QUERIES = 4
_ROUND1_SYMBOL_TOP_N = 20
_HEURISTIC_R2_RRF_WEIGHT = 0.5

_EVIDENCE_STOP_WORDS = _STOP_WORDS | frozenset({
    "all", "and", "any", "are", "bug", "but", "can", "did", "does", "for", "get", "has", "had",
    "how", "its", "not", "now", "off", "one", "our", "out", "per", "see", "set", "that", "the",
    "their", "them", "then", "there", "these", "they", "this", "those", "two", "via", "was",
    "were", "what", "who", "why", "yes", "yet", "you", "your",
})
_SYMBOL_BOILERPLATE = _EVIDENCE_STOP_WORDS | frozenset({
    "abstract", "async", "base", "class", "controller", "convert", "default", "dto", "entity",
    "enumerable", "handler", "helper", "impl", "interface", "internal", "manager", "model",
    "private", "public", "repository", "selection", "service", "spec", "static", "status",
    "task", "test", "tests", "track", "tracking", "util", "utils", "view", "void",
})
_SYNONYM_GROUPS: Tuple[frozenset, ...] = (
    frozenset({"accessor", "link", "attach", "relat", "associat", "component", "child", "addon"}),
    frozenset({"item", "product", "part", "sku", "good", "catalog"}),
    frozenset({"miss", "hid", "hide", "visibl", "show", "shown", "display", "remov", "exclud", "omit", "inlin"}),
    frozenset({"primar", "main", "master", "root", "parent"}),
    frozenset({"lookup", "find", "fetch", "retriev", "resolv", "map", "build"}),
)
_NON_CODE_BRAND_WORDS = frozenset({
    "ios", "ipad", "iphone", "macos", "android", "github", "gitlab", "graphql", "postgresql",
    "mysql", "mongodb", "javascript", "typescript", "dotnet", "aspnet", "openai", "litellm", "oauth",
})
_AUTO_EXPAND_SYMPTOM_MARKERS = (
    " but ", " however ", " unless ", " when ", " instead ", " does not ", " doesn't ",
    " missing ", " wrong ", " fails ", " broken ", " not show", " never ", " only when ",
    " empty ", " shows ", " visible ", " pops ",
)
_BOILERPLATE_PREFIXES = ("using ", "import ", "from ", "package ", "namespace ", "#include", "export {")
_DECL_PREFIXES = (
    "public class ", "private class ", "internal class ", "protected class ", "class ",
    "public interface ", "interface ", "public struct ", "struct ", "def ", "async def ",
    "function ", "export function ", "export class ", "export const ",
)
_LOGIC_MARKERS = (
    "if ", "if(", "else", "return ", "where", "remove", "exclude", "filter", "contains",
    "==", "!=", "&&", "||", "=>", "throw ", "raise ", "switch", "case ",
)


@dataclass
class ExpandedSearchOutcome:
    """Result of multi-round concept query expansion, RRF fusion, per-query slot retention, and area diversification."""

    queries: List[Dict[str, Any]]
    hits: List[VectorSearchResult]
    areas: List[Dict[str, Any]]
    source: str = "heuristic"
    expansion: Dict[str, str] = field(default_factory=lambda: {"round1": "heuristic", "round2": "skipped"})


def _simple_stem(token: str) -> str:
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


def _has_real_code_symbol(text: str) -> bool:
    """True when `text` contains a real code identifier (ignoring brand/platform words like iOS/macOS and data SKUs)."""
    for match in RE_SYMBOL_CANDIDATE.finditer(text):
        tok = match.group(0)
        low = tok.lower()
        if low in _NON_CODE_BRAND_WORDS or is_data_value_token(tok):
            continue
        if len(tok) <= 3 and "." not in tok and "_" not in tok:
            continue
        return True
    return False


def should_auto_expand_search_query(query: str, scope: str = "all") -> bool:
    """True when `search` receives a plain-language bug report with no code identifiers or real HTTP routes (#224, #227)."""
    if (scope or "all").strip().lower() in ("docs", "doc"):
        return False
    text = " ".join((query or "").split())
    words = text.split()
    if len(words) < 7:
        return False
    if parse_stack_frames(text) or extract_http_routes(text) or RE_EXCEPTION_NAME.search(text) or _has_real_code_symbol(text):
        return False
    if len(words) < 12 and classify_query_intent(text).intent == "lexical_exact" and ('"' in text or "::" in text or "->" in text):
        return False
    sentence_ends = sum(1 for i, c in enumerate(text) if c in ".!?" and (i + 1 == len(text) or text[i + 1].isspace()))
    if len(words) >= 20 or sentence_ends >= 2:
        return True
    return any(m in f" {text.lower()} " for m in _AUTO_EXPAND_SYMPTOM_MARKERS)


def _norm_rel_path(payload: Dict[str, Any]) -> str:
    raw = str(payload.get("rel_path") or payload.get("path") or payload.get("filepath") or "").replace("\\", "/")
    return (raw.split("://", 1)[1] if "://" in raw else raw).lstrip("/")


def area_key_for_path(rel_path: str) -> str:
    norm = (rel_path or "").replace("\\", "/").lstrip("/")
    if "://" in norm:
        norm = norm.split("://", 1)[1].lstrip("/")
    parts = [p for p in norm.split("/") if p]
    return "(root)" if len(parts) <= 1 else "/".join(parts[:-1])


def extract_evidence_line(content: str, matched_queries: Sequence[str]) -> str:
    """Selects one concise, high-signal executable code line from a chunk as evidence for an area."""
    if not content:
        return ""
    q_terms = {tok for q in matched_queries for tok in identifier_parts(q) if len(tok) >= 3 and tok not in _EVIDENCE_STOP_WORDS}
    best_line, best_score, first_non_empty = "", -999, ""
    for raw_line in content.splitlines():
        line = " ".join(raw_line.strip().split())
        if not line:
            continue
        if not first_non_empty:
            first_non_empty = line
        if line in ("{", "}", ");", "};", "]", "),") or line.startswith(("//", "/*", "*", "*/")):
            continue
        low = line.lower()
        if low.startswith(_BOILERPLATE_PREFIXES):
            continue
        parts = set(identifier_parts(line))
        overlap = sum(1 for t in q_terms if t in parts or (len(t) >= 5 and t in low))
        is_decl = low.startswith(_DECL_PREFIXES)
        has_logic = any(m in low for m in _LOGIC_MARKERS)
        score = (overlap * 3) + (4 if has_logic else 0) - (8 if is_decl and not has_logic else 0)
        if score > best_score:
            best_score, best_line = score, line
    chosen = best_line or first_non_empty
    return (chosen[: _MAX_EVIDENCE_CHARS - 3].rstrip() + "...") if len(chosen) > _MAX_EVIDENCE_CHARS else chosen


def _diversify_by_area(items: List[Any], area_fn: Callable[[Any], str], limit: int, max_per_area: int = 2) -> List[Any]:
    safe_limit, cap = max(1, int(limit or 5)), max(1, int(max_per_area or 2))
    primary, overflow, counts = [], [], {}
    for item in items:
        area = area_fn(item).lower()
        seen = counts.get(area, 0)
        if seen < cap:
            counts[area] = seen + 1
            primary.append(item)
        else:
            overflow.append(item)
    return (primary if len(primary) >= safe_limit else primary + overflow)[:safe_limit]


def _anchor_stems(report_text: str, round1_queries: Sequence[str]) -> Set[str]:
    base_stems: Set[str] = set()
    for text in (report_text, *round1_queries):
        for tok in identifier_parts(text or ""):
            if len(tok) >= 3 and tok not in _EVIDENCE_STOP_WORDS and not is_data_value_token(tok):
                base_stems.add(_simple_stem(tok))
    expanded = set(base_stems)
    for group in _SYNONYM_GROUPS:
        if any(s in group or any(s.startswith(g) or g.startswith(s) for g in group) for s in base_stems):
            expanded.update(group)
    return expanded


def _build_round2_queries(
    report_text: str,
    round1_queries: Sequence[str],
    round1_ranked_entries: Sequence[Dict[str, Any]],
    *,
    llm_mode: bool,
    max_queries: int = _MAX_ROUND2_QUERIES,
) -> Tuple[List[str], str]:
    """Derives 2-4 corpus-grounded round-2 queries; returns `(queries, round2_source)` (#223, #228)."""
    from app.services.query_expansion import expand_round2_with_llm

    anchors = _anchor_stems(report_text, round1_queries)
    if not anchors or not round1_ranked_entries:
        return [], "skipped"

    report_stems = {_simple_stem(t) for t in identifier_parts(report_text or "") if len(t) >= 3}
    existing_sets = [frozenset(identifier_parts(q)) for q in round1_queries]
    word_df: Counter = Counter()
    candidate_phrases: List[Tuple[Tuple[int, float, int], List[str]]] = []
    seen_phrase_sets: List[frozenset] = []

    for entry in round1_ranked_entries[:_ROUND1_SYMBOL_TOP_N]:
        p = entry["hit"].payload or {}
        rel_path = _norm_rel_path(p)
        if rel_path and _is_test_path(rel_path):
            continue
        raw_names = [p.get("full_symbol") or "", p.get("symbol") or ""]
        if rel_path:
            raw_names.append(os.path.splitext(os.path.basename(rel_path))[0])

        hit_words: Set[str] = set()
        for raw_name in raw_names:
            if not raw_name:
                continue
            words = [
                w for w in OrderedDict.fromkeys(identifier_parts(raw_name))
                if len(w) >= 3 and w not in _SYMBOL_BOILERPLATE and not is_data_value_token(w)
            ]
            if len(words) < 2:
                continue
            stems = [_simple_stem(w) for w in words]
            if not any(s in anchors or any(s.startswith(a) for a in anchors if len(a) >= 4) for s in stems):
                continue
            hit_words.update(words)
            phrase_words = words[:8]
            sig = frozenset(phrase_words)
            if sig in existing_sets or sig in seen_phrase_sets:
                continue
            novel_count = sum(1 for s in stems if s not in report_stems)
            if novel_count == 0 and len(phrase_words) < 3:
                continue
            seen_phrase_sets.append(sig)
            candidate_phrases.append(((novel_count, float(entry["rrf"]), len(phrase_words)), phrase_words))
        for w in hit_words:
            word_df[w] += 1

    if not word_df:
        return [], "skipped"
    top_symbol_words = [w for w, _cnt in word_df.most_common(40)]

    # When an LLM is configured, prefer skipping round 2 over fusing noisy symbol-phrase fallback queries (#228).
    if llm_mode:
        llm_r2 = expand_round2_with_llm(report_text, top_symbol_words, max_queries=max_queries)
        if llm_r2:
            filtered = [q for q in llm_r2 if frozenset(identifier_parts(q)) not in existing_sets]
            if filtered:
                return filtered[:max_queries], "llm"
        return [], "skipped"

    candidate_phrases.sort(key=lambda item: item[0], reverse=True)
    out, out_sets = [], list(existing_sets)
    for _score, words in candidate_phrases:
        sig = frozenset(words)
        if sig not in out_sets:
            out_sets.append(sig)
            out.append(" ".join(words))
            if len(out) >= max_queries:
                break
    if len(out) < min(2, max_queries) and len(top_symbol_words) >= 3:
        novel = [w for w in top_symbol_words if _simple_stem(w) not in report_stems][:4]
        anchor = [w for w in top_symbol_words if _simple_stem(w) in report_stems][:2]
        combo = list(OrderedDict.fromkeys(novel + anchor))[:6]
        if len(combo) >= 2 and frozenset(combo) not in out_sets:
            out.append(" ".join(combo))
    return (out[:max_queries], "heuristic") if out else ([], "skipped")


def _run_batch(queries: Sequence[str], run_one: Callable[[str], List[VectorSearchResult]]) -> List[List[VectorSearchResult]]:
    if not queries:
        return []
    if len(queries) == 1:
        return [run_one(queries[0])]
    with ThreadPoolExecutor(max_workers=min(len(queries), 6), thread_name_prefix="ctx-expand") as pool:
        return [f.result() for f in [pool.submit(contextvars.copy_context().run, run_one, q) for q in queries]]


def _accumulate_rrf(
    fused_map: Dict[tuple, Dict[str, Any]],
    per_query_hits: Sequence[List[VectorSearchResult]],
    start_q_idx: int,
    *,
    repo: Optional[str],
    filter_fn: Optional[Callable[[Dict[str, Any]], bool]],
    min_raw_score: Optional[float],
    per_query_top_files: Dict[int, List[Tuple[str, str]]],
    rrf_weight: float = 1.0,
) -> None:
    for offset, hits in enumerate(per_query_hits):
        q_idx = start_q_idx + offset
        rank = 0
        top_files: List[Tuple[str, str]] = []
        seen_q_files: Set[Tuple[str, str]] = set()
        for hit in hits:
            p = dict(getattr(hit, "payload", None) or {})
            raw_score = float(hit.score) if isinstance(getattr(hit, "score", None), (int, float)) else 0.0
            if (min_raw_score is not None and raw_score < min_raw_score) or (filter_fn is not None and not filter_fn(p)):
                continue
            rank += 1
            rel_path = _norm_rel_path(p)
            hit_repo = p.get("repo") or repo
            fkey = (hit_repo or "", rel_path.lower())
            if rel_path and fkey not in seen_q_files:
                seen_q_files.add(fkey)
                top_files.append(fkey)
            sym = p.get("full_symbol") or p.get("symbol") or ""
            bucket = sym if sym else f"line:{int(p.get('start_line') or 0) // 15}"
            dedup_key = (hit_repo or "", rel_path.lower(), bucket)
            entry = fused_map.get(dedup_key)
            rrf_delta = float(rrf_weight) / float(RRF_K + rank)
            cloned = VectorSearchResult(
                id=str(getattr(hit, "id", dedup_key)), score=raw_score, payload=p,
                dense_score=getattr(hit, "dense_score", None), sparse_score=getattr(hit, "sparse_score", None),
            )
            if entry is None:
                fused_map[dedup_key] = {"rrf": rrf_delta, "max_raw": raw_score, "matched_by": {q_idx}, "hit": cloned}
            else:
                entry["rrf"] += rrf_delta
                entry["matched_by"].add(q_idx)
                if raw_score > entry["max_raw"]:
                    entry["max_raw"] = raw_score
                    entry["hit"] = cloned
        per_query_top_files[q_idx] = top_files[:2]


def _build_areas_with_per_query_slots(
    fused_hits: List[VectorSearchResult],
    hit_matched_by: Dict[int, List[int]],
    query_texts: Sequence[str],
    per_query_top_files: Dict[int, List[Tuple[str, str]]],
    repo: Optional[str],
    area_limit: int,
    max_per_area: int,
) -> List[Dict[str, Any]]:
    by_file: "OrderedDict[Tuple[str, str], Dict[str, Any]]" = OrderedDict()
    for h in fused_hits:
        p = h.payload or {}
        rel_path = _norm_rel_path(p)
        if not rel_path:
            continue
        hit_repo = p.get("repo") or repo
        fkey = (hit_repo or "", rel_path.lower())
        q_indices = hit_matched_by.get(id(h), [])
        if fkey not in by_file:
            start_l, end_l = p.get("start_line"), p.get("end_line")
            lines = [start_l, end_l] if start_l is not None and end_l is not None else None
            matched_texts = [query_texts[i] for i in q_indices if 0 <= i < len(query_texts)]
            by_file[fkey] = {
                "area": area_key_for_path(rel_path), "repo": hit_repo, "file": rel_path,
                "symbol": p.get("full_symbol") or p.get("symbol"), "lines": lines,
                "matched_by": list(q_indices), "evidence": extract_evidence_line(str(p.get("content") or ""), matched_texts),
                "score": round(float(h.score or 0.0), 4),
            }
        else:
            existing = by_file[fkey]
            existing["matched_by"] = sorted(set(existing["matched_by"]) | set(q_indices))
            if not existing["evidence"]:
                matched_texts = [query_texts[i] for i in existing["matched_by"] if 0 <= i < len(query_texts)]
                existing["evidence"] = extract_evidence_line(str(p.get("content") or ""), matched_texts)

    rrf_diversified = _diversify_by_area(
        list(by_file.values()), area_fn=lambda a: str(a.get("area") or ""), limit=area_limit, max_per_area=max_per_area
    )
    leader_slots = min(len(rrf_diversified), max(3, area_limit // 2))
    selected: List[Dict[str, Any]] = list(rrf_diversified[:leader_slots])
    selected_keys: Set[Tuple[str, str]] = {(str(a.get("repo") or ""), str(a["file"]).lower()) for a in selected}

    for slot_rank in (0, 1):
        for q_idx in sorted(per_query_top_files):
            if len(selected) >= area_limit:
                break
            q_files = per_query_top_files[q_idx]
            if slot_rank < len(q_files) and q_files[slot_rank] not in selected_keys and q_files[slot_rank] in by_file:
                selected.append(by_file[q_files[slot_rank]])
                selected_keys.add(q_files[slot_rank])

    for area in rrf_diversified[leader_slots:]:
        if len(selected) >= area_limit:
            break
        fkey = (str(area.get("repo") or ""), str(area["file"]).lower())
        if fkey not in selected_keys:
            selected.append(area)
            selected_keys.add(fkey)
    return selected[:area_limit]


def run_expanded_code_search(
    report_text: str,
    search_fn: Callable[..., List[VectorSearchResult]],
    *,
    repo: Optional[str] = None,
    doc_type: Optional[str] = "code",
    language: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 8,
    per_query_limit: Optional[int] = None,
    dense_weight: Optional[float] = None,
    search_mode: str = "hybrid",
    max_queries: int = 6,
    max_per_file: int = 2,
    max_per_area: int = 2,
    area_limit: Optional[int] = None,
    filter_fn: Optional[Callable[[Dict[str, Any]], bool]] = None,
    min_raw_score: Optional[float] = None,
    use_llm: bool = True,
    enable_round2: bool = True,
) -> ExpandedSearchOutcome:
    """Runs round-1 expansion + corpus-grounded round-2 PRF, RRF fusion with per-query slots, and area diversification."""
    from app.services.database.connection import get_chat_model
    from app.services.query_expansion import expand_report_to_code_queries

    round1_queries, round1_source = expand_report_to_code_queries(report_text, repo=repo, max_queries=max_queries, use_llm=use_llm)
    if not round1_queries:
        return ExpandedSearchOutcome(queries=[], hits=[], areas=[], source=round1_source, expansion={"round1": round1_source, "round2": "skipped"})

    q_limit = max(int(per_query_limit or max(limit * 2, 10)), 1)

    def _run_one(q: str) -> List[VectorSearchResult]:
        try:
            kwargs: Dict[str, Any] = {"query_text": q, "doc_type": doc_type, "repo": repo, "limit": q_limit, "search_mode": search_mode}
            for k, v in (("language", language), ("category", category), ("tag", tag), ("dense_weight", dense_weight)):
                if v is not None:
                    kwargs[k] = v
            return search_fn(**kwargs) or []
        except Exception as exc:
            logger.warning(f"Expanded sub-query failed ({q!r}): {exc}")
            return []

    fused_map: Dict[tuple, Dict[str, Any]] = {}
    per_query_top_files: Dict[int, List[Tuple[str, str]]] = {}

    r1_hits = _run_batch(round1_queries, _run_one)
    _accumulate_rrf(
        fused_map, r1_hits, 0, repo=repo, filter_fn=filter_fn, min_raw_score=min_raw_score,
        per_query_top_files=per_query_top_files, rrf_weight=1.0,
    )

    query_entries: List[Dict[str, Any]] = [{"query": q, "round": 1, "source": round1_source} for q in round1_queries]
    query_texts: List[str] = list(round1_queries)
    round2_source = "skipped"
    total_rrf_weight = float(len(round1_queries))

    llm_configured = bool(use_llm and get_chat_model())
    if enable_round2 and fused_map and doc_type in (None, "code"):
        r1_ranked = sorted(fused_map.values(), key=lambda e: (e["rrf"], len(e["matched_by"]), e["max_raw"]), reverse=True)
        r2_queries, round2_source = _build_round2_queries(
            report_text, round1_queries, r1_ranked, llm_mode=llm_configured, max_queries=_MAX_ROUND2_QUERIES
        )
        if r2_queries:
            r2_weight = 1.0 if round2_source == "llm" else _HEURISTIC_R2_RRF_WEIGHT
            r2_hits = _run_batch(r2_queries, _run_one)
            _accumulate_rrf(
                fused_map, r2_hits, len(query_texts), repo=repo, filter_fn=filter_fn, min_raw_score=min_raw_score,
                per_query_top_files=per_query_top_files, rrf_weight=r2_weight,
            )
            query_entries.extend({"query": q, "round": 2, "source": round2_source} for q in r2_queries)
            query_texts.extend(r2_queries)
            total_rrf_weight += r2_weight * float(len(r2_queries))

    max_rrf = total_rrf_weight / float(RRF_K + 1)
    ranked_entries = sorted(fused_map.values(), key=lambda e: (e["rrf"], len(e["matched_by"]), e["max_raw"]), reverse=True)
    fused_hits: List[VectorSearchResult] = []
    hit_matched_by: Dict[int, List[int]] = {}
    for entry in ranked_entries:
        h = entry["hit"]
        h.score = round(min(1.0, entry["rrf"] / max_rrf), 4) if max_rrf > 0 else 0.0
        hit_matched_by[id(h)] = sorted(entry["matched_by"])
        fused_hits.append(h)

    file_capped = cap_results_per_file(fused_hits, limit=max(limit * 2, 20), max_per_file=max_per_file)
    diversified_hits = _diversify_by_area(
        file_capped, area_fn=lambda h: area_key_for_path(_norm_rel_path(h.payload or {})), limit=limit, max_per_area=max_per_area,
    )
    target_areas = max(1, min(15, int(area_limit or max(limit, 10))))
    areas = _build_areas_with_per_query_slots(
        fused_hits, hit_matched_by, query_texts, per_query_top_files, repo, target_areas, max_per_area
    )
    return ExpandedSearchOutcome(
        queries=query_entries, hits=diversified_hits, areas=areas, source=round1_source,
        expansion={"round1": round1_source, "round2": round2_source},
    )


__all__ = ["ExpandedSearchOutcome", "RRF_K", "area_key_for_path", "extract_evidence_line", "run_expanded_code_search", "should_auto_expand_search_query"]
