import os
import re
import logging
from typing import Optional, Dict, Any
from app.services.git_manager import format_git_permalink

logger = logging.getLogger("contextcortex.topology")

def _clean_filepath(fp: str) -> str:
    if "://" in fp:
        return fp.split("://", 1)[1]
    return fp

def _get_permalink(
    git_repos: Dict[str, Dict[str, Any]],
    repo: str,
    filepath: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None
) -> Optional[str]:
    g_info = git_repos.get(repo)
    if not g_info or not g_info.get("url"):
        return None
    clean_fp = _clean_filepath(filepath)
    return format_git_permalink(
        g_info["url"],
        g_info.get("commit_sha"),
        clean_fp,
        start_line,
        end_line,
        provider=g_info.get("provider")
    )

def _read_code_snippet(
    filepath: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    max_lines: int = 100
) -> Optional[str]:
    """Attempts to read source code snippet from local filesystem if accessible."""
    clean_fp = _clean_filepath(filepath)
    candidate_paths = [
        clean_fp,
        os.path.abspath(clean_fp),
        os.path.join(os.getcwd(), clean_fp),
        os.path.join(os.getcwd(), "contexthub", clean_fp),
    ]
    
    found_path = None
    for cp in candidate_paths:
        if os.path.isfile(cp):
            found_path = cp
            break
            
    if not found_path:
        return None

    try:
        with open(found_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            
        s_line = max(1, start_line or 1)
        e_line = min(len(lines), end_line or len(lines))
        
        if e_line - s_line > max_lines:
            e_line = s_line + max_lines
            
        snippet = "".join(lines[s_line - 1:e_line])
        return snippet.rstrip()
    except Exception:
        return None

