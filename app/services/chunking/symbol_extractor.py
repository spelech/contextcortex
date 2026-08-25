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
    CALL_NODE_TYPES,
    IMPORT_NODE_TYPES,
    extract_target_from_call_node,
    extract_import_targets,
    extract_inheritance_relationships
)
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
    max_chunk_chars: int = 1500
) -> ExtractionResult:
    """
    Parses code using Tree-sitter AST, extracting:
    1. Structural code chunks (classes, methods, functions, module-level blocks).
    2. Symbol table records (name, kind, signature, lines) for instant lookup.
    3. File outline hierarchy.
    4. Server API route definitions and client call sites.
    """
    language = detect_language(filepath)
    source_bytes = code.encode("utf-8")
    lines = code.splitlines()
    total_lines = len(lines)
    
    import sys
    chunker_mod = sys.modules.get("app.services.chunker")
    _get_parser = getattr(chunker_mod, "get_tree_sitter_parser", get_tree_sitter_parser) if chunker_mod else get_tree_sitter_parser
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

    def traverse(node, parent_symbol: Optional[str] = None):
        current_active_symbol = parent_symbol or file_symbol
        line_num = node.start_point[0] + 1

        if node.type in target_types:
            name = extract_node_name(node, source_bytes) or "anonymous"
            full_symbol = f"{parent_symbol}.{name}" if parent_symbol else name
            kind = node.type
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
                "name": name,
                "kind": kind,
                "start_line": start_line,
                "end_line": end_line,
                "signature": first_line[:120]
            })

            # Check inheritance / interface implementation on class declaration nodes
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

            # Add as discrete chunk if reasonable size
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
                # Sub-chunk large functions/classes
                sub = split_by_length(node_text, heading=f"{full_symbol} ({kind})", max_chars=max_chunk_chars)
                for s in sub:
                    s["symbol"] = full_symbol
                    s["kind"] = kind
                    s["start_line"] = start_line + s.get("start_line", 1) - 1
                    s["end_line"] = start_line + s.get("end_line", end_line - start_line + 1) - 1
                    chunks.append(s)

            # Traverse child nodes for nested methods/functions
            for child in node.children:
                traverse(child, parent_symbol=full_symbol)

        elif node.type in CALL_NODE_TYPES:
            target = extract_target_from_call_node(node, source_bytes)
            if target and target not in ("self", "this", "super"):
                # Clean method prefix if full_symbol has parent
                active_src = parent_symbol if parent_symbol else file_symbol
                # if current active symbol is a method like Foo.bar, extract just bar or Foo.bar
                if active_src and "." in active_src:
                    active_src_name = active_src.split(".")[-1]
                else:
                    active_src_name = active_src
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

    parsed_symbols = [CodeSymbol(**s) for s in symbols]
    routes, client_calls = extract_api_routes_and_calls(code, filepath, repo=repo, symbols=parsed_symbols)

    return ExtractionResult(
        chunks=[CodeChunk(**c) for c in chunks],
        symbols=parsed_symbols,
        outline=[f"{o['name']} ({o['kind']}) lines {o['start_line']}-{o['end_line']}" for o in outline],
        relationships=[CodeRelationship(**r) for r in relationships],
        api_routes=routes,
        api_client_calls=client_calls
    )



def get_file_outline(code: str, filepath: str) -> List[str]:
    """Returns a structured AST outline of classes, methods, and functions in a file."""
    res = extract_symbols_and_chunks(code, filepath)
    return res.outline
