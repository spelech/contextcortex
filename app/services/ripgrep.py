import subprocess
import shutil
import json
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("contextcortex.ripgrep")


def is_ripgrep_available() -> bool:
    """Checks whether 'rg' binary is available in PATH."""
    return shutil.which("rg") is not None


def run_ripgrep_search(
    query: str,
    target_paths: List[str],
    case_sensitive: bool = False,
    max_results: int = 50,
    globs: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Executes fast line-level search across target paths using ripgrep JSON output."""
    if not is_ripgrep_available():
        logger.debug("ripgrep not available in environment.")
        return []

    q = query.strip()
    if not q or not target_paths:
        return []

    valid_paths = [p for p in target_paths if p]
    if not valid_paths:
        return []

    cmd = ["rg", "--json"]
    if not case_sensitive:
        cmd.append("-i")
    cmd.extend(["-m", str(max_results)])

    if globs:
        for g in globs:
            if g.strip():
                cmd.extend(["-g", g.strip()])

    cmd.extend(["-e", q, "--"])
    cmd.extend(valid_paths)

    results: List[Dict[str, Any]] = []
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("type") == "match":
                    payload = data.get("data", {})
                    path_data = payload.get("path", {})
                    file_path = path_data.get("text", "")
                    lines_data = payload.get("lines", {})
                    line_text = lines_data.get("text", "").rstrip("\r\n")
                    line_num = payload.get("line_number", 1)
                    submatches = payload.get("submatches", [])
                    col_start = submatches[0].get("start", 0) if submatches else 0

                    results.append({
                        "filepath": file_path,
                        "line_number": line_num,
                        "column": col_start + 1,
                        "content": line_text,
                    })
                    if len(results) >= max_results:
                        break
            except json.JSONDecodeError:
                continue
    except subprocess.TimeoutExpired:
        logger.warning(f"ripgrep search timed out for query: '{q}'")
    except Exception as e:
        logger.warning(f"ripgrep execution error: {e}")

    return results
