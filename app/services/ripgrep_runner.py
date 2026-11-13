import base64
import fnmatch
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("contextcortex.ripgrep")

_DEFAULT_TIMEOUT_SECONDS = 30


def find_ripgrep_binary() -> Optional[str]:
    """Locates the `rg` executable from env override, PATH, or frozen bundle directory."""
    env_override = os.getenv("CONTEXTCORTEX_RG_PATH")
    if env_override is not None:
        cleaned = env_override.strip()
        if cleaned.lower() in ("", "none", "disabled", "off", "false"):
            return None
        if os.path.isfile(cleaned):
            return cleaned
        found_override = shutil.which(cleaned)
        if found_override:
            return found_override
        return None

    which_rg = shutil.which("rg")
    if which_rg:
        return which_rg

    exe_name = "rg.exe" if os.name == "nt" else "rg"
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    candidates = [
        os.path.join(exe_dir, exe_name),
        os.path.join(exe_dir, "bin", exe_name),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


_GLOB_CHARS = frozenset("*?[")


def matches_path_glob(rel_path: str, path_glob: Optional[str]) -> bool:
    """Checks relative path against an fnmatch glob (with wildcards) or folder/file filter (without wildcards)."""
    if not path_glob:
        return True
    norm_path = rel_path.replace("\\", "/").strip("/")
    norm_filter = path_glob.replace("\\", "/").strip().strip("/")
    if not norm_filter:
        return True
    if _GLOB_CHARS & set(norm_filter):
        return fnmatch.fnmatch(norm_path, norm_filter) or fnmatch.fnmatch(os.path.basename(norm_path), norm_filter)
    path_l, filter_l = norm_path.lower(), norm_filter.lower()
    return (
        path_l == filter_l
        or path_l.startswith(filter_l + "/")
        or path_l.endswith("/" + filter_l)
        or f"/{filter_l}/" in f"/{path_l}/"
    )


def _normalize_rg_rel_path(raw_path: str) -> str:
    rel = (raw_path or "").replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel


def _decode_rg_data_field(obj: Optional[Dict[str, Any]]) -> str:
    if not obj:
        return ""
    if "text" in obj and obj["text"] is not None:
        return str(obj["text"]).rstrip("\r\n")
    if "bytes" in obj and obj["bytes"] is not None:
        try:
            raw = base64.b64decode(obj["bytes"])
            return raw.decode("utf-8", errors="replace").rstrip("\r\n")
        except Exception:
            return ""
    return ""


def _build_ignore_glob_args(ignored_dirs: Iterable[str]) -> List[str]:
    args: List[str] = []
    for d in sorted(set(ignored_dirs)):
        clean_d = d.strip().strip("/\\")
        if not clean_d:
            continue
        args.extend(["-g", f"!{clean_d}/**", "-g", f"!**/{clean_d}/**"])
    return args


def _build_include_glob_args(path_glob: Optional[str]) -> List[str]:
    if not path_glob:
        return []
    norm_glob = path_glob.replace("\\", "/").strip()
    if not norm_glob or norm_glob.startswith("!"):
        return []
    while norm_glob.startswith("./"):
        norm_glob = norm_glob[2:]
    norm_glob = norm_glob.strip("/")
    if not norm_glob:
        return []
    if not (_GLOB_CHARS & set(norm_glob)):
        globs = [norm_glob, f"{norm_glob}/**", f"**/{norm_glob}", f"**/{norm_glob}/**"]
        args: List[str] = []
        for g in dict.fromkeys(globs):
            args.extend(["--iglob", g])
        return args
    if "/" not in norm_glob:
        return ["-g", norm_glob]

    globs = [norm_glob]
    if norm_glob.endswith("/*"):
        globs.append(norm_glob[:-2] + "/**")
    elif "*" in norm_glob and "**" not in norm_glob:
        globs.append(norm_glob.replace("*", "**"))
    args: List[str] = []
    for g in dict.fromkeys(globs):
        args.extend(["-g", g])
    return args


def list_files_with_ripgrep(
    root_dir: str,
    ignored_dirs: Iterable[str],
    include_hidden: bool = False,
    extensions: Optional[Tuple[str, ...]] = None,
) -> Optional[List[Tuple[str, str]]]:
    """Lists files under `root_dir` via `rg --files`. Returns None if `rg` is unavailable or errors."""
    rg_bin = find_ripgrep_binary()
    if not rg_bin or not os.path.isdir(root_dir):
        return None

    cmd = [rg_bin, "--files", "--no-config", "--no-ignore"]
    if include_hidden:
        cmd.append("--hidden")
    cmd.extend(_build_ignore_glob_args(ignored_dirs))
    cmd.append(".")

    try:
        proc = subprocess.run(
            cmd,
            cwd=root_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_DEFAULT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug(f"ripgrep --files fallback triggered for {root_dir}: {exc}")
        return None

    if proc.returncode not in (0, 1):
        logger.debug(f"ripgrep --files exited {proc.returncode} for {root_dir}: {proc.stderr.strip()}")
        return None

    exts_lower = tuple(e.lower() for e in extensions) if extensions else None
    results: List[Tuple[str, str]] = []
    for raw_line in proc.stdout.splitlines():
        rel_p = _normalize_rg_rel_path(raw_line.strip())
        if not rel_p:
            continue
        if exts_lower and not rel_p.lower().endswith(exts_lower):
            continue
        abs_p = os.path.abspath(os.path.join(root_dir, rel_p))
        results.append((abs_p, rel_p))
    return results


def _flush_file_matches(
    repo_name: str,
    rel_path: str,
    abs_path: str,
    match_lines: List[Tuple[int, str]],
    context_map: Dict[int, str],
    context_lines: int,
    max_remaining: int,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for line_no, match_text in match_lines:
        if len(out) >= max_remaining:
            break
        start_c = max(1, line_no - context_lines)
        end_c = line_no + context_lines
        ctx_items = [
            {"line": ln, "text": context_map[ln]}
            for ln in range(start_c, end_c + 1)
            if ln in context_map
        ]
        if not ctx_items:
            ctx_items = [{"line": line_no, "text": match_text}]
        out.append({
            "repo": repo_name,
            "file": rel_path,
            "abs_path": abs_path,
            "line": line_no,
            "match_text": match_text,
            "context": ctx_items,
        })
    return out


def _run_rg_json_stream(
    cmd: List[str],
    cwd: str,
    repo_name: str,
    path_glob: Optional[str],
    context_lines: int,
    max_matches: int,
) -> Tuple[Optional[List[Dict[str, Any]]], int, str]:
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    matches: List[Dict[str, Any]] = []
    cur_rel: Optional[str] = None
    cur_abs: Optional[str] = None
    cur_skip = False
    cur_ctx: Dict[int, str] = {}
    cur_hits: List[Tuple[int, str]] = []
    stopped_early = False

    def _flush_current() -> None:
        nonlocal cur_rel, cur_abs, cur_skip, cur_ctx, cur_hits
        if cur_rel and cur_abs and not cur_skip and cur_hits and len(matches) < max_matches:
            rem = max_matches - len(matches)
            matches.extend(
                _flush_file_matches(repo_name, cur_rel, cur_abs, cur_hits, cur_ctx, context_lines, rem)
            )
        cur_rel = None
        cur_abs = None
        cur_skip = False
        cur_ctx = {}
        cur_hits = []

    try:
        assert proc.stdout is not None
        for raw_bytes in proc.stdout:
            line_str = raw_bytes.decode("utf-8", errors="replace").strip()
            if not line_str:
                continue
            try:
                evt = json.loads(line_str)
            except json.JSONDecodeError:
                continue

            etype = evt.get("type")
            data = evt.get("data") or {}
            if etype == "begin":
                _flush_current()
                raw_rel = _decode_rg_data_field(data.get("path"))
                norm_rel = _normalize_rg_rel_path(raw_rel)
                cur_rel = norm_rel
                cur_abs = os.path.abspath(os.path.join(cwd, norm_rel))
                cur_skip = not matches_path_glob(norm_rel, path_glob)
            elif etype in ("context", "match"):
                if cur_skip or not cur_rel:
                    continue
                lnum = int(data.get("line_number") or 0)
                if lnum <= 0:
                    continue
                ltext = _decode_rg_data_field(data.get("lines"))
                cur_ctx[lnum] = ltext
                if etype == "match":
                    cur_hits.append((lnum, ltext))
                elif (
                    len(matches) + len(cur_hits) >= max_matches
                    and cur_hits
                    and lnum >= cur_hits[max_matches - len(matches) - 1][0] + context_lines
                ):
                    _flush_current()
                    stopped_early = True
                    break
            elif etype == "end":
                _flush_current()
                if len(matches) >= max_matches:
                    stopped_early = True
                    break
        _flush_current()
    finally:
        if stopped_early and proc.poll() is None:
            proc.terminate()
        stderr_text = ""
        try:
            if proc.stderr is not None and not stopped_early:
                stderr_text = proc.stderr.read().decode("utf-8", errors="replace").strip()
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
            proc.wait(timeout=2)

    if stopped_early:
        return matches[:max_matches], 0, ""
    return matches[:max_matches], int(proc.returncode or 0), stderr_text


def search_files_with_ripgrep(
    root_dir: str,
    repo_name: str,
    pattern: str,
    ignored_dirs: Iterable[str],
    path_glob: Optional[str] = None,
    is_regex: bool = False,
    case_sensitive: bool = False,
    context_lines: int = 2,
    max_matches: int = 30,
    include_hidden: bool = True,
) -> Optional[List[Dict[str, Any]]]:
    """Searches `root_dir` via `rg --json`. Returns None if `rg` is missing or errors."""
    rg_bin = find_ripgrep_binary()
    if not rg_bin:
        return None

    is_single_file = os.path.isfile(root_dir)
    if not is_single_file and not os.path.isdir(root_dir):
        return []

    cwd = os.path.dirname(os.path.abspath(root_dir)) if is_single_file else os.path.abspath(root_dir)
    target = os.path.basename(os.path.abspath(root_dir)) if is_single_file else "."

    def _build_cmd(use_pcre2: bool) -> List[str]:
        cmd = [rg_bin, "--json", "--no-config", "--no-ignore"]
        if include_hidden:
            cmd.append("--hidden")
        cmd.append("-s" if case_sensitive else "-i")
        if not is_regex:
            cmd.append("-F")
        if use_pcre2:
            cmd.append("--pcre2")
        if context_lines > 0:
            cmd.extend(["-C", str(context_lines)])
        if not is_single_file:
            cmd.extend(_build_include_glob_args(path_glob))
            cmd.extend(_build_ignore_glob_args(ignored_dirs))
        cmd.extend(["--", pattern, target])
        return cmd

    try:
        hits, rc, err = _run_rg_json_stream(
            _build_cmd(use_pcre2=False),
            cwd=cwd,
            repo_name=repo_name,
            path_glob=path_glob,
            context_lines=context_lines,
            max_matches=max_matches,
        )
        if rc == 2 and is_regex:
            hits, rc, err = _run_rg_json_stream(
                _build_cmd(use_pcre2=True),
                cwd=cwd,
                repo_name=repo_name,
                path_glob=path_glob,
                context_lines=context_lines,
                max_matches=max_matches,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug(f"ripgrep search fallback triggered for {root_dir}: {exc}")
        return None

    if rc not in (0, 1):
        logger.debug(f"ripgrep exited {rc} for {root_dir}: {err}")
        return None
    return hits or []


def search_tokens_with_ripgrep(
    root_dir: str,
    tokens: List[str],
    ignored_dirs: Iterable[str],
    extensions: Optional[Tuple[str, ...]] = None,
    max_per_file: int = 25,
    max_files: int = 80,
) -> Optional[Dict[str, List[Tuple[int, str]]]]:
    """Multi-token `rg --json` scan returning `{rel_path: [(line_no, line_text), ...]}`."""
    rg_bin = find_ripgrep_binary()
    clean_tokens = [t for t in dict.fromkeys(tokens) if t]
    if not rg_bin or not clean_tokens or not os.path.isdir(root_dir):
        return None

    pattern = "(?:" + "|".join(re.escape(t) for t in clean_tokens) + ")"
    cmd = [
        rg_bin, "--json", "--no-config", "--no-ignore", "--hidden",
        "-i", "--max-count", str(max_per_file),
    ]
    if extensions:
        for ext in sorted(set(extensions)):
            cmd.extend(["-g", f"*{ext}"])
    cmd.extend(_build_ignore_glob_args(ignored_dirs))
    cmd.extend(["--", pattern, "."])

    try:
        proc = subprocess.Popen(cmd, cwd=root_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        return None

    by_file: Dict[str, List[Tuple[int, str]]] = {}
    cur_rel: Optional[str] = None
    stopped_early = False
    try:
        assert proc.stdout is not None
        for raw_bytes in proc.stdout:
            line_str = raw_bytes.decode("utf-8", errors="replace").strip()
            if not line_str:
                continue
            try:
                evt = json.loads(line_str)
            except json.JSONDecodeError:
                continue
            etype = evt.get("type")
            data = evt.get("data") or {}
            if etype == "begin":
                cur_rel = _normalize_rg_rel_path(_decode_rg_data_field(data.get("path")))
            elif etype == "match" and cur_rel:
                lnum = int(data.get("line_number") or 0)
                if lnum > 0:
                    by_file.setdefault(cur_rel, []).append((lnum, _decode_rg_data_field(data.get("lines"))))
            elif etype == "end":
                cur_rel = None
                if len(by_file) >= max_files:
                    stopped_early = True
                    break
    finally:
        if stopped_early and proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
            proc.wait(timeout=2)

    if not stopped_early and proc.returncode not in (0, 1):
        return None
    return by_file
