import os
import re
from typing import List, Dict, Any, Optional, Set, Tuple
from app.models.schemas import MarkdownChunk, CodeRelationship
from app.services.chunking.tree_sitter_loader import detect_language

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

WIKILINK_PATTERN = re.compile(r'(?<!\!)\[\[([^\]]+)\]\]')
MD_LINK_PATTERN = re.compile(r'(?<!\!)\[([^\]]*)\]\(([^)]+)\)')

def extract_markdown_doc_links(content: str, filepath: str, repo: str) -> List[CodeRelationship]:
    """
    Extracts relative markdown links and Obsidian wikilinks from documentation content,
    returning a list of CodeRelationship objects with relationship_type="DOC_LINKS_TO".
    """
    if not content:
        return []

    source_symbol = os.path.basename(filepath) if filepath else ""
    relationships: List[CodeRelationship] = []
    seen: Set[Tuple[str, int]] = set()

    for line_idx, line in enumerate(content.split("\n"), start=1):
        # 1. Match Obsidian wikilinks: [[Target]] or [[Target|Label]] or [[Target#Section|Label]]
        for m in WIKILINK_PATTERN.finditer(line):
            inner = m.group(1).strip()
            if not inner:
                continue
            # Split pipe for label
            target_part = inner.split("|", 1)[0].strip()
            # If section anchor on same doc (e.g. [[#Section]]), skip
            if target_part.startswith("#"):
                continue
            # Strip heading anchor if present (e.g. Target#Section -> Target)
            target_name = target_part.split("#", 1)[0].strip()
            if not target_name:
                continue

            dedup_key = (target_name, line_idx)
            if dedup_key not in seen:
                seen.add(dedup_key)
                relationships.append(CodeRelationship(
                    repo=repo,
                    source_filepath=filepath,
                    source_symbol=source_symbol,
                    target_symbol=target_name,
                    relationship_type="DOC_LINKS_TO",
                    line_number=line_idx
                ))

        # 2. Match standard markdown links: [label](target) or [label](target "title")
        for m in MD_LINK_PATTERN.finditer(line):
            raw_target = m.group(2).strip()
            if not raw_target:
                continue
            # Strip title in quotes if present, e.g. path/to/doc.md "Title"
            url_part = raw_target.split()[0].strip()
            if url_part.startswith("<") and url_part.endswith(">"):
                url_part = url_part[1:-1].strip()

            # Ignore web URLs, protocols, and anchors
            if re.match(r'^(?:https?://|mailto:|ftp://|file://|javascript:|data:|//)', url_part, re.IGNORECASE):
                continue
            if url_part.startswith("#"):
                continue

            # Strip fragment / anchor if present in target URL (e.g. doc.md#section -> doc.md)
            if "#" in url_part:
                target_doc = url_part.split("#", 1)[0].strip()
            else:
                target_doc = url_part

            # Strip query params if present (e.g. doc.md?v=1 -> doc.md)
            if "?" in target_doc:
                target_doc = target_doc.split("?", 1)[0].strip()

            if not target_doc:
                continue

            dedup_key = (target_doc, line_idx)
            if dedup_key not in seen:
                seen.add(dedup_key)
                relationships.append(CodeRelationship(
                    repo=repo,
                    source_filepath=filepath,
                    source_symbol=source_symbol,
                    target_symbol=target_doc,
                    relationship_type="DOC_LINKS_TO",
                    line_number=line_idx
                ))

    return relationships

# Tree-sitter node type queries per language for AST chunking & outline
CODE_CONTAINER_TYPES = {
    "python": {"class_definition", "function_definition", "async_function_definition"},
    "javascript": {"class_declaration", "function_declaration", "method_definition", "variable_declarator", "pair"},
    "typescript": {"class_declaration", "interface_declaration", "function_declaration", "method_definition", "type_alias_declaration", "enum_declaration", "variable_declarator", "pair"},
    "tsx": {"class_declaration", "interface_declaration", "function_declaration", "method_definition", "type_alias_declaration", "enum_declaration", "variable_declarator", "pair"},
    "go": {"function_declaration", "method_declaration", "type_declaration"},
    "rust": {"function_item", "impl_item", "struct_item", "trait_item", "enum_item"},
    "c_sharp": {"class_declaration", "interface_declaration", "method_declaration", "struct_declaration", "enum_declaration", "record_declaration", "record_struct_declaration", "constructor_declaration"},
    "csharp": {"class_declaration", "interface_declaration", "method_declaration", "struct_declaration", "enum_declaration", "record_declaration", "record_struct_declaration", "constructor_declaration"},
    "cpp": {"class_specifier", "function_definition", "struct_specifier", "namespace_definition"},
    "c": {"function_definition", "struct_specifier"},
    "java": {"class_declaration", "method_declaration", "interface_declaration", "constructor_declaration", "record_declaration"},
    "ruby": {"class", "method", "module"},
    "php": {"class_declaration", "function_definition", "method_declaration"}
}

_JS_WRAPPED_COMPONENT_CALLS = frozenset({
    "memo", "React.memo", "forwardRef", "React.forwardRef",
    "lazy", "React.lazy", "create", "defineStore", "observer",
})


def extract_callable_variable_or_pair(node, source_bytes: bytes) -> Optional[Tuple[str, str]]:
    """
    For JS/TS/TSX `variable_declarator` or `pair` nodes, returns `(name, kind)`
    only when the assigned value is an arrow function, function expression, or
    a recognized React/store higher-order wrapper (memo, forwardRef, create, etc.).
    Returns None for plain data variables or object literal properties.
    """
    if node.type == "variable_declarator":
        name_node = node.child_by_field_name("name")
        val_node = node.child_by_field_name("value")
        if not name_node or not val_node or name_node.type != "identifier":
            return None
        name = source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="ignore").strip()
        if not name:
            return None
        if val_node.type in ("arrow_function", "function_expression", "function", "generator_function"):
            return (name, "function_declaration")
        if val_node.type == "call_expression":
            fn_node = val_node.child_by_field_name("function")
            fn_name = source_bytes[fn_node.start_byte:fn_node.end_byte].decode("utf-8", errors="ignore").strip() if fn_node else ""
            fn_base = re.sub(r"<.*?>", "", fn_name).strip()
            if fn_base in _JS_WRAPPED_COMPONENT_CALLS or fn_base.endswith((".memo", ".forwardRef", ".lazy")):
                return (name, "function_declaration")
        return None

    if node.type == "pair":
        key_node = node.child_by_field_name("key")
        val_node = node.child_by_field_name("value")
        if not key_node or not val_node:
            return None
        if val_node.type not in ("arrow_function", "function_expression", "function", "generator_function"):
            return None
        if key_node.type not in ("property_identifier", "identifier"):
            return None
        name = source_bytes[key_node.start_byte:key_node.end_byte].decode("utf-8", errors="ignore").strip()
        if not name:
            return None
        return (name, "method_definition")

    return None


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

JSX_CALL_NODE_TYPES = {"jsx_opening_element", "jsx_self_closing_element"}

IMPORT_NODE_TYPES = {
    "import_statement", "import_from_statement", "import_declaration",
    "use_declaration", "using_directive", "namespace_use_declaration",
    "preproc_include"
}


def extract_jsx_component_target(node, source_bytes: bytes) -> Optional[str]:
    """Extracts React/JSX uppercase component invocations (e.g. `<AppKeysCard />`, `<Layout.Header>`)."""
    name_node = node.child_by_field_name("name")
    if not name_node:
        return None
    raw = source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="ignore").strip()
    raw = re.sub(r"<.*>", "", raw).strip()
    if not raw or raw in ("Fragment", "React.Fragment"):
        return None
    leaf = raw.split(".")[-1].strip()
    if leaf and leaf[0].isupper():
        return leaf
    return None


def extract_target_from_call_node(node, source_bytes: bytes) -> Optional[str]:
    """Extract function, method, constructor, or macro name from a call node."""
    fn_node = (
        node.child_by_field_name("function")
        or node.child_by_field_name("method")
        or node.child_by_field_name("expression")
        or node.child_by_field_name("type")
        or node.child_by_field_name("constructor")
    )
    if not fn_node and len(node.children) > 0:
        for child in node.children:
            if child.type not in ("new", "(", ")", ";", "{", "}", "[", "]"):
                fn_node = child
                break

    if fn_node:
        call_str = source_bytes[fn_node.start_byte:fn_node.end_byte].decode("utf-8", errors="ignore").strip()
        if call_str.startswith("new "):
            call_str = call_str[4:].strip()
        if "(" in call_str:
            call_str = call_str.split("(")[0].strip()
        call_str = re.sub(r'<.*?>', '', call_str).strip('; >')
        for sep in ('.', '::', '->', '\\'):
            if sep in call_str:
                parts = [p for p in call_str.split(sep) if p]
                if parts:
                    call_str = parts[-1]
        call_str = re.sub(r'<.*?>', '', call_str).strip('; >()')
        if not call_str or call_str in ("new", "var", "self", "this", "super", "return", "throw", "yield", "void"):
            return None
        return call_str
    return None


def _collect_js_import_clause(clause_node, source_bytes: bytes, out: List[str]) -> None:
    for sub in clause_node.children:
        if sub.type == "identifier":
            val = source_bytes[sub.start_byte:sub.end_byte].decode("utf-8", errors="ignore").strip()
            if val:
                out.append(val)
        elif sub.type == "import_specifier":
            for fld in ("name", "alias"):
                part = sub.child_by_field_name(fld)
                if part:
                    val = source_bytes[part.start_byte:part.end_byte].decode("utf-8", errors="ignore").strip()
                    if val and val != "type" and val not in out:
                        out.append(val)
        elif sub.type in ("named_imports", "namespace_import"):
            _collect_js_import_clause(sub, source_bytes, out)


def extract_import_targets(node, source_bytes: bytes) -> List[str]:
    """Extract symbol/module names from import nodes across Python, TS/JS, C#, Go, Rust, etc."""
    imp_text = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore").strip()
    targets: List[str] = []
    for child in node.children:
        if child.type == "aliased_import":
            for fld in ("name", "alias"):
                part = child.child_by_field_name(fld)
                if part:
                    val = source_bytes[part.start_byte:part.end_byte].decode("utf-8", errors="ignore").strip()
                    if val and val not in targets:
                        targets.append(val)
        elif child.type == "import_clause":
            _collect_js_import_clause(child, source_bytes, targets)
        elif child.type in (
            "identifier", "type_identifier", "dotted_name", "qualified_name",
            "scoped_identifier", "string", "string_literal", "import_spec", "namespace_use_clause",
        ):
            val = source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore").strip("\"'`; ")
            if val and val not in ("import", "from", "as", "use", "using", "include", "type", "static", "global"):
                targets.append(val)
    if not targets:
        tokens = re.findall(r'[A-Za-z_][A-Za-z0-9_\.]*', imp_text)
        targets = [t for t in tokens if t not in ("import", "from", "as", "use", "using", "include", "require", "package", "type", "static")]
    return targets


def _clean_type_target(raw_t: str) -> str:
    cleaned = re.sub(r"<.*>", "", raw_t).split("(")[0].strip()
    return cleaned.split(".")[-1].strip() if "." in cleaned else cleaned


def extract_inheritance_relationships(node, language: str, source_bytes: bytes, current_symbol: str, line_num: int) -> List[Dict[str, Any]]:
    """Extract INHERITS and IMPLEMENTS relationships from class/interface definition nodes."""
    rels = []
    if language == "python":
        arg_list = node.child_by_field_name("superclasses") or node.child_by_field_name("argument_list")
        if arg_list:
            for child in arg_list.children:
                if child.type in ("identifier", "attribute", "subscript"):
                    base_node = (child.child_by_field_name("value") or child.children[0]) if child.type == "subscript" else child
                    target = source_bytes[base_node.start_byte:base_node.end_byte].decode("utf-8", errors="ignore").strip()
                    target = _clean_type_target(target)
                    if target and target not in ("Generic", "Protocol", "ABC"):
                        rels.append({"target": target, "type": "INHERITS", "line": line_num})
                    elif target in ("Protocol", "ABC"):
                        rels.append({"target": target, "type": "IMPLEMENTS", "line": line_num})

    elif language in ("javascript", "typescript", "tsx"):
        ts_type_nodes = ("identifier", "type_identifier", "expression_with_type_arguments", "generic_type", "nested_type_identifier", "member_expression")
        for child in node.children:
            if child.type in ("class_heritage", "extends_clause", "extends_type_clause", "implements_clause"):
                heritage_nodes = child.children if child.type == "class_heritage" else [child]
                for hnode in heritage_nodes:
                    if hnode.type in ("extends_clause", "extends_type_clause"):
                        for sub in hnode.children:
                            if sub.type in ts_type_nodes:
                                t = _clean_type_target(source_bytes[sub.start_byte:sub.end_byte].decode("utf-8", errors="ignore"))
                                if t and t != "extends":
                                    rels.append({"target": t, "type": "INHERITS", "line": line_num})
                    elif hnode.type == "implements_clause":
                        for sub in hnode.children:
                            if sub.type in ts_type_nodes:
                                t = _clean_type_target(source_bytes[sub.start_byte:sub.end_byte].decode("utf-8", errors="ignore"))
                                if t and t != "implements":
                                    rels.append({"target": t, "type": "IMPLEMENTS", "line": line_num})

    elif language == "go":
        pass

    elif language == "rust":
        if node.type == "impl_item":
            trait_node = node.child_by_field_name("trait")
            type_node = node.child_by_field_name("type")
            if trait_node and type_node:
                trait_name = _clean_type_target(source_bytes[trait_node.start_byte:trait_node.end_byte].decode("utf-8", errors="ignore"))
                struct_name = _clean_type_target(source_bytes[type_node.start_byte:type_node.end_byte].decode("utf-8", errors="ignore"))
                if trait_name and struct_name:
                    rels.append({"source_override": struct_name, "target": trait_name, "type": "IMPLEMENTS", "line": line_num})

    elif language in ("c_sharp", "csharp"):
        base_list = node.child_by_field_name("base_list") or next((c for c in node.children if c.type == "base_list"), None)
        if base_list:
            cs_base_nodes = ("identifier", "simple_type", "type_identifier", "generic_name", "qualified_name", "primary_constructor_base_type")
            for child in base_list.children:
                if child.type in cs_base_nodes:
                    t = _clean_type_target(source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore"))
                    if t:
                        is_iface = t.startswith("I") and len(t) > 1 and t[1].isupper()
                        rel_type = "INHERITS" if node.type == "interface_declaration" else ("IMPLEMENTS" if is_iface else "INHERITS")
                        rels.append({"target": t, "type": rel_type, "line": line_num})

    elif language == "java":
        super_node = node.child_by_field_name("superclass") or next((c for c in node.children if c.type == "superclass"), None)
        if super_node:
            for child in super_node.children:
                if child.type in ("type_identifier", "type_list"):
                    t = source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore").strip()
                    if t and t != "extends":
                        rels.append({"target": t, "type": "INHERITS", "line": line_num})

        impl_node = node.child_by_field_name("interfaces") or next((c for c in node.children if c.type in ("super_interfaces", "implements_clause")), None)
        if impl_node:
            for child in impl_node.children:
                if child.type in ("type_identifier", "type_list", "interface_type_list"):
                    t = source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore").strip()
                    if t and t != "implements":
                        for sub_t in (s.strip() for s in t.split(",")):
                            if sub_t:
                                rels.append({"target": sub_t, "type": "IMPLEMENTS", "line": line_num})

    elif language in ("cpp", "c"):
        for child in node.children:
            if child.type == "base_class_clause":
                for sub in child.children:
                    if sub.type in ("type_identifier", "identifier"):
                        t = source_bytes[sub.start_byte:sub.end_byte].decode("utf-8", errors="ignore").strip()
                        if t and t not in ("public", "protected", "private"):
                            rels.append({"target": t, "type": "INHERITS", "line": line_num})

    elif language == "php":
        for child in node.children:
            if child.type == "base_clause":
                t = re.sub(r"^extends\s+", "", source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore").strip()).strip()
                if t:
                    rels.append({"target": t, "type": "INHERITS", "line": line_num})
            elif child.type == "class_interface_clause":
                t = re.sub(r"^implements\s+", "", source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore").strip()).strip()
                for sub_t in (s.strip() for s in t.split(",") if s.strip()):
                    rels.append({"target": sub_t, "type": "IMPLEMENTS", "line": line_num})

    elif language == "ruby":
        super_node = node.child_by_field_name("superclass") or next((c for c in node.children if c.type == "superclass"), None)
        if super_node:
            t = source_bytes[super_node.start_byte:super_node.end_byte].decode("utf-8", errors="ignore").strip("< ").strip()
            if t:
                rels.append({"target": t, "type": "INHERITS", "line": line_num})

    return rels

