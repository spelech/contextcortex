import os
import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from app.models.schemas import CodeChunk, CodeRelationship, CodeSymbol, ExtractionResult
from app.services.chunking.text_chunker import split_by_length
from app.services.chunking.tree_sitter_loader import get_tree_sitter_parser

_COBOL_RESERVED_PARAGRAPH_WORDS = frozenset({
    "ACCEPT", "ADD", "ALTER", "CALL", "CANCEL", "CLOSE", "COMPUTE", "CONTINUE", "DECLARATIVES",
    "DELETE", "DISPLAY", "DIVIDE", "ELSE", "END", "END-ACCEPT", "END-ADD", "END-CALL",
    "END-COMPUTE", "END-DELETE", "END-DISPLAY", "END-DIVIDE", "END-EVALUATE", "END-EXEC",
    "END-IF", "END-INVOKE", "END-MULTIPLY", "END-PERFORM", "END-READ", "END-RETURN",
    "END-REWRITE", "END-SEARCH", "END-START", "END-STRING", "END-SUBTRACT", "END-UNSTRING",
    "END-WRITE", "END-XML", "ENTRY", "EVALUATE", "EXEC", "EXIT", "GO", "GOBACK", "IF",
    "INITIALIZE", "INSPECT", "INVOKE", "MERGE", "MOVE", "MULTIPLY", "NEXT", "OPEN", "PERFORM",
    "READ", "RELEASE", "RETURN", "REWRITE", "SEARCH", "SET", "SORT", "START", "STOP", "STRING",
    "SUBTRACT", "THEN", "UNSTRING", "USE", "WHEN", "WRITE", "XML",
})
_PERFORM_INLINE_KEYWORDS = frozenset({
    "UNTIL", "VARYING", "WITH", "TEST", "TIMES", "FOREVER", "AFTER", "END-PERFORM",
})

_DIVISION_RE = re.compile(r"^\s*(IDENTIFICATION|ID|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b", re.I)
_PROGRAM_ID_RE = re.compile(r"^\s*PROGRAM-ID\s*\.?\s*['\"]?([A-Za-z0-9][A-Za-z0-9_-]*)['\"]?", re.I)
_END_PROGRAM_RE = re.compile(r"^\s*END\s+PROGRAM\s+['\"]?([A-Za-z0-9][A-Za-z0-9_-]*)['\"]?", re.I)
_SECTION_HEADER_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9_-]*)\s+SECTION\s*\.", re.I)
_PARAGRAPH_HEADER_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_-]*)\s*\.\s*$")
_DATA_LEVEL_RE = re.compile(r"^\s*(\d{1,2})\s+([A-Za-z0-9][A-Za-z0-9_-]*)?\b(.*)$", re.I)
_VALUE_LITERAL_RE = re.compile(r"\bVALUE\s+(?:IS\s+)?['\"]([A-Za-z0-9_-]+)['\"]", re.I)
_COPY_STMT_RE = re.compile(r"\bCOPY\s+(?:['\"]([^'\"]+)['\"]|([A-Za-z0-9_./\\-]+))", re.I)
_SQL_INCLUDE_RE = re.compile(r"EXEC\s+SQL\s+INCLUDE\s+(?:['\"]([^'\"]+)['\"]|([A-Za-z0-9_./\\-]+))", re.I)
_CICS_XFER_RE = re.compile(
    r"EXEC\s+CICS\s+(?:LINK|XCTL)\b[\s\S]*?\bPROGRAM\s*\(\s*(?:['\"]([^'\"]+)['\"]|([A-Za-z0-9_-]+))\s*\)", re.I
)
_CALL_STMT_RE = re.compile(r"\bCALL\s+(?:['\"]([^'\"]+)['\"]|([A-Za-z0-9][A-Za-z0-9_-]*))", re.I)
_PERFORM_STMT_RE = re.compile(
    r"\bPERFORM\s+([A-Za-z0-9][A-Za-z0-9_-]*)(?:\s+(?:THRU|THROUGH)\s+([A-Za-z0-9][A-Za-z0-9_-]*))?", re.I
)
_NEW_STMT_START_RE = re.compile(
    r"^(?:PERFORM|CALL|COPY|EXEC|MOVE|IF|ELSE|END-[A-Z0-9-]+|EVALUATE|WHEN|COMPUTE|ADD|SUBTRACT|"
    r"MULTIPLY|DIVIDE|READ|WRITE|REWRITE|DELETE|OPEN|CLOSE|DISPLAY|ACCEPT|INITIALIZE|STRING|"
    r"UNSTRING|INSPECT|SEARCH|SET|GO|GOBACK|STOP|EXIT|CONTINUE)\b", re.I
)


def _strip_inline_comment(text: str) -> str:
    in_quote: Optional[str] = None
    for idx in range(len(text) - 1):
        ch = text[idx]
        if in_quote:
            if ch == in_quote:
                in_quote = None
        elif ch in ("'", '"'):
            in_quote = ch
        elif ch == "*" and text[idx + 1] == ">":
            return text[:idx].rstrip()
    return text.rstrip()


def _detect_fixed_format(lines: List[str]) -> bool:
    fixed_votes, free_votes = 0, 0
    for raw in lines[:200]:
        expanded = raw.expandtabs(4)
        stripped = expanded.strip()
        if not stripped:
            continue
        upper_s = stripped.upper()
        if ">>SOURCE" in upper_s and "FORMAT" in upper_s:
            return "FREE" not in upper_s
        if len(expanded) >= 7 and expanded[:6].isdigit() and expanded[6] in (" ", "*", "/", "-", "D", "d"):
            fixed_votes += 2
        elif len(expanded) >= 7 and expanded[:6] == "      " and expanded[6] in ("*", "/", "-"):
            fixed_votes += 2
        elif expanded[:6].strip():
            free_votes += 2
        elif len(expanded) >= 7 and expanded[:6] == "      " and expanded[6] == " ":
            fixed_votes += 1
    return fixed_votes > free_votes


def _clean_cobol_lines(lines: List[str]) -> Tuple[List[Dict[str, Any]], bool]:
    is_fixed = _detect_fixed_format(lines)
    has_seq_nums = any(len(l) >= 7 and l[:6].isdigit() for l in lines[:100])
    right_tags = [
        l[72:80].strip() for l in lines[:100]
        if len(l) >= 73 and l[:6] == "      " and l[71:72] == " " and l[72:80].strip()
    ]
    strip_col73 = has_seq_nums or (len(right_tags) >= 3 and len(set(right_tags)) <= 2)

    cleaned: List[Dict[str, Any]] = []
    current_fixed = is_fixed
    for line_no, raw in enumerate(lines, start=1):
        expanded = raw.rstrip("\r\n")
        upper_trim = expanded.strip().upper()
        if ">>SOURCE" in upper_trim and "FORMAT" in upper_trim:
            current_fixed = "FREE" not in upper_trim
            cleaned.append({"line": line_no, "text": "", "is_comment": True, "area_a": False})
            continue
        if current_fixed:
            if len(expanded) < 7 or expanded[6] in ("*", "/"):
                is_cmt = len(expanded) >= 7 or expanded.lstrip().startswith("*") or not expanded.strip()
                cleaned.append({"line": line_no, "text": "", "is_comment": is_cmt, "area_a": False})
                continue
            code_area = expanded[7:72] if (expanded[:6].isdigit() or strip_col73) else expanded[7:]
            code_area = _strip_inline_comment(code_area)
            if not code_area.strip():
                cleaned.append({"line": line_no, "text": "", "is_comment": False, "area_a": False})
                continue
            in_area_a = (len(code_area) - len(code_area.lstrip(" "))) <= 3
            cleaned.append({"line": line_no, "text": code_area.strip(), "is_comment": False, "area_a": in_area_a})
        else:
            s = expanded.lstrip()
            if not s or s.startswith("*>") or s.startswith("*"):
                cleaned.append({"line": line_no, "text": "", "is_comment": bool(s), "area_a": False})
                continue
            cleaned.append({"line": line_no, "text": _strip_inline_comment(s).strip(), "is_comment": False, "area_a": True})
    return cleaned, is_fixed


def _normalize_copybook_target(raw_name: str) -> str:
    base = os.path.basename(raw_name.strip().strip("'\".,;").replace("\\", "/"))
    stem, ext = os.path.splitext(base)
    return stem.upper() if ext.upper() in (".CPY", ".COB", ".CBL", ".COPY", ".INC", ".SQL") else base.upper()


def _parse_tree_sitter_cobol_hints(
    line_infos: List[Dict[str, Any]], has_program_header: bool, parser_getter: Callable[[str], Any]
) -> Dict[str, Set[int]]:
    hints: Dict[str, Set[int]] = {"paragraphs": set(), "sections": set(), "records": set()}
    parser = parser_getter("cobol")
    if not parser:
        return hints

    norm_lines: List[str] = []
    line_offset = 0
    if not has_program_header:
        norm_lines.extend([
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. COPYBOOK-AST.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
        ])
        line_offset = 4

    in_exec = False
    for info in line_infos:
        txt = info["text"]
        if not txt or info["is_comment"]:
            norm_lines.append("      *")
            continue
        upper_t = txt.upper()
        if re.search(r"\bEXEC\s+(?:SQL|CICS)\b", upper_t):
            in_exec = "END-EXEC" not in upper_t
            norm_lines.append("      * EXEC")
            continue
        if in_exec:
            if "END-EXEC" in upper_t:
                in_exec = False
            norm_lines.append("      * EXEC")
            continue
        norm_lines.append(f"{'       ' if info['area_a'] else '           '}{txt[:65]}")

    try:
        source_bytes = ("\n".join(norm_lines) + "\n").encode("utf-8")
        tree = parser.parse(source_bytes)
    except Exception:
        return hints

    def walk(node):
        orig_line = node.start_point[0] + 1 - line_offset
        if orig_line >= 1:
            if node.type == "paragraph_header":
                hints["paragraphs"].add(orig_line)
            elif node.type == "section_header":
                hints["sections"].add(orig_line)
            elif node.type == "data_description":
                for child in node.children:
                    if child.type == "level_number":
                        lvl = source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore").strip()
                        if lvl in ("1", "01"):
                            hints["records"].add(orig_line)
                        break
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return hints


def _last_code_line_in_range(line_infos: List[Dict[str, Any]], start_l: int, max_end_l: int) -> int:
    for idx in range(min(max_end_l, len(line_infos)) - 1, start_l - 1, -1):
        if line_infos[idx]["text"] and not line_infos[idx]["is_comment"]:
            return idx + 1
    return start_l


def extract_cobol_symbols_and_chunks(
    code: str,
    filepath: str,
    repo: str = "default",
    max_chunk_chars: int = 1500,
    parser_getter: Callable[[str], Any] = get_tree_sitter_parser,
) -> ExtractionResult:
    """Extracts COBOL AST symbols, chunks, outlines, and cross-file relationships."""
    lines = code.splitlines()
    total_lines = len(lines)
    clean_fp = (filepath.split("://", 1)[1] if "://" in filepath else filepath).replace("\\", "/")
    file_symbol = os.path.basename(clean_fp)
    if total_lines == 0:
        return ExtractionResult(chunks=[], symbols=[], outline=[], relationships=[], api_routes=[], api_client_calls=[])

    line_infos, is_fixed = _clean_cobol_lines(lines)
    has_program_header = any(
        _DIVISION_RE.match(li["text"]) or _PROGRAM_ID_RE.match(li["text"]) for li in line_infos if li["text"]
    )
    ts_hints = _parse_tree_sitter_cobol_hints(line_infos, has_program_header, parser_getter)

    programs: List[Dict[str, Any]] = []
    sections: List[Dict[str, Any]] = []
    paragraphs: List[Dict[str, Any]] = []
    records: List[Dict[str, Any]] = []
    ws_values: Dict[str, str] = {}

    current_division: Optional[str] = "DATA" if not has_program_header else None
    current_prog: Optional[Dict[str, Any]] = None
    pending_id_div_line: Optional[int] = None

    for info in line_infos:
        txt, ln = info["text"], info["line"]
        if not txt or info["is_comment"]:
            continue

        m_div = _DIVISION_RE.match(txt)
        if m_div:
            div_kw = m_div.group(1).upper()
            current_division = "IDENTIFICATION" if div_kw == "ID" else div_kw
            if current_division == "IDENTIFICATION":
                if current_prog and current_prog["end_line"] is None:
                    current_prog["end_line"] = _last_code_line_in_range(line_infos, current_prog["start_line"], ln - 1)
                pending_id_div_line = ln
            continue

        if _END_PROGRAM_RE.match(txt):
            if current_prog and current_prog["end_line"] is None:
                current_prog["end_line"] = ln
            current_prog, current_division, pending_id_div_line = None, None, None
            continue

        m_prog = _PROGRAM_ID_RE.match(txt)
        if m_prog:
            prog_name = m_prog.group(1).upper()
            current_prog = {
                "name": prog_name, "full_symbol": prog_name, "kind": "program_definition",
                "start_line": pending_id_div_line or ln, "id_line": ln, "end_line": None,
                "signature": lines[ln - 1].strip()[:120],
            }
            programs.append(current_prog)
            pending_id_div_line = None
            continue

        prog_prefix = current_prog["name"] if current_prog else None
        if current_division in ("DATA", None):
            m_lvl = _DATA_LEVEL_RE.match(txt)
            if m_lvl:
                lvl = int(m_lvl.group(1))
                entry_name = (m_lvl.group(2) or "").upper()
                rest = m_lvl.group(3) or ""
                if entry_name and entry_name != "FILLER":
                    m_val = _VALUE_LITERAL_RE.search(rest)
                    if m_val:
                        ws_values[entry_name] = m_val.group(1).upper()
                if lvl == 1 or ln in ts_hints["records"]:
                    if entry_name and entry_name != "FILLER":
                        records.append({
                            "name": entry_name, "prog": prog_prefix, "kind": "record_definition",
                            "start_line": ln, "end_line": None, "signature": lines[ln - 1].strip()[:120],
                        })
                    elif records and records[-1]["end_line"] is None:
                        records[-1]["end_line"] = _last_code_line_in_range(line_infos, records[-1]["start_line"], ln - 1)
                elif lvl in (66, 77) and records and records[-1]["end_line"] is None:
                    records[-1]["end_line"] = _last_code_line_in_range(line_infos, records[-1]["start_line"], ln - 1)
            elif _SECTION_HEADER_RE.match(txt) and records and records[-1]["end_line"] is None:
                records[-1]["end_line"] = _last_code_line_in_range(line_infos, records[-1]["start_line"], ln - 1)

        if current_division == "PROCEDURE":
            if records and records[-1]["end_line"] is None:
                records[-1]["end_line"] = _last_code_line_in_range(line_infos, records[-1]["start_line"], ln - 1)
            m_sec = _SECTION_HEADER_RE.match(txt)
            if m_sec:
                sec_name = m_sec.group(1).upper()
                sections.append({
                    "name": sec_name, "full_symbol": f"{prog_prefix}.{sec_name}" if prog_prefix else sec_name,
                    "prog": prog_prefix, "kind": "section", "start_line": ln, "end_line": None,
                    "signature": lines[ln - 1].strip()[:120],
                })
                continue
            m_para = _PARAGRAPH_HEADER_RE.match(txt)
            if m_para and (info["area_a"] or not is_fixed or ln in ts_hints["paragraphs"]):
                cand_name = m_para.group(1).upper()
                if cand_name not in _COBOL_RESERVED_PARAGRAPH_WORDS and not cand_name.isdigit():
                    paragraphs.append({
                        "name": cand_name, "full_symbol": f"{prog_prefix}.{cand_name}" if prog_prefix else cand_name,
                        "prog": prog_prefix, "kind": "paragraph", "start_line": ln, "end_line": None,
                        "signature": lines[ln - 1].strip()[:120],
                    })

    copybook_sym: Optional[Dict[str, Any]] = None
    if not programs:
        cpy_stem = os.path.splitext(file_symbol)[0].upper()
        first_sig = next((lines[li["line"] - 1].strip()[:120] for li in line_infos if li["text"]), f"COPYBOOK {cpy_stem}")
        copybook_sym = {
            "name": cpy_stem, "full_symbol": cpy_stem, "kind": "copybook",
            "start_line": 1, "end_line": total_lines, "signature": first_sig,
        }
        for rec in records:
            rec["prog"] = cpy_stem

    for idx, p in enumerate(programs):
        if p["end_line"] is None:
            bound = programs[idx + 1]["start_line"] - 1 if idx + 1 < len(programs) else total_lines
            p["end_line"] = _last_code_line_in_range(line_infos, p["start_line"], bound)

    proc_div_lines = [
        li["line"] for li in line_infos
        if li["text"] and _DIVISION_RE.match(li["text"]) and _DIVISION_RE.match(li["text"]).group(1).upper() == "PROCEDURE"
    ]
    for idx, rec in enumerate(records):
        rec["full_symbol"] = f"{rec['prog']}.{rec['name']}" if rec.get("prog") else rec["name"]
        if rec["end_line"] is None:
            next_rec_l = records[idx + 1]["start_line"] - 1 if idx + 1 < len(records) else total_lines
            proc_after = [pl - 1 for pl in proc_div_lines if pl > rec["start_line"]]
            prog_end = next((p["end_line"] for p in programs if p["name"] == rec.get("prog")), total_lines)
            rec["end_line"] = _last_code_line_in_range(line_infos, rec["start_line"], min([next_rec_l, prog_end] + proc_after))

    for idx, sec in enumerate(sections):
        next_sec_l = sections[idx + 1]["start_line"] - 1 if idx + 1 < len(sections) else total_lines
        prog_end = next((p["end_line"] for p in programs if p["name"] == sec.get("prog")), total_lines)
        sec["end_line"] = _last_code_line_in_range(line_infos, sec["start_line"], min(next_sec_l, prog_end))

    boundary_starts = sorted({s["start_line"] for s in sections} | {p["start_line"] for p in paragraphs} | {p["end_line"] + 1 for p in programs})
    for para in paragraphs:
        higher_bounds = [b - 1 for b in boundary_starts if b > para["start_line"]]
        para["end_line"] = _last_code_line_in_range(line_infos, para["start_line"], min(higher_bounds) if higher_bounds else total_lines)

    ordered_containers = ([copybook_sym] if copybook_sym else []) + programs + records + sections + paragraphs
    ordered_containers.sort(key=lambda item: (item["start_line"], -(item["end_line"] - item["start_line"])))

    symbols_raw, outline_items, chunks_raw = [], [], []
    for item in ordered_containers:
        s_line, e_line = item["start_line"], max(item["start_line"], item["end_line"])
        full_sym, kind = item["full_symbol"], item["kind"]
        node_text = "\n".join(lines[s_line - 1:e_line])
        symbols_raw.append({
            "name": item["name"], "full_symbol": full_sym, "kind": kind,
            "start_line": s_line, "end_line": e_line, "signature": item["signature"],
            "filepath": filepath, "repo": repo, "language": "cobol",
        })
        outline_items.append({"name": full_sym if "." in full_sym else item["name"], "kind": kind, "start_line": s_line, "end_line": e_line})
        if len(node_text) <= max_chunk_chars:
            chunks_raw.append({"symbol": full_sym, "kind": kind, "heading": f"{full_sym} ({kind})", "content": node_text, "start_line": s_line, "end_line": e_line})
        else:
            for sc in split_by_length(node_text, heading=f"{full_sym} ({kind})", max_chars=max_chunk_chars):
                sc.update({"symbol": full_sym, "kind": kind, "start_line": s_line + sc.get("start_line", 1) - 1, "end_line": s_line + sc.get("end_line", e_line - s_line + 1) - 1})
                chunks_raw.append(sc)

    def _enclosing_source_name(ln: int) -> str:
        for group in (paragraphs, sections, programs):
            matches = [g for g in group if g["start_line"] <= ln <= g["end_line"]]
            if matches:
                best = min(matches, key=lambda g: g["end_line"] - g["start_line"])
                return best.get("full_symbol") or best["name"]
        return copybook_sym["name"] if copybook_sym else file_symbol

    header_lines = {p["id_line"] for p in programs} | {s["start_line"] for s in sections} | {p["start_line"] for p in paragraphs} | {r["start_line"] for r in records}
    statements: List[Tuple[int, str]] = []
    buf_lines: List[str] = []
    buf_start, in_exec_stmt = 1, False
    for info in line_infos:
        txt = info["text"]
        if not txt or info["is_comment"]:
            continue
        upper_t = txt.upper()
        if not in_exec_stmt and buf_lines and (info["line"] in header_lines or _NEW_STMT_START_RE.match(txt)):
            statements.append((buf_start, " ".join(buf_lines)))
            buf_lines = []
        if not buf_lines:
            buf_start = info["line"]
        buf_lines.append(txt)
        if re.search(r"\bEXEC\s+(?:SQL|CICS)\b", upper_t) and "END-EXEC" not in upper_t:
            in_exec_stmt = True
        elif in_exec_stmt:
            if "END-EXEC" in upper_t:
                in_exec_stmt = False
                statements.append((buf_start, " ".join(buf_lines)))
                buf_lines = []
        elif txt.endswith(".") or len(buf_lines) >= 6:
            statements.append((buf_start, " ".join(buf_lines)))
            buf_lines = []
    if buf_lines:
        statements.append((buf_start, " ".join(buf_lines)))

    relationships_raw: List[Dict[str, Any]] = []
    def _add_rel(src: str, tgt: str, rtype: str, ln: int) -> None:
        relationships_raw.append({"repo": repo, "source_filepath": filepath, "source_symbol": src, "target_symbol": tgt, "relationship_type": rtype, "line_number": ln})

    for stmt_line, stmt_text in statements:
        src_sym = _enclosing_source_name(stmt_line)
        for rx in (_COPY_STMT_RE, _SQL_INCLUDE_RE):
            for m_inc in rx.finditer(stmt_text):
                raw_t = m_inc.group(1) or m_inc.group(2)
                if raw_t:
                    _add_rel(src_sym, _normalize_copybook_target(raw_t), "IMPORTS", stmt_line)
        for m_cics in _CICS_XFER_RE.finditer(stmt_text):
            raw_p = (m_cics.group(1) or m_cics.group(2) or "").strip().upper()
            if raw_p:
                _add_rel(src_sym, raw_p, "CALLS", stmt_line)
                if m_cics.group(2) and raw_p in ws_values:
                    _add_rel(src_sym, ws_values[raw_p], "CALLS", stmt_line)
        if not re.search(r"\bEXEC\s+CICS\b", stmt_text, re.I):
            for m_call in _CALL_STMT_RE.finditer(stmt_text):
                target_p = (m_call.group(1) or m_call.group(2) or "").strip().upper()
                if target_p and target_p not in ("PROGRAM", "USING", "ON", "EXCEPTION"):
                    _add_rel(src_sym, target_p, "CALLS", stmt_line)
                    if m_call.group(2) and target_p in ws_values:
                        _add_rel(src_sym, ws_values[target_p], "CALLS", stmt_line)
            for m_perf in _PERFORM_STMT_RE.finditer(stmt_text):
                p1, p2 = m_perf.group(1).upper(), (m_perf.group(2).upper() if m_perf.group(2) else None)
                if p1 not in _PERFORM_INLINE_KEYWORDS and not p1.isdigit():
                    _add_rel(src_sym, p1, "CALLS", stmt_line)
                    if p2 and p2 not in _PERFORM_INLINE_KEYWORDS and not p2.isdigit():
                        _add_rel(src_sym, p2, "CALLS", stmt_line)

    seen_rels: Set[Tuple[str, str, str, str, str, int]] = set()
    dedup_rels: List[CodeRelationship] = []
    for r in relationships_raw:
        rk = (r["repo"], r["source_filepath"], r["source_symbol"], r["target_symbol"], r["relationship_type"], r["line_number"])
        if rk not in seen_rels:
            seen_rels.add(rk)
            dedup_rels.append(CodeRelationship(**r))

    return ExtractionResult(
        chunks=[CodeChunk(**c) for c in chunks_raw],
        symbols=[CodeSymbol(**s) for s in symbols_raw],
        outline=[f"{o['name']} ({o['kind']}) lines {o['start_line']}-{o['end_line']}" for o in outline_items],
        relationships=dedup_rels,
        api_routes=[],
        api_client_calls=[],
    )
