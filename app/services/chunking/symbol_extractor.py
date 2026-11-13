import os
import re
import logging
from typing import List, Dict, Any, Optional, Tuple
from app.models.schemas import CodeChunk, MarkdownChunk, CodeSymbol, CodeRelationship, ExtractionResult, ApiRouteRecord, ApiClientCallRecord
from app.services.chunking.tree_sitter_loader import detect_language, get_tree_sitter_parser
from app.services.chunking.text_chunker import (
    split_by_length,
    chunk_markdown,
    CODE_CONTAINER_TYPES,
    extract_node_name,
    extract_callable_variable_or_pair,
    CALL_NODE_TYPES,
    JSX_CALL_NODE_TYPES,
    IMPORT_NODE_TYPES,
    extract_target_from_call_node,
    extract_jsx_component_target,
    extract_import_targets,
    extract_inheritance_relationships
)
from app.services.chunking.cobol_extractor import extract_cobol_symbols_and_chunks
from app.services.chunking.csharp_receiver_types import qualify_csharp_call
from app.services.chunking.api_route_extractor import (
    normalize_path_pattern,
    match_route_and_call,
    extract_api_routes_and_calls,
    find_enclosing_symbol
)

logger = logging.getLogger("contextcortex.chunker")

def extract_symbols_and_chunks(
    code: str, 
    filepath: str, 
    repo: str = "default",
    max_chunk_chars: int = 4000
) -> ExtractionResult:
    """
    Parses code using Tree-sitter AST, extracting:
    1. Structural code chunks (classes, methods, functions, module-level blocks).
    2. Symbol table records (name, kind, signature, lines) for instant lookup.
    3. File outline hierarchy.
    4. Server API route definitions and client call sites.
    """
    language = detect_language(filepath)
    import sys
    chunker_mod = sys.modules.get("app.services.chunker")
    _get_parser = getattr(chunker_mod, "get_tree_sitter_parser", get_tree_sitter_parser) if chunker_mod else get_tree_sitter_parser

    if language == "cobol":
        return extract_cobol_symbols_and_chunks(
            code, filepath, repo=repo, max_chunk_chars=max_chunk_chars, parser_getter=_get_parser
        )

    source_bytes = code.encode("utf-8")
    lines = code.splitlines()
    total_lines = len(lines)
    
    parser = _get_parser(language)
    if not parser:
        # Fallback to line-based chunking for unsupported languages
        raw_chunks = split_by_length(code, heading=os.path.basename(filepath), max_chars=max_chunk_chars)
        routes, client_calls = extract_api_routes_and_calls(code, filepath, repo=repo, symbols=[])
        return ExtractionResult(
            chunks=[CodeChunk(**c) for c in raw_chunks],
            symbols=[],
            relationships=[],
            api_routes=routes,
            api_client_calls=client_calls
        )
        
    try:
        tree = parser.parse(source_bytes)
        root = tree.root_node
    except Exception:
        raw_chunks = split_by_length(code, heading=os.path.basename(filepath), max_chars=max_chunk_chars)
        routes, client_calls = extract_api_routes_and_calls(code, filepath, repo=repo, symbols=[])
        return ExtractionResult(
            chunks=[CodeChunk(**c) for c in raw_chunks],
            symbols=[],
            outline=[],
            relationships=[],
            api_routes=routes,
            api_client_calls=client_calls
        )

    symbols = []
    chunks = []
    outline = []
    relationships = []
    
    target_types = CODE_CONTAINER_TYPES.get(language, set())
    file_symbol = os.path.basename(filepath)
    is_csharp = language in ("c_sharp", "csharp")
    receiver_type_cache: Dict[Any, Dict[str, str]] = {}

    def traverse(node, parent_symbol: Optional[str] = None):
        line_num = node.start_point[0] + 1

        is_container = False
        name = None
        kind = node.type

        if node.type in target_types:
            if node.type in ("variable_declarator", "pair"):
                res_var = extract_callable_variable_or_pair(node, source_bytes)
                if res_var:
                    name, kind = res_var
                    is_container = True
                elif node.type == "variable_declarator":
                    name_node = node.child_by_field_name("name")
                    val_node = node.child_by_field_name("value")
                    if name_node and val_node and name_node.type == "identifier" and val_node.type == "object":
                        obj_name = source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="ignore").strip()
                        next_parent = f"{parent_symbol}.{obj_name}" if parent_symbol else obj_name
                        for child in node.children:
                            traverse(child, parent_symbol=next_parent)
                        return
            else:
                name = extract_node_name(node, source_bytes)
                if name:
                    is_container = True
                    if language in ("c_sharp", "csharp") and node.type == "record_declaration":
                        if any(c.type == "struct" for c in node.children):
                            kind = "record_struct_declaration"

        if is_container and name:
            full_symbol = f"{parent_symbol}.{name}" if parent_symbol else name
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            node_text = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")
            
            first_line = lines[start_line - 1].strip() if start_line - 1 < len(lines) else ""
            
            symbol_record = {
                "name": name,
                "full_symbol": full_symbol,
                "kind": kind,
                "start_line": start_line,
                "end_line": end_line,
                "signature": first_line[:120],
                "filepath": filepath,
                "repo": repo,
                "language": language
            }
            symbols.append(symbol_record)
            outline.append({
                "name": full_symbol if "." in full_symbol else name,
                "kind": kind,
                "start_line": start_line,
                "end_line": end_line,
                "signature": first_line[:120]
            })

            # C# 12 primary constructor on class/struct declaration
            if language in ("c_sharp", "csharp") and node.type in ("class_declaration", "struct_declaration"):
                p_list = next((c for c in node.children if c.type == "parameter_list"), None)
                if p_list is not None:
                    p_start = p_list.start_point[0] + 1
                    p_end = p_list.end_point[0] + 1
                    p_sig = f"{name}{source_bytes[p_list.start_byte:p_list.end_byte].decode('utf-8', errors='ignore').strip()}"[:120]
                    ctor_full = f"{full_symbol}.{name}"
                    symbols.append({
                        "name": name,
                        "full_symbol": ctor_full,
                        "kind": "constructor_declaration",
                        "start_line": p_start,
                        "end_line": p_end,
                        "signature": p_sig,
                        "filepath": filepath,
                        "repo": repo,
                        "language": language,
                    })
                    outline.append({
                        "name": ctor_full,
                        "kind": "constructor_declaration",
                        "start_line": p_start,
                        "end_line": p_end,
                        "signature": p_sig,
                    })

            inherit_rels = extract_inheritance_relationships(node, language, source_bytes, name, start_line)
            for irel in inherit_rels:
                src_sym = irel.get("source_override") or name
                relationships.append({
                    "repo": repo,
                    "source_filepath": filepath,
                    "source_symbol": src_sym,
                    "target_symbol": irel["target"],
                    "relationship_type": irel["type"],
                    "line_number": irel["line"]
                })

            if len(node_text) <= max_chunk_chars:
                chunks.append({
                    "symbol": full_symbol,
                    "kind": kind,
                    "heading": f"{full_symbol} ({kind})",
                    "content": node_text,
                    "start_line": start_line,
                    "end_line": end_line
                })
            else:
                sub = split_by_length(node_text, heading=f"{full_symbol} ({kind})", max_chars=max_chunk_chars)
                for s in sub:
                    s["symbol"] = full_symbol
                    s["kind"] = kind
                    s["start_line"] = start_line + s.get("start_line", 1) - 1
                    s["end_line"] = start_line + s.get("end_line", end_line - start_line + 1) - 1
                    chunks.append(s)

            for child in node.children:
                traverse(child, parent_symbol=full_symbol)

        elif node.type in CALL_NODE_TYPES or node.type in JSX_CALL_NODE_TYPES:
            target = (
                extract_jsx_component_target(node, source_bytes)
                if node.type in JSX_CALL_NODE_TYPES
                else extract_target_from_call_node(node, source_bytes)
            )
            if target and target not in ("self", "this", "super", "new", "var"):
                if is_csharp:
                    target = qualify_csharp_call(node, source_bytes, target, receiver_type_cache)
                active_src = parent_symbol if parent_symbol else file_symbol
                active_src_name = parent_symbol.split(".")[-1] if (parent_symbol and "." in parent_symbol) else active_src
                relationships.append({
                    "repo": repo,
                    "source_filepath": filepath,
                    "source_symbol": active_src_name,
                    "target_symbol": target,
                    "relationship_type": "CALLS",
                    "line_number": line_num
                })
            for child in node.children:
                traverse(child, parent_symbol=parent_symbol)

        elif node.type in IMPORT_NODE_TYPES:
            targets = extract_import_targets(node, source_bytes)
            for t in targets:
                relationships.append({
                    "repo": repo,
                    "source_filepath": filepath,
                    "source_symbol": file_symbol,
                    "target_symbol": t,
                    "relationship_type": "IMPORTS",
                    "line_number": line_num
                })
        else:
            for child in node.children:
                traverse(child, parent_symbol=parent_symbol)

    traverse(root)

    # If no AST symbols found (e.g. script with top-level statements), chunk by length
    if not chunks:
        chunks = split_by_length(code, heading=os.path.basename(filepath), max_chars=max_chunk_chars)
        for c in chunks:
            c["symbol"] = None
            c["kind"] = "module"

    dedup_symbols = []
    seen_syms = set()
    for s in symbols:
        s_key = (s["repo"], s["filepath"], s["name"], s["full_symbol"], s["kind"], s["start_line"], s["end_line"])
        if s_key not in seen_syms:
            seen_syms.add(s_key)
            dedup_symbols.append(s)

    dedup_relationships = []
    seen_rels = set()
    for r in relationships:
        r_key = (r["repo"], r["source_filepath"], r["source_symbol"], r["target_symbol"], r["relationship_type"], r["line_number"])
        if r_key not in seen_rels:
            seen_rels.add(r_key)
            dedup_relationships.append(r)

    parsed_symbols = [CodeSymbol(**s) for s in dedup_symbols]
    routes, client_calls = extract_api_routes_and_calls(code, filepath, repo=repo, symbols=parsed_symbols)

    return ExtractionResult(
        chunks=[CodeChunk(**c) for c in chunks],
        symbols=parsed_symbols,
        outline=[f"{o['name']} ({o['kind']}) lines {o['start_line']}-{o['end_line']}" for o in outline],
        relationships=[CodeRelationship(**r) for r in dedup_relationships],
        api_routes=routes,
        api_client_calls=client_calls
    )



def get_file_outline(code: str, filepath: str) -> List[str]:
    """Returns a structured AST outline of classes, methods, and functions in a file."""
    res = extract_symbols_and_chunks(code, filepath)
    return res.outline
