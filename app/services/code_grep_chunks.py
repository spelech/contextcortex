"""
grep_code matches from vector-store chunks.

The chunks of one file are put back together as one line map before the scan. Each context line then gets its own
file line number, and the context can continue past the edge of the chunk that holds the match.
"""
import logging
from typing import Any, Callable, Dict, Iterable, List, Optional, Pattern, Set, Tuple

logger = logging.getLogger("contextcortex.file_reader")

FileKey = Tuple[str, str]


def chunk_file_key(chunk: Dict[str, Any]) -> FileKey:
    """(repo, path in the repo) for a chunk payload, with a 'repo://' or 'repo/' prefix removed."""
    ch_repo = chunk.get("repo") or "unknown"
    raw_file = (chunk.get("rel_path") or chunk.get("path") or "").replace("\\", "/")
    ch_file = raw_file.split("://", 1)[1] if "://" in raw_file else raw_file
    if ch_file.startswith(f"{ch_repo}/"):
        ch_file = ch_file[len(ch_repo) + 1:]
    return ch_repo, ch_file


def is_summary_chunk(chunk: Dict[str, Any]) -> bool:
    """File summaries are LLM text with placeholder line numbers, so grep must not report lines from them."""
    return chunk.get("doc_type") == "summary" or bool(chunk.get("is_summary"))


def _positive_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 1 else None


def _same_line(known: str, text: str) -> bool:
    known_s, text_s = known.strip(), text.strip()
    if not text_s:
        return not known_s
    # A nested symbol chunk can start or stop in the middle of a line of its parent chunk.
    return known_s == text_s or known_s.endswith(text_s) or known_s.startswith(text_s)


def _fit_shift(line_map: Dict[int, str], blank_lines: Set[int], start: int, lines: List[str], slack: int) -> int:
    """
    Chunk text is stripped when it is indexed, so blank lines at the start or end of a chunk can be missing. `slack`
    is the number of missing lines. Use the smallest shift at which the chunk agrees with the known lines.
    """
    for shift in range(slack + 1):
        agrees = True
        for idx, text in enumerate(lines):
            line_no = start + shift + idx
            known = line_map.get(line_no, "" if line_no in blank_lines else None)
            if known is not None and not _same_line(known, text):
                agrees = False
                break
        if agrees:
            return shift
    return 0


def build_line_map(chunks: Iterable[Dict[str, Any]]) -> Dict[int, str]:
    """Maps file line numbers to text for the chunks of one file. Large chunks go first, so full lines win."""
    ordered = sorted(
        chunks,
        key=lambda c: (_positive_int(c.get("start_line")) or 0, -(_positive_int(c.get("end_line")) or 0)),
    )
    line_map: Dict[int, str] = {}
    blank_lines: Set[int] = set()
    next_line = 1
    for chunk in ordered:
        lines = (chunk.get("content") or chunk.get("text") or "").splitlines()
        if not lines:
            continue
        start = _positive_int(chunk.get("start_line")) or next_line
        end = _positive_int(chunk.get("end_line"))
        slack = max(0, end - start + 1 - len(lines)) if end and end >= start else 0
        shift = _fit_shift(line_map, blank_lines, start, lines, slack)
        # The lines that the strip removed were blank.
        blank_lines.update(range(start, start + shift))
        blank_lines.update(range(start + shift + len(lines), start + slack + len(lines)))
        start += shift
        for idx, text in enumerate(lines):
            line_map.setdefault(start + idx, text)
        next_line = max(next_line, start + len(lines))
    for line_no in blank_lines:
        line_map.setdefault(line_no, "")
    return line_map


def grep_chunk_matches(
    chunks: Iterable[Dict[str, Any]],
    compiled: Pattern[str],
    context_lines: int,
    limit: int,
    skip_files: Set[FileKey],
    seen_keys: Set[Tuple[str, str, int]],
    load_file_chunks: Optional[Callable[[str, str], List[Dict[str, Any]]]] = None,
) -> List[Dict[str, Any]]:
    """
    Returns up to `limit` matches from the files of the matched chunks. Files in `skip_files` were scanned on disk.
    `load_file_chunks(repo, file)` gives all chunks of a file; without it only the matched chunks are used.
    """
    grouped: Dict[FileKey, List[Dict[str, Any]]] = {}
    for chunk in chunks:
        if is_summary_chunk(chunk):
            continue
        key = chunk_file_key(chunk)
        if key in skip_files:
            continue
        grouped.setdefault(key, []).append(chunk)

    matches: List[Dict[str, Any]] = []
    for (ch_repo, ch_file), matched_chunks in grouped.items():
        file_chunks = matched_chunks
        if load_file_chunks is not None:
            try:
                loaded = [c for c in (load_file_chunks(ch_repo, ch_file) or []) if not is_summary_chunk(c)]
                if loaded:
                    file_chunks = loaded
            except Exception as e:
                logger.debug(f"get_file_chunks failed for {ch_repo}:{ch_file}: {e}")

        line_map = build_line_map(file_chunks)
        for line_no in sorted(line_map):
            line_str = line_map[line_no]
            if not compiled.search(line_str):
                continue
            key = (ch_repo, ch_file, line_no)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            context = [
                {"line": c_line, "text": line_map[c_line]}
                for c_line in range(line_no - context_lines, line_no + context_lines + 1)
                if c_line in line_map
            ]
            matches.append({
                "repo": ch_repo,
                "file": ch_file,
                "line": line_no,
                "match_text": line_str,
                "context": context,
            })
            if len(matches) >= limit:
                return matches
    return matches
