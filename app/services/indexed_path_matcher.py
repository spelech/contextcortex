"""Suffix resolution and ranked path suggestions against the `indexed_files` table."""

import os
from typing import Any, Callable, List, Tuple

_COMMON_SUFFIXES = (
    "resolver", "handler", "service", "factory", "provider", "manager",
    "repository", "controller", "adapter", "client", "builder", "helper",
    "impl", "tests", "test",
)


def _strip_repo_prefix(filepath: str, repo_name: str) -> str:
    fp = str(filepath or "").replace("\\", "/")
    prefix = f"{repo_name}://"
    if fp.startswith(prefix):
        return fp[len(prefix):]
    if "://" in fp:
        return fp.split("://", 1)[1].lstrip("/")
    return fp.lstrip("/")


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _extract_stems(stem: str) -> List[str]:
    """Derives candidate stems via common suffix stripping and linear CamelCase prefix splitting."""
    stems: List[str] = [stem.lower()]
    cur = stem
    for _ in range(3):
        low = cur.lower()
        stripped = next((cur[:-len(suf)] for suf in _COMMON_SUFFIXES if low.endswith(suf) and len(cur) - len(suf) >= 4), None)
        if not stripped:
            break
        cur = stripped.rstrip("_-.")
        if cur and cur.lower() not in stems:
            stems.append(cur.lower())

    camel_parts: List[str] = []
    buf: List[str] = []
    for idx_c, ch in enumerate(stem[:120]):
        if not ch.isalnum():
            if buf:
                camel_parts.append("".join(buf))
                buf = []
            continue
        if buf and ch.isupper():
            prev_lower = buf[-1].islower() or buf[-1].isdigit()
            next_lower = (idx_c + 1 < len(stem) and stem[idx_c + 1].islower())
            if prev_lower or (buf[-1].isupper() and next_lower):
                camel_parts.append("".join(buf))
                buf = [ch]
                continue
        buf.append(ch)
    if buf:
        camel_parts.append("".join(buf))
    if len(camel_parts) >= 3:
        for k in range(len(camel_parts) - 1, 1, -1):
            pref = "".join(camel_parts[:k]).lower()
            if len(pref) >= 4 and pref not in stems:
                stems.append(pref)
    return stems


def _trailing_segment_match_count(cand_path: str, req_parts_low: List[str]) -> int:
    cand_parts = [p for p in cand_path.lower().split("/") if p]
    matched = 0
    for c_seg, r_seg in zip(reversed(cand_parts), reversed(req_parts_low)):
        if c_seg == r_seg:
            matched += 1
        else:
            break
    return matched


def find_suffix_indexed_files(
    db_conn_factory: Callable[[], Any],
    clean_path: str,
    repo_name: str,
    limit: int = 20,
) -> List[str]:
    """Returns indexed paths in `repo_name` equal to `clean_path` or ending with `/<clean_path>` (case-insensitive)."""
    if not clean_path or not repo_name:
        return []
    rel = clean_path.replace("\\", "/").strip("/")
    if not rel or ".." in rel.split("/"):
        return []
    rel_low = rel.lower()
    esc_rel = _escape_like(rel_low)
    repo_uri_low = f"{repo_name.lower()}://{rel_low}"

    try:
        with db_conn_factory() as conn:
            rows = conn.execute(
                "SELECT filepath FROM indexed_files WHERE repo = ? AND ("
                "LOWER(REPLACE(filepath, '\\', '/')) LIKE ? ESCAPE '\\' "
                "OR LOWER(REPLACE(filepath, '\\', '/')) = ? "
                "OR LOWER(REPLACE(filepath, '\\', '/')) = ?) LIMIT ?",
                (repo_name, f"%/{esc_rel}", repo_uri_low, rel_low, max(2, int(limit) * 2)),
            ).fetchall()
    except Exception:
        return []

    matches: List[str] = []
    seen = set()
    for r in rows:
        cand = _strip_repo_prefix(r["filepath"], repo_name)
        if not cand or cand in seen:
            continue
        cand_low = cand.lower()
        if cand_low == rel_low or cand_low.endswith(f"/{rel_low}"):
            seen.add(cand)
            matches.append(cand)
    matches.sort(key=lambda p: (len(p), p))
    return matches[:limit]


def suggest_similar_indexed_files(
    db_conn_factory: Callable[[], Any],
    clean_path: str,
    repo_name: str,
    limit: int = 5,
) -> List[str]:
    """Returns up to `limit` close indexed paths, prioritizing exact suffixes and matching trailing path segments."""
    if not clean_path or not repo_name:
        return []
    rel = clean_path.replace("\\", "/").strip("/")
    basename = os.path.basename(rel)
    if not basename:
        return []

    rel_low = rel.lower()
    req_parts_low = [p for p in rel_low.split("/") if p]
    req_dir = os.path.dirname(rel).lower()
    stem, _ = os.path.splitext(basename)
    stems = _extract_stems(stem)

    # Start with exact suffix matches so they can never be crowded out by same-basename files.
    exact_suffixes = find_suffix_indexed_files(db_conn_factory, rel, repo_name, limit=max(limit, 10))
    if len(exact_suffixes) >= limit:
        return exact_suffixes[:limit]

    like_clauses: List[str] = []
    params: List[Any] = [repo_name]
    if len(req_parts_low) >= 2:
        tail2 = "/".join(req_parts_low[-2:])
        like_clauses.append("LOWER(REPLACE(filepath, '\\', '/')) LIKE ? ESCAPE '\\'")
        params.append(f"%/{_escape_like(tail2)}")
    like_clauses.append("LOWER(REPLACE(filepath, '\\', '/')) LIKE ? ESCAPE '\\'")
    params.append(f"%/{_escape_like(basename.lower())}")
    for st in stems[:5]:
        like_clauses.append("LOWER(REPLACE(filepath, '\\', '/')) LIKE ? ESCAPE '\\'")
        params.append(f"%{_escape_like(st)}%")
    if req_dir:
        like_clauses.append("LOWER(REPLACE(filepath, '\\', '/')) LIKE ? ESCAPE '\\'")
        params.append(f"%/{_escape_like(req_dir)}/%")

    rows = []
    try:
        with db_conn_factory() as conn:
            rows = conn.execute(
                f"SELECT filepath FROM indexed_files WHERE repo = ? AND ({' OR '.join(like_clauses)}) LIMIT 80",
                params,
            ).fetchall()
    except Exception:
        return exact_suffixes[:limit]

    base_low, stem_low = basename.lower(), stem.lower()
    shorter_stems = set(stems[1:])
    scored: List[Tuple[int, int, int, int, int, str]] = []
    seen = set()

    candidate_paths = list(exact_suffixes)
    for r in rows:
        cand = _strip_repo_prefix(r["filepath"], repo_name)
        if cand:
            candidate_paths.append(cand)

    for clean_fp in candidate_paths:
        if not clean_fp or clean_fp in seen:
            continue
        seen.add(clean_fp)
        cand_low = clean_fp.lower()
        cand_dir = os.path.dirname(clean_fp).lower()
        cand_base = os.path.basename(clean_fp).lower()
        cand_stem = os.path.splitext(cand_base)[0]

        is_exact_suffix = 0 if (cand_low == rel_low or cand_low.endswith(f"/{rel_low}")) else 1
        trailing_hits = _trailing_segment_match_count(clean_fp, req_parts_low)
        same_dir = 0 if (req_dir and (cand_dir == req_dir or cand_dir.endswith(f"/{req_dir}"))) else 1

        if is_exact_suffix == 0:
            rank = 0
        elif cand_base == base_low:
            rank = 1
        elif cand_stem in (f"{stem_low}test", f"{stem_low}tests", f"{stem_low}_test", f"test_{stem_low}"):
            rank = 2
        elif cand_stem in shorter_stems or (len(cand_stem) >= 4 and stem_low.startswith(cand_stem)):
            rank = 3
        elif stem_low in cand_base or any(st in cand_base for st in shorter_stems):
            rank = 4
        elif same_dir == 0:
            rank = 5
        else:
            continue
        scored.append((is_exact_suffix, -trailing_hits, rank, same_dir, len(clean_fp), clean_fp))

    scored.sort(key=lambda item: (item[0], item[1], item[2], item[3], item[4], item[5]))
    return [item[5] for item in scored[:limit]]
