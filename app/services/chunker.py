import os
import re
from typing import List, Dict, Any, Optional
from app.models.schemas import CodeChunk, MarkdownChunk, CodeSymbol, CodeRelationship, ExtractionResult

# Supported language mappings to tree-sitter language names
EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".cs": "c_sharp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".sh": "bash",
    ".bash": "bash",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown",
    ".txt": "text"
}

_PARSERS: Dict[str, Any] = {}

def get_tree_sitter_parser(lang_name: str):
    """Retrieve or initialize a cached Tree-sitter parser for a language."""
    if lang_name in _PARSERS:
        return _PARSERS[lang_name]
    try:
        import tree_sitter_language_pack as tslp
        try:
            parser = tslp.get_parser(lang_name)
        except Exception:
            # Fallback for naming variants like c_sharp <-> csharp
            alt_name = "csharp" if lang_name == "c_sharp" else "c_sharp" if lang_name == "csharp" else lang_name
            parser = tslp.get_parser(alt_name)
        _PARSERS[lang_name] = parser
        return parser
    except Exception:
        return None

def detect_language(filepath: str) -> str:
    ext = os.path.splitext(filepath)[1].lower()
    return EXTENSION_TO_LANGUAGE.get(ext, "text")

def is_code_file(filepath: str) -> bool:
    lang = detect_language(filepath)
    return lang not in ("markdown", "text", "json", "yaml", "toml")

def split_by_length(text: str, heading: str, max_chars: int = 1500, overlap: int = 200) -> List[Dict[str, Any]]:
    if len(text) <= max_chars:
        return [{"heading": heading, "content": text, "start_line": 1, "end_line": len(text.splitlines())}]
    
    lines = text.splitlines(keepends=True)
    chunks = []
    current_chunk = []
    current_len = 0
    start_line = 1
    current_line = 1
    
    for line in lines:
        if current_len + len(line) > max_chars and current_chunk:
            chunk_str = "".join(current_chunk)
            chunks.append({
                "heading": heading,
                "content": chunk_str,
                "start_line": start_line,
                "end_line": current_line - 1
            })
            # keep overlap lines
            overlap_lines = []
            overlap_len = 0
            for l in reversed(current_chunk):
                if overlap_len + len(l) <= overlap:
                    overlap_lines.insert(0, l)
                    overlap_len += len(l)
                else:
                    break
            current_chunk = overlap_lines
            current_len = overlap_len
            start_line = max(1, current_line - len(overlap_lines))
        
        current_chunk.append(line)
        current_len += len(line)
        current_line += 1
        
    if current_chunk:
        chunk_str = "".join(current_chunk)
        chunks.append({
            "heading": heading,
            "content": chunk_str,
            "start_line": start_line,
            "end_line": current_line - 1
        })
    return chunks

def chunk_markdown(text: str, max_chars: int = 1500, overlap: int = 200) -> List[MarkdownChunk]:
    """Chunks markdown documents by header hierarchies (# ## ###)."""
    lines = text.split("\n")
    chunks = []
    current_heading = "Root"
    current_section = []
    section_start_line = 1

    heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")

    for line_idx, line in enumerate(lines, start=1):
        match = heading_pattern.match(line)
        if match:
            if current_section:
                section_text = "\n".join(current_section)
                sub_chunks = split_by_length(section_text, current_heading, max_chars, overlap)
                for sc in sub_chunks:
                    sc["start_line"] = section_start_line + sc.get("start_line", 1) - 1
                    sc["end_line"] = section_start_line + sc.get("end_line", len(current_section)) - 1
                chunks.extend(sub_chunks)
                current_section = []
            current_heading = match.group(2).strip()
            section_start_line = line_idx
            current_section.append(line)
        else:
            current_section.append(line)

    if current_section:
        section_text = "\n".join(current_section)
        sub_chunks = split_by_length(section_text, current_heading, max_chars, overlap)
        for sc in sub_chunks:
            sc["start_line"] = section_start_line + sc.get("start_line", 1) - 1
            sc["end_line"] = section_start_line + sc.get("end_line", len(current_section)) - 1
        chunks.extend(sub_chunks)

    return [MarkdownChunk(**c) for c in chunks]

# Tree-sitter node type queries per language for AST chunking & outline
CODE_CONTAINER_TYPES = {
    "python": {"class_definition", "function_definition", "async_function_definition"},
    "javascript": {"class_declaration", "function_declaration", "method_definition", "arrow_function"},
    "typescript": {"class_declaration", "interface_declaration", "function_declaration", "method_definition", "type_alias_declaration", "enum_declaration"},
    "tsx": {"class_declaration", "interface_declaration", "function_declaration", "method_definition", "type_alias_declaration", "enum_declaration"},
    "go": {"function_declaration", "method_declaration", "type_declaration"},
    "rust": {"function_item", "impl_item", "struct_item", "trait_item", "enum_item"},
    "c_sharp": {"class_declaration", "interface_declaration", "method_declaration", "struct_declaration", "enum_declaration"},
    "csharp": {"class_declaration", "interface_declaration", "method_declaration", "struct_declaration", "enum_declaration"},
    "cpp": {"class_specifier", "function_definition", "struct_specifier", "namespace_definition"},
    "c": {"function_definition", "struct_specifier"},
    "java": {"class_declaration", "method_declaration", "interface_declaration"},
    "ruby": {"class", "method", "module"},
    "php": {"class_declaration", "function_definition", "method_declaration"}
}

def extract_node_name(node, source_bytes: bytes) -> Optional[str]:
    """Extract symbol name from AST node."""
    name_node = node.child_by_field_name("name")
    if name_node:
        return source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="ignore")
    # Go / Rust / C fallbacks
    for child in node.children:
        if child.type in ("identifier", "type_identifier", "name"):
            return source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore")
    return None

CALL_NODE_TYPES = {
    "call", "call_expression", "method_invocation", "invocation_expression",
    "function_call_expression", "new_expression", "object_creation_expression",
    "macro_invocation"
}

IMPORT_NODE_TYPES = {
    "import_statement", "import_from_statement", "import_declaration",
    "use_declaration", "using_directive", "namespace_use_declaration",
    "preproc_include"
}

def extract_target_from_call_node(node, source_bytes: bytes) -> Optional[str]:
    """Extract function, method, constructor, or macro name from a call node."""
    fn_node = node.child_by_field_name("function") or node.child_by_field_name("method") or node.child_by_field_name("expression")
    if not fn_node and len(node.children) > 0:
        fn_node = node.children[0]

    if fn_node:
        call_str = source_bytes[fn_node.start_byte:fn_node.end_byte].decode("utf-8", errors="ignore").strip()
        # Clean up any trailing brackets or instantiation keywords if any
        if call_str.startswith("new "):
            call_str = call_str[4:].strip()
        # Clean method call like self.foo() or obj.bar() or math.sqrt() -> get target symbol name
        if "(" in call_str:
            call_str = call_str.split("(")[0].strip()
        if "." in call_str:
            parts = [p for p in call_str.split(".") if p]
            if parts:
                return parts[-1]
        if "::" in call_str:
            parts = [p for p in call_str.split("::") if p]
            if parts:
                return parts[-1]
        if "->" in call_str:
            parts = [p for p in call_str.split("->") if p]
            if parts:
                return parts[-1]
        if "\\" in call_str:
            parts = [p for p in call_str.split("\\") if p]
            if parts:
                return parts[-1]
        return call_str
    return None

def extract_import_targets(node, source_bytes: bytes) -> List[str]:
    """Extract symbol/module names from import nodes."""
    imp_text = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore").strip()
    targets = []
    # Extract identifiers, quoted modules, or package names
    # Match imported names or modules
    for child in node.children:
        if child.type in ("identifier", "type_identifier", "dotted_name", "string", "string_literal", "import_spec", "import_clause", "namespace_use_clause"):
            val = source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore").strip("\"'`; ")
            if val and val not in ("import", "from", "as", "use", "using", "include"):
                targets.append(val)
    if not targets:
        # Fallback regex over node text
        tokens = re.findall(r'[A-Za-z_][A-Za-z0-9_\.]*', imp_text)
        targets = [t for t in tokens if t not in ("import", "from", "as", "use", "using", "include", "require", "package")]
    return targets

def extract_inheritance_relationships(node, language: str, source_bytes: bytes, current_symbol: str, line_num: int) -> List[Dict[str, Any]]:
    """Extract INHERITS and IMPLEMENTS relationships from class/interface definition nodes."""
    rels = []
    # Python: class Derived(Base1, Base2):
    if language == "python":
        arg_list = node.child_by_field_name("superclasses") or node.child_by_field_name("argument_list")
        if arg_list:
            for child in arg_list.children:
                if child.type in ("identifier", "attribute"):
                    target = source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore").strip()
                    if "." in target:
                        target = target.split(".")[-1]
                    if target:
                        rels.append({"target": target, "type": "INHERITS", "line": line_num})

    # JavaScript / TypeScript
    elif language in ("javascript", "typescript", "tsx"):
        for child in node.children:
            if child.type in ("class_heritage", "extends_clause", "extends_type_clause", "implements_clause"):
                heritage_nodes = child.children if child.type == "class_heritage" else [child]
                for hnode in heritage_nodes:
                    if hnode.type in ("extends_clause", "extends_type_clause"):
                        for sub in hnode.children:
                            if sub.type in ("identifier", "type_identifier", "expression_with_type_arguments"):
                                t = source_bytes[sub.start_byte:sub.end_byte].decode("utf-8", errors="ignore").strip()
                                if t and t not in ("extends",):
                                    rels.append({"target": t, "type": "INHERITS", "line": line_num})
                    elif hnode.type == "implements_clause":
                        for sub in hnode.children:
                            if sub.type in ("identifier", "type_identifier", "expression_with_type_arguments"):
                                t = source_bytes[sub.start_byte:sub.end_byte].decode("utf-8", errors="ignore").strip()
                                if t and t not in ("implements",):
                                    rels.append({"target": t, "type": "IMPLEMENTS", "line": line_num})

    # Go: embedded structs
    elif language == "go":
        # struct embedded fields or interfaces
        pass

    # Rust: impl Trait for Struct
    elif language == "rust":
        if node.type == "impl_item":
            trait_node = node.child_by_field_name("trait")
            type_node = node.child_by_field_name("type")
            if trait_node and type_node:
                trait_name = source_bytes[trait_node.start_byte:trait_node.end_byte].decode("utf-8", errors="ignore").strip()
                struct_name = source_bytes[type_node.start_byte:type_node.end_byte].decode("utf-8", errors="ignore").strip()
                if trait_name and struct_name:
                    rels.append({"source_override": struct_name, "target": trait_name, "type": "IMPLEMENTS", "line": line_num})

    # C#
    elif language in ("c_sharp", "csharp"):
        base_list = node.child_by_field_name("base_list")
        if not base_list:
            for c in node.children:
                if c.type == "base_list":
                    base_list = c
                    break
        if base_list:
            for child in base_list.children:
                if child.type in ("identifier", "simple_type", "type_identifier", "generic_name"):
                    t = source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore").strip()
                    if t:
                        rel_type = "IMPLEMENTS" if (t.startswith("I") and len(t) > 1 and t[1].isupper()) else "INHERITS"
                        rels.append({"target": t, "type": rel_type, "line": line_num})

    # Java
    elif language == "java":
        super_node = node.child_by_field_name("superclass")
        if not super_node:
            for c in node.children:
                if c.type == "superclass":
                    super_node = c
                    break
        if super_node:
            for child in super_node.children:
                if child.type in ("type_identifier", "type_list"):
                    t = source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore").strip()
                    if t and t != "extends":
                        rels.append({"target": t, "type": "INHERITS", "line": line_num})

        impl_node = node.child_by_field_name("interfaces")
        if not impl_node:
            for c in node.children:
                if c.type in ("super_interfaces", "implements_clause"):
                    impl_node = c
                    break
        if impl_node:
            for child in impl_node.children:
                if child.type in ("type_identifier", "type_list", "interface_type_list"):
                    t = source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore").strip()
                    if t and t != "implements":
                        # split by comma if list
                        for sub_t in t.split(","):
                            sub_t = sub_t.strip()
                            if sub_t:
                                rels.append({"target": sub_t, "type": "IMPLEMENTS", "line": line_num})

    # C++
    elif language in ("cpp", "c"):
        for child in node.children:
            if child.type == "base_class_clause":
                for sub in child.children:
                    if sub.type in ("type_identifier", "identifier"):
                        t = source_bytes[sub.start_byte:sub.end_byte].decode("utf-8", errors="ignore").strip()
                        if t and t not in ("public", "protected", "private"):
                            rels.append({"target": t, "type": "INHERITS", "line": line_num})

    # PHP
    elif language == "php":
        for child in node.children:
            if child.type == "base_clause":
                t = source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore").strip()
                t = re.sub(r"^extends\s+", "", t).strip()
                if t:
                    rels.append({"target": t, "type": "INHERITS", "line": line_num})
            elif child.type == "class_interface_clause":
                t = source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore").strip()
                t = re.sub(r"^implements\s+", "", t).strip()
                if t:
                    for sub_t in t.split(","):
                        sub_t = sub_t.strip()
                        if sub_t:
                            rels.append({"target": sub_t, "type": "IMPLEMENTS", "line": line_num})

    # Ruby
    elif language == "ruby":
        super_node = node.child_by_field_name("superclass")
        if not super_node:
            for c in node.children:
                if c.type == "superclass":
                    super_node = c
                    break
        if super_node:
            t = source_bytes[super_node.start_byte:super_node.end_byte].decode("utf-8", errors="ignore").strip("< ").strip()
            if t:
                rels.append({"target": t, "type": "INHERITS", "line": line_num})

    return rels

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
    """
    language = detect_language(filepath)
    source_bytes = code.encode("utf-8")
    lines = code.splitlines()
    total_lines = len(lines)
    
    parser = get_tree_sitter_parser(language)
    if not parser:
        # Fallback to line-based chunking for unsupported languages
        raw_chunks = split_by_length(code, heading=os.path.basename(filepath), max_chars=max_chunk_chars)
        return ExtractionResult(
            chunks=[CodeChunk(**c) for c in raw_chunks],
            symbols=[],
            outline=[],
            relationships=[]
        )
        
    try:
        tree = parser.parse(source_bytes)
        root = tree.root_node
    except Exception:
        raw_chunks = split_by_length(code, heading=os.path.basename(filepath), max_chars=max_chunk_chars)
        return ExtractionResult(
            chunks=[CodeChunk(**c) for c in raw_chunks],
            symbols=[],
            outline=[],
            relationships=[]
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

    return ExtractionResult(
        chunks=[CodeChunk(**c) for c in chunks],
        symbols=[CodeSymbol(**s) for s in symbols],
        outline=[f"{o['name']} ({o['kind']}) lines {o['start_line']}-{o['end_line']}" for o in outline],
        relationships=[CodeRelationship(**r) for r in relationships]
    )

def get_file_outline(code: str, filepath: str) -> List[str]:
    """Returns a structured AST outline of classes, methods, and functions in a file."""
    res = extract_symbols_and_chunks(code, filepath)
    return res.outline
