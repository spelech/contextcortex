import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.services.chunking.tree_sitter_loader import EXTENSION_TO_LANGUAGE, detect_language, is_code_file
from app.services.code_grep_scanner import IGNORED_GREP_DIRS, _collect_target_roots
from app.services.database import get_db_connection
from app.services.file_path_resolver import FilePathResolver
from app.services.git_manager import format_git_permalink
from app.services.local_storage import get_default_storage_path
from app.services.query_router import QueryPlan, _has_term_code_syntax, compute_token_coverage, split_identifier_tokens
from app.services.ripgrep_runner import search_tokens_with_ripgrep
from app.services.vector_store.base import VectorSearchResult

logger = logging.getLogger("contextcortex.lexical_retriever")

_DOC_EXTENSIONS = (".md", ".markdown", ".txt", ".rst", ".adoc", ".yaml", ".yml", ".json")


def _clean_rel_path(raw_path: str, repo: Optional[str]) -> str:
    cleaned = (raw_path or "").replace("\\", "/")
    if "://" in cleaned:
        cleaned = cleaned.split("://", 1)[1]
    cleaned = cleaned.lstrip("/")
    if repo and cleaned.startswith(f"{repo}/"):
        cleaned = cleaned[len(repo) + 1 :]
    return cleaned


def _language_variants(language: Optional[str]) -> List[str]:
    if not language:
        return []
    lang = language.strip().lower()
    if lang in ("csharp", "c_sharp"):
        return ["c_sharp", "csharp"]
    if lang in ("javascript", "js"):
        return ["javascript"]
    if lang in ("typescript", "ts"):
        return ["typescript"]
    return [lang]


def _extensions_for_filter(doc_type: Optional[str], language: Optional[str]) -> Optional[Tuple[str, ...]]:
    if language:
        variants = set(_language_variants(language))
        return tuple(ext for ext, lang in EXTENSION_TO_LANGUAGE.items() if lang in variants) or None
    if doc_type == "code":
        return tuple(ext for ext in EXTENSION_TO_LANGUAGE if is_code_file(f"file{ext}"))
    if doc_type == "doc":
        return _DOC_EXTENSIONS
    return None


def _load_disk_roots(repo: Optional[str], doc_type: Optional[str]) -> Tuple[List[Tuple[str, str]], Dict[str, Dict[str, Any]]]:
    resolver = FilePathResolver(db_conn_factory=lambda: get_db_connection())
    effective_repo = None if repo in ("__all__", "", "all", None) else repo.strip()
    raw_roots = _collect_target_roots(
        storage_root=get_default_storage_path(),
        indexed_paths=resolver.get_authorized_indexed_paths(),
        persistent_repos=resolver.get_authorized_persistent_repos(),
        effective_repo=effective_repo,
    )
    roots: List[Tuple[str, str]] = []
    seen = set()
    for root_p, r_name in raw_roots:
        if doc_type == "code" and r_name == "local_storage":
            continue
        if os.path.isdir(root_p) and (r_name, root_p) not in seen:
            seen.add((r_name, root_p))
            roots.append((root_p, r_name))

    git_repos: Dict[str, Dict[str, Any]] = {}
    try:
        with get_db_connection() as conn:
            for r in conn.execute("SELECT name, url, commit_sha, provider FROM git_repositories").fetchall():
                git_repos[r["name"]] = dict(r)
    except Exception:
        pass
    return roots, git_repos


def _read_disk_slice(roots: List[Tuple[str, str]], repo: Optional[str], rel_path: str, start_line: int, end_line: int) -> Optional[str]:
    norm_rel = _clean_rel_path(rel_path, repo)
    for root_dir, r_name in roots:
        if repo and r_name != repo:
            continue
        candidate = os.path.normpath(os.path.join(root_dir, norm_rel))
        if not candidate.startswith(os.path.normpath(root_dir)) or not os.path.isfile(candidate):
            continue
        try:
            with open(candidate, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
            return "\n".join(lines[max(0, start_line - 1) : min(len(lines), end_line)])
        except OSError:
            return None
    return None


def _hydrate_from_store(store: Any, repo: Optional[str], rel_path: str, start_line: int, end_line: int) -> Optional[Dict[str, Any]]:
    if not store or not hasattr(store, "get_file_chunks"):
        return None
    try:
        chunks = store.get_file_chunks(path=rel_path, repo=repo)
        if not chunks:
            return None
        overlapping = [c for c in chunks if (c.get("end_line") or 999999) >= start_line and (c.get("start_line") or 1) <= end_line]
        return dict(overlapping[0] if overlapping else chunks[0])
    except Exception:
        return None


def _build_hit_id(repo: str, rel_path: str, start_line: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"lex:{repo}:{rel_path}:{start_line}"))


def _permalink(git_repos: Dict[str, Dict[str, Any]], repo: str, rel_p: str, s_line: int, e_line: int) -> Optional[str]:
    g = git_repos.get(repo)
    if not g or not g.get("url"):
        return None
    return format_git_permalink(g["url"], g.get("commit_sha"), rel_p, s_line, e_line, provider=g.get("provider"))


def _extract_priority_terms(plan: QueryPlan) -> List[str]:
    """Returns exact phrase / raw code-syntax identifiers that must match before sub-token OR expansion."""
    terms: List[str] = []
    if plan.exact_phrase and plan.exact_phrase.strip():
        terms.append(plan.exact_phrase.strip())
    for raw in plan.raw_terms:
        cleaned = re.sub(r'^["\'\(\[]+|["\'\)\],;:]+$', "", raw.strip())
        if not cleaned or len(cleaned) < 2:
            continue
        if _has_term_code_syntax(cleaned) or len(plan.raw_terms) == 1:
            terms.append(cleaned)
            if "." in cleaned:
                tail = cleaned.rsplit(".", 1)[-1]
                if len(tail) >= 2:
                    terms.append(tail)
    return list(dict.fromkeys(terms))


def _query_ast_candidates(
    plan: QueryPlan,
    roots: List[Tuple[str, str]],
    git_repos: Dict[str, Dict[str, Any]],
    store: Any,
    repo: Optional[str],
    language: Optional[str],
    limit: int,
    allow_store_hydration: bool,
) -> List[VectorSearchResult]:
    priority_terms = _extract_priority_terms(plan)
    sub_terms = list(dict.fromkeys(([plan.exact_phrase] if plan.exact_phrase else []) + plan.content_tokens[:6]))
    if not priority_terms and not sub_terms:
        return []

    base_parts: List[str] = []
    base_params: List[Any] = []
    if repo and repo not in ("__all__", "all"):
        base_parts.append("repo = ?")
        base_params.append(repo)
    lang_variants = _language_variants(language)
    if lang_variants:
        base_parts.append(f"LOWER(language) IN ({', '.join('?' for _ in lang_variants)})")
        base_params.extend(lang_variants)

    rows: List[Any] = []
    seen_ids = set()
    target_cap = max(limit * 2, 8)
    try:
        with get_db_connection() as conn:
            if priority_terms:
                p_clauses = ["(name LIKE ? OR full_symbol LIKE ? OR filepath LIKE ?)"] * len(priority_terms[:4])
                p_params: List[Any] = [v for t in priority_terms[:4] for v in (f"%{t}%", f"%{t}%", f"%{t}%")]
                primary = priority_terms[0]
                where_p = [f"({' OR '.join(p_clauses)})"] + base_parts
                sql_p = (
                    f"SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language "
                    f"FROM ast_symbols WHERE {' AND '.join(where_p)} "
                    f"ORDER BY (CASE WHEN LOWER(name) = LOWER(?) OR LOWER(full_symbol) = LOWER(?) THEN 0 "
                    f"WHEN LOWER(name) LIKE LOWER(?) OR LOWER(full_symbol) LIKE LOWER(?) THEN 1 ELSE 2 END) ASC LIMIT 40"
                )
                for r in conn.execute(sql_p, p_params + base_params + [primary, primary, f"%{primary}%", f"%{primary}%"]).fetchall():
                    if r["id"] not in seen_ids:
                        seen_ids.add(r["id"])
                        rows.append(r)

            if len(rows) < target_cap and sub_terms:
                clauses = ["(name LIKE ? OR full_symbol LIKE ? OR signature LIKE ? OR filepath LIKE ?)"] * len(sub_terms)
                params: List[Any] = [v for t in sub_terms for v in (f"%{t}%", f"%{t}%", f"%{t}%", f"%{t}%")]
                where_parts = [f"({' OR '.join(clauses)})"] + base_parts
                sql = f"SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language FROM ast_symbols WHERE {' AND '.join(where_parts)} LIMIT 60"
                for r in conn.execute(sql, params + base_params).fetchall():
                    if r["id"] not in seen_ids:
                        seen_ids.add(r["id"])
                        rows.append(r)
    except Exception as exc:
        logger.debug(f"AST lexical query skipped: {exc}")
        return []

    scored_rows = []
    for row in rows:
        rel_p = _clean_rel_path(row["filepath"], row["repo"])
        pre_score, _ = compute_token_coverage(
            plan.content_tokens, rel_path=rel_p, symbol=row["full_symbol"] or row["name"],
            heading=None, content=row["signature"] or "", raw_query=plan.exact_phrase or plan.raw_query,
        )
        if pre_score > 0.0:
            scored_rows.append((pre_score, row))

    scored_rows.sort(key=lambda item: item[0], reverse=True)
    results: List[VectorSearchResult] = []
    for _, row in scored_rows[:target_cap]:
        r_repo = row["repo"]
        rel_p = _clean_rel_path(row["filepath"], r_repo)
        s_line, e_line = int(row["start_line"] or 1), int(row["end_line"] or 1)
        content = _read_disk_slice(roots, r_repo, rel_p, s_line, min(e_line, s_line + 140))
        payload_path = row["filepath"]

        if content is None and allow_store_hydration:
            hydrated = _hydrate_from_store(store, r_repo, rel_p, s_line, e_line)
            if hydrated:
                content = hydrated.get("content") or hydrated.get("text")
                payload_path = hydrated.get("path") or payload_path
                s_line = int(hydrated.get("start_line") or s_line)
                e_line = int(hydrated.get("end_line") or e_line)
        if not content:
            continue

        sym = row["full_symbol"] or row["name"]
        score, meta = compute_token_coverage(
            plan.content_tokens, rel_path=rel_p, symbol=sym, heading=None,
            content=content, raw_query=plan.exact_phrase or plan.raw_query,
        )
        link = _permalink(git_repos, r_repo, rel_p, s_line, e_line)
        results.append(VectorSearchResult(
            id=_build_hit_id(r_repo, rel_p, s_line), score=score, dense_score=0.0, sparse_score=score,
            payload={
                "repo": r_repo, "doc_type": "code", "path": payload_path, "rel_path": rel_p,
                "title": os.path.basename(rel_p), "symbol": sym, "full_symbol": sym,
                "kind": row["kind"], "signature": row["signature"], "ast_symbol_id": row["id"],
                "language": row["language"] or detect_language(rel_p), "start_line": s_line,
                "end_line": e_line, "github_url": link, "permalink_url": link,
                "content": content, "_lexical_meta": meta,
            },
        ))
    return results


def _cluster_rg_hits(
    root_dir: str, r_name: str, rel_p: str, line_hits: List[Tuple[int, str]],
    plan: QueryPlan, git_repos: Dict[str, Dict[str, Any]],
) -> Optional[VectorSearchResult]:
    try:
        with open(os.path.join(root_dir, rel_p), "r", encoding="utf-8", errors="replace") as f:
            file_lines = f.read().splitlines()
    except OSError:
        return None
    if not file_lines:
        return None

    sorted_lines = sorted({ln for ln, _ in line_hits})
    best_start, best_end, best_distinct = sorted_lines[0], sorted_lines[0], -1
    q_tokens_set = set(plan.content_tokens)

    for idx, anchor in enumerate(sorted_lines):
        win_lines = [ln for ln in sorted_lines[idx:] if ln <= anchor + 35]
        snippet_text = "\n".join(file_lines[max(0, anchor - 3) : min(len(file_lines), win_lines[-1] + 5)])
        overlap = len(set(split_identifier_tokens(f"{rel_p} {snippet_text}")) & q_tokens_set)
        if overlap > best_distinct:
            best_distinct = overlap
            best_start = max(1, anchor - 5)
            best_end = min(len(file_lines), win_lines[-1] + 15)

    snippet = "\n".join(file_lines[best_start - 1 : min(len(file_lines), best_end)])
    doc_t = "code" if is_code_file(rel_p) else "doc"
    score, meta = compute_token_coverage(
        plan.content_tokens, rel_path=rel_p, symbol=None, heading=None,
        content=snippet, raw_query=plan.exact_phrase or plan.raw_query,
    )
    if score <= 0.0:
        return None
    link = _permalink(git_repos, r_name, rel_p, best_start, best_end)
    return VectorSearchResult(
        id=_build_hit_id(r_name, rel_p, best_start), score=score, dense_score=0.0, sparse_score=score,
        payload={
            "repo": r_name, "doc_type": doc_t, "path": rel_p, "rel_path": rel_p,
            "title": os.path.basename(rel_p), "language": detect_language(rel_p) if doc_t == "code" else None,
            "start_line": best_start, "end_line": best_end, "github_url": link, "permalink_url": link,
            "content": snippet, "_lexical_meta": meta,
        },
    )


def _query_rg_disk_candidates(
    plan: QueryPlan, roots: List[Tuple[str, str]], git_repos: Dict[str, Dict[str, Any]],
    doc_type: Optional[str], language: Optional[str], category: Optional[str], tag: Optional[str], limit: int,
) -> List[VectorSearchResult]:
    if category or tag or not roots:
        return []
    exts = _extensions_for_filter(doc_type, language)
    priority_terms = _extract_priority_terms(plan)
    sub_terms = list(dict.fromkeys(([plan.exact_phrase] if plan.exact_phrase else []) + plan.content_tokens[:6]))
    if not priority_terms and not sub_terms:
        return []

    candidates: List[VectorSearchResult] = []
    q_set = set(plan.content_tokens)
    for root_dir, r_name in roots:
        by_file = None
        if priority_terms:
            by_file = search_tokens_with_ripgrep(
                root_dir=root_dir, tokens=priority_terms[:4], ignored_dirs=IGNORED_GREP_DIRS,
                extensions=exts, max_per_file=20, max_files=40,
            )
        if not by_file and sub_terms:
            by_file = search_tokens_with_ripgrep(
                root_dir=root_dir, tokens=sub_terms, ignored_dirs=IGNORED_GREP_DIRS,
                extensions=exts, max_per_file=20, max_files=40,
            )
        if not by_file:
            continue
        ranked_files = sorted(
            ((len(set(split_identifier_tokens(f"{rp} " + " ".join(txt for _, txt in hits[:10]))) & q_set), rp, hits) for rp, hits in by_file.items()),
            key=lambda item: item[0], reverse=True,
        )
        for _, rel_p, hits in ranked_files[: max(limit * 2, 6)]:
            res = _cluster_rg_hits(root_dir, r_name, rel_p, hits, plan, git_repos)
            if res is not None:
                candidates.append(res)
    return candidates


def _query_summary_candidates(
    plan: QueryPlan, roots: List[Tuple[str, str]], store: Any, repo: Optional[str],
    category: Optional[str], tag: Optional[str], limit: int, allow_store_hydration: bool,
) -> List[VectorSearchResult]:
    terms = plan.content_tokens[:6]
    if not terms:
        return []
    clauses = ["(title LIKE ? OR headings LIKE ? OR keywords LIKE ? OR filepath LIKE ?)"] * len(terms)
    params: List[Any] = [v for t in terms for v in (f"%{t}%", f"%{t}%", f"%{t}%", f"%{t}%")]
    where_parts = [f"({' OR '.join(clauses)})"]
    if repo and repo not in ("__all__", "all"):
        where_parts.append("repo = ?")
        params.append(repo)
    if category:
        where_parts.append("category = ?")
        params.append(category)

    sql = f"SELECT repo, filepath, title, category, tags, headings, keywords FROM file_summaries WHERE {' AND '.join(where_parts)} LIMIT 30"
    try:
        with get_db_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
    except Exception:
        return []

    out: List[VectorSearchResult] = []
    for row in rows[: max(limit * 2, 6)]:
        if tag:
            try:
                if tag not in json.loads(row["tags"] or "[]"):
                    continue
            except Exception:
                continue
        r_repo = row["repo"]
        rel_p = _clean_rel_path(row["filepath"], r_repo)
        content = _read_disk_slice(roots, r_repo, rel_p, 1, 120)
        payload_path, heading = row["filepath"], None
        if content is None and allow_store_hydration:
            hydrated = _hydrate_from_store(store, r_repo, rel_p, 1, 120)
            if hydrated:
                content = hydrated.get("content") or hydrated.get("text")
                payload_path = hydrated.get("path") or payload_path
                heading = hydrated.get("heading")
        if not content:
            continue
        score, meta = compute_token_coverage(
            plan.content_tokens, rel_path=rel_p, symbol=None, heading=heading or row["title"],
            content=content, raw_query=plan.exact_phrase or plan.raw_query,
        )
        if score <= 0.0:
            continue
        out.append(VectorSearchResult(
            id=_build_hit_id(r_repo, rel_p, 1), score=score, dense_score=0.0, sparse_score=score,
            payload={
                "repo": r_repo, "doc_type": "doc", "path": payload_path, "rel_path": rel_p,
                "title": row["title"], "category": row["category"], "heading": heading or row["title"],
                "start_line": 1, "end_line": min(120, len(content.splitlines()) or 1),
                "content": content, "_lexical_meta": meta,
            },
        ))
    return out


def run_fast_lexical_track(
    plan: QueryPlan,
    store: Any,
    doc_type: Optional[str] = None,
    repo: Optional[str] = None,
    language: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 5,
    allow_store_chunk_hydration: bool = True,
) -> List[VectorSearchResult]:
    """Runs fast Track A lexical retrieval (AST symbols + ripgrep disk scan + file summaries)."""
    roots, git_repos = _load_disk_roots(repo, doc_type)
    candidates: List[VectorSearchResult] = []
    if doc_type != "doc" and not category and not tag:
        candidates.extend(_query_ast_candidates(plan, roots, git_repos, store, repo, language, limit, allow_store_chunk_hydration))
    candidates.extend(_query_rg_disk_candidates(plan, roots, git_repos, doc_type, language, category, tag, limit))
    if doc_type != "code" and not language:
        candidates.extend(_query_summary_candidates(plan, roots, store, repo, category, tag, limit, allow_store_chunk_hydration))

    deduped: Dict[Tuple[str, str], VectorSearchResult] = {}
    for item in candidates:
        p = item.payload or {}
        key = (str(p.get("repo") or ""), str(p.get("rel_path") or p.get("path") or ""))
        if key not in deduped or float(item.score or 0.0) > float(deduped[key].score or 0.0):
            deduped[key] = item

    return sorted(deduped.values(), key=lambda r: float(r.score or 0.0), reverse=True)[: max(limit, 8)]
