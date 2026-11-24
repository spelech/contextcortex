"""Multi-query parallel execution, RRF fusion, file/folder diversification, and evidence extraction (#219)."""

import contextvars
import logging
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from app.services.diagnostic_error_terms import _STOP_WORDS, identifier_parts
from app.services.search_ranking import cap_results_per_file
from app.services.vector_store.base import VectorSearchResult

logger = logging.getLogger("contextcortex.expanded_search")

RRF_K = 60
_MAX_EVIDENCE_CHARS = 160

_EVIDENCE_STOP_WORDS = _STOP_WORDS | frozenset({
    "all", "and", "any", "are", "bug", "but", "can", "did", "does", "for", "get", "has", "had",
    "how", "its", "not", "now", "off", "one", "our", "out", "per", "see", "set", "that", "the",
    "their", "them", "then", "there", "these", "they", "this", "those", "two", "via", "was",
    "were", "what", "who", "why", "yes", "yet", "you", "your",
})
_BOILERPLATE_PREFIXES = (
    "using ", "import ", "from ", "package ", "namespace ", "#include", "export {",
)
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
    """Result of splitting a report into concept queries, running each, and fusing + diversifying results."""

    queries: List[str]
    hits: List[VectorSearchResult]
    areas: List[Dict[str, Any]]
    source: str = "heuristic"


def _norm_rel_path(payload: Dict[str, Any]) -> str:
    raw = str(payload.get("rel_path") or payload.get("path") or payload.get("filepath") or "").replace("\\", "/")
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    return raw.lstrip("/")


def area_key_for_path(rel_path: str) -> str:
    """Groups file paths into folder/project areas for result diversification."""
    norm = (rel_path or "").replace("\\", "/").lstrip("/")
    if "://" in norm:
        norm = norm.split("://", 1)[1].lstrip("/")
    parts = [p for p in norm.split("/") if p]
    if len(parts) <= 1:
        return "(root)"
    return "/".join(parts[:-1])


def extract_evidence_line(content: str, matched_queries: Sequence[str]) -> str:
    """Selects one concise, high-signal code line from a chunk as evidence for an area."""
    if not content:
        return ""
    q_terms = {
        tok for q in matched_queries for tok in identifier_parts(q)
        if len(tok) >= 3 and tok not in _EVIDENCE_STOP_WORDS
    }
    best_line = ""
    best_score = -999
    first_non_empty = ""
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
        score = overlap * 3
        if any(m in low for m in _LOGIC_MARKERS):
            score += 2
        if low.startswith(_DECL_PREFIXES):
            score -= 1
        if score > best_score:
            best_score = score
            best_line = line
    chosen = best_line or first_non_empty
    if len(chosen) > _MAX_EVIDENCE_CHARS:
        return chosen[: _MAX_EVIDENCE_CHARS - 3].rstrip() + "..."
    return chosen


def _diversify_by_area(items: List[Any], area_fn: Callable[[Any], str], limit: int, max_per_area: int = 2) -> List[Any]:
    """Caps items per folder/project area on primary pass, backfilling from overflow if under `limit`."""
    safe_limit = max(1, int(limit or 5))
    cap = max(1, int(max_per_area or 2))
    primary: List[Any] = []
    overflow: List[Any] = []
    counts: Dict[str, int] = {}
    for item in items:
        area = area_fn(item).lower()
        seen = counts.get(area, 0)
        if seen < cap:
            counts[area] = seen + 1
            primary.append(item)
        else:
            overflow.append(item)
    return (primary if len(primary) >= safe_limit else primary + overflow)[:safe_limit]


def _build_areas(
    fused_hits: List[VectorSearchResult],
    hit_matched_by: Dict[int, List[int]],
    queries: Sequence[str],
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
            matched_texts = [queries[i] for i in q_indices if 0 <= i < len(queries)]
            by_file[fkey] = {
                "area": area_key_for_path(rel_path),
                "repo": hit_repo,
                "file": rel_path,
                "symbol": p.get("full_symbol") or p.get("symbol"),
                "lines": lines,
                "matched_by": list(q_indices),
                "evidence": extract_evidence_line(str(p.get("content") or ""), matched_texts),
                "score": round(float(h.score or 0.0), 4),
            }
        else:
            existing = by_file[fkey]
            merged = sorted(set(existing["matched_by"]) | set(q_indices))
            existing["matched_by"] = merged
            if not existing["evidence"]:
                matched_texts = [queries[i] for i in merged if 0 <= i < len(queries)]
                existing["evidence"] = extract_evidence_line(str(p.get("content") or ""), matched_texts)
    return _diversify_by_area(
        list(by_file.values()),
        area_fn=lambda a: str(a.get("area") or ""),
        limit=area_limit,
        max_per_area=max_per_area,
    )


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
) -> ExpandedSearchOutcome:
    """Expands a plain-language report into concept queries, runs each, RRF-fuses, and diversifies by file & area."""
    from app.services.query_expansion import expand_report_to_code_queries

    queries, source = expand_report_to_code_queries(report_text, repo=repo, max_queries=max_queries, use_llm=use_llm)
    if not queries:
        return ExpandedSearchOutcome(queries=[], hits=[], areas=[], source=source)

    q_limit = max(int(per_query_limit or max(limit * 2, 10)), 1)

    def _run_one(q: str) -> List[VectorSearchResult]:
        try:
            kwargs: Dict[str, Any] = {
                "query_text": q,
                "doc_type": doc_type,
                "repo": repo,
                "limit": q_limit,
                "search_mode": search_mode,
            }
            if language is not None:
                kwargs["language"] = language
            if category is not None:
                kwargs["category"] = category
            if tag is not None:
                kwargs["tag"] = tag
            if dense_weight is not None:
                kwargs["dense_weight"] = dense_weight
            return search_fn(**kwargs) or []
        except Exception as exc:
            logger.warning(f"Expanded sub-query failed ({q!r}): {exc}")
            return []

    if len(queries) == 1:
        per_query_hits = [_run_one(queries[0])]
    else:
        with ThreadPoolExecutor(max_workers=min(len(queries), 6), thread_name_prefix="ctx-expand") as pool:
            futures = [pool.submit(contextvars.copy_context().run, _run_one, q) for q in queries]
            per_query_hits = [f.result() for f in futures]

    fused_map: Dict[tuple, Dict[str, Any]] = {}
    for q_idx, hits in enumerate(per_query_hits):
        rank = 0
        for hit in hits:
            p = dict(getattr(hit, "payload", None) or {})
            raw_score = float(hit.score) if isinstance(getattr(hit, "score", None), (int, float)) else 0.0
            if min_raw_score is not None and raw_score < min_raw_score:
                continue
            if filter_fn is not None and not filter_fn(p):
                continue
            rank += 1
            rel_path = _norm_rel_path(p)
            hit_repo = p.get("repo") or repo
            sym = p.get("full_symbol") or p.get("symbol") or ""
            bucket = sym if sym else f"line:{int(p.get('start_line') or 0) // 15}"
            dedup_key = (hit_repo or "", rel_path.lower(), bucket)
            entry = fused_map.get(dedup_key)
            rrf_delta = 1.0 / float(RRF_K + rank)
            cloned = VectorSearchResult(
                id=str(getattr(hit, "id", dedup_key)),
                score=raw_score,
                payload=p,
                dense_score=getattr(hit, "dense_score", None),
                sparse_score=getattr(hit, "sparse_score", None),
            )
            if entry is None:
                fused_map[dedup_key] = {"rrf": rrf_delta, "max_raw": raw_score, "matched_by": {q_idx}, "hit": cloned}
            else:
                entry["rrf"] += rrf_delta
                entry["matched_by"].add(q_idx)
                if raw_score > entry["max_raw"]:
                    entry["max_raw"] = raw_score
                    entry["hit"] = cloned

    max_rrf = float(len(queries)) / float(RRF_K + 1)
    ranked_entries = sorted(
        fused_map.values(),
        key=lambda e: (e["rrf"], len(e["matched_by"]), e["max_raw"]),
        reverse=True,
    )
    fused_hits: List[VectorSearchResult] = []
    hit_matched_by: Dict[int, List[int]] = {}
    for entry in ranked_entries:
        h = entry["hit"]
        h.score = round(min(1.0, entry["rrf"] / max_rrf), 4) if max_rrf > 0 else 0.0
        hit_matched_by[id(h)] = sorted(entry["matched_by"])
        fused_hits.append(h)

    file_capped = cap_results_per_file(fused_hits, limit=max(limit * 2, 20), max_per_file=max_per_file)
    diversified_hits = _diversify_by_area(
        file_capped,
        area_fn=lambda h: area_key_for_path(_norm_rel_path(h.payload or {})),
        limit=limit,
        max_per_area=max_per_area,
    )
    target_areas = max(1, min(12, int(area_limit or max(limit, 6))))
    areas = _build_areas(fused_hits, hit_matched_by, queries, repo, target_areas, max_per_area)
    return ExpandedSearchOutcome(queries=queries, hits=diversified_hits, areas=areas, source=source)


__all__ = [
    "ExpandedSearchOutcome",
    "RRF_K",
    "area_key_for_path",
    "extract_evidence_line",
    "run_expanded_code_search",
]
