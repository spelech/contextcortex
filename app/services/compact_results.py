"""
Compact result shapes for the `grep_code` and `read_file` MCP tools.

The output follows ripgrep: the file path is given once per file, and each line is one string, `<line>:<text>` for a
match line and `<line>-<text>` for a context line. A `--` string separates blocks that are not next to each other.
Fields that are null, empty, or the same for each match are not repeated.
"""

from typing import Any, Dict, Iterable, List, Optional, Tuple

BLOCK_SEPARATOR = "--"


def _permalink_base(permalink: Optional[str]) -> Optional[str]:
    if not permalink:
        return None
    return permalink.split("#", 1)[0]


def _file_lines(matches: List[Dict[str, Any]], block_separators: bool) -> List[str]:
    """ripgrep-style lines for the matches of one file: context lines merge, and gaps get a `--` separator."""
    by_line: Dict[int, Tuple[str, bool]] = {}
    for match in matches:
        for item in match.get("context") or []:
            number = item.get("line")
            if isinstance(number, int) and number not in by_line:
                by_line[number] = (item.get("text") or "", False)
        by_line[match["line"]] = (match.get("match_text") or "", True)
    lines: List[str] = []
    previous: Optional[int] = None
    for number in sorted(by_line):
        if block_separators and previous is not None and number > previous + 1:
            lines.append(BLOCK_SEPARATOR)
        text, is_match = by_line[number]
        lines.append(f"{number}{':' if is_match else '-'}{text}")
        previous = number
    return lines


def group_grep_matches(
    matches: Iterable[Dict[str, Any]],
    block_separators: bool = True,
    include_permalinks: bool = False,
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """
    Groups grep matches by (repo, file) in first-seen order. Returns the repo that all groups share (or None) and the
    file groups. A group has `file`, `repo` (only when the repos are different), `lines`, and, when known,
    `symbols` ({line: enclosing symbol}) and `permalink` (the file permalink when include_permalinks=True; add `#L<line>`).
    Set block_separators=False when there are no context lines (ripgrep writes no `--` then).
    """
    groups: Dict[Tuple[Any, Any], List[Dict[str, Any]]] = {}
    for match in matches:
        groups.setdefault((match.get("repo"), match.get("file")), []).append(match)
    repos = {repo for repo, _file in groups}
    shared_repo = next(iter(repos)) if len(repos) == 1 else None

    files: List[Dict[str, Any]] = []
    for (repo, file_path), file_matches in groups.items():
        group: Dict[str, Any] = {"file": file_path}
        if shared_repo is None and repo:
            group["repo"] = repo
        if include_permalinks:
            permalink = next((_permalink_base(m.get("permalink")) for m in file_matches if m.get("permalink")), None)
            if permalink:
                group["permalink"] = permalink
        symbols = {str(m["line"]): m["symbol"] for m in file_matches if m.get("symbol")}
        if symbols:
            group["symbols"] = symbols
        group["lines"] = _file_lines(file_matches, block_separators)
        files.append(group)
    return shared_repo, files


def number_lines(content: str, start_line: int) -> str:
    """The text with `<line>:` before each line, as `grep -n` writes it."""
    if not content:
        return ""
    return "\n".join(f"{start_line + i}:{line}" for i, line in enumerate(content.split("\n")))


__all__ = ["BLOCK_SEPARATOR", "group_grep_matches", "number_lines"]
