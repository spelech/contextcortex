from typing import List
from app.models.schemas import CodeRelationship, CodeSymbol
from app.services.chunking.symbol_extractor import get_node_text

def extract_ast_relationships(
    root_node,
    code_bytes: bytes,
    repo: str,
    filepath: str,
    language: str,
    symbols: List[CodeSymbol]
) -> List[CodeRelationship]:
    relationships: List[CodeRelationship] = []

    def get_enclosing_symbol(line_num: int) -> str:
        match = None
        for s in symbols:
            if s.start_line <= line_num <= s.end_line:
                if match is None or (s.end_line - s.start_line < match.end_line - match.start_line):
                    match = s
        return match.name if match else filepath

    def traverse(node):
        line_num = node.start_point[0] + 1
        source_sym = get_enclosing_symbol(line_num)

        # 1. Imports
        if language == "python" and node.type in ("import_statement", "import_from_statement"):
            text = get_node_text(node, code_bytes).strip()
            for child in node.children:
                if child.type == "dotted_name" or child.type == "relative_import":
                    target = get_node_text(child, code_bytes).strip()
                    relationships.append(CodeRelationship(
                        repo=repo,
                        source_filepath=filepath,
                        source_symbol=source_sym,
                        target_symbol=target,
                        relationship_type="IMPORTS",
                        line_number=line_num
                    ))
        elif language in ("javascript", "typescript", "tsx") and node.type in ("import_statement", "import_clause"):
            for child in node.children:
                if child.type == "string" or child.type == "import_specifier":
                    target = get_node_text(child, code_bytes).strip(" '\"`")
                    relationships.append(CodeRelationship(
                        repo=repo,
                        source_filepath=filepath,
                        source_symbol=source_sym,
                        target_symbol=target,
                        relationship_type="IMPORTS",
                        line_number=line_num
                    ))
        elif language == "go" and node.type in ("import_spec",):
            path_node = node.child_by_field_name("path")
            if path_node:
                target = get_node_text(path_node, code_bytes).strip(" '\"`")
                relationships.append(CodeRelationship(
                    repo=repo,
                    source_filepath=filepath,
                    source_symbol=source_sym,
                    target_symbol=target,
                    relationship_type="IMPORTS",
                    line_number=line_num
                ))

        # 2. Function & Method Calls
        if language == "python" and node.type == "call":
            func_node = node.child_by_field_name("function")
            if func_node:
                target_sym = get_node_text(func_node, code_bytes).strip()
                if "." in target_sym:
                    target_sym = target_sym.split(".")[-1]
                if target_sym and target_sym != source_sym:
                    relationships.append(CodeRelationship(
                        repo=repo,
                        source_filepath=filepath,
                        source_symbol=source_sym,
                        target_symbol=target_sym,
                        relationship_type="CALLS",
                        line_number=line_num
                    ))
        elif language in ("javascript", "typescript", "tsx") and node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                target_sym = get_node_text(func_node, code_bytes).strip()
                if "." in target_sym:
                    target_sym = target_sym.split(".")[-1]
                if target_sym and target_sym != source_sym:
                    relationships.append(CodeRelationship(
                        repo=repo,
                        source_filepath=filepath,
                        source_symbol=source_sym,
                        target_symbol=target_sym,
                        relationship_type="CALLS",
                        line_number=line_num
                    ))
        elif language == "go" and node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                target_sym = get_node_text(func_node, code_bytes).strip()
                if "." in target_sym:
                    target_sym = target_sym.split(".")[-1]
                if target_sym and target_sym != source_sym:
                    relationships.append(CodeRelationship(
                        repo=repo,
                        source_filepath=filepath,
                        source_symbol=source_sym,
                        target_symbol=target_sym,
                        relationship_type="CALLS",
                        line_number=line_num
                    ))
        elif language == "rust" and node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                target_sym = get_node_text(func_node, code_bytes).strip()
                if "::" in target_sym:
                    target_sym = target_sym.split("::")[-1]
                elif "." in target_sym:
                    target_sym = target_sym.split(".")[-1]
                if target_sym and target_sym != source_sym:
                    relationships.append(CodeRelationship(
                        repo=repo,
                        source_filepath=filepath,
                        source_symbol=source_sym,
                        target_symbol=target_sym,
                        relationship_type="CALLS",
                        line_number=line_num
                    ))
        elif language in ("c_sharp", "java") and node.type in ("invocation_expression", "method_invocation"):
            func_node = node.child_by_field_name("name") or node.child_by_field_name("expression")
            if func_node:
                target_sym = get_node_text(func_node, code_bytes).strip()
                if "." in target_sym:
                    target_sym = target_sym.split(".")[-1]
                if target_sym and target_sym != source_sym:
                    relationships.append(CodeRelationship(
                        repo=repo,
                        source_filepath=filepath,
                        source_symbol=source_sym,
                        target_symbol=target_sym,
                        relationship_type="CALLS",
                        line_number=line_num
                    ))

        # 3. Inheritance & Implementation
        if language == "python" and node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            args_node = node.child_by_field_name("superclasses")
            if name_node and args_node:
                c_name = get_node_text(name_node, code_bytes).strip()
                for arg in args_node.children:
                    if arg.type in ("identifier", "attribute"):
                        base_name = get_node_text(arg, code_bytes).strip()
                        relationships.append(CodeRelationship(
                            repo=repo,
                            source_filepath=filepath,
                            source_symbol=c_name,
                            target_symbol=base_name,
                            relationship_type="INHERITS",
                            line_number=line_num
                        ))
        elif language in ("javascript", "typescript", "tsx") and node.type in ("class_declaration", "class"):
            name_node = node.child_by_field_name("name")
            if name_node:
                c_name = get_node_text(name_node, code_bytes).strip()
                for child in node.children:
                    if child.type == "class_heritage":
                        for clause in child.children:
                            if clause.type == "extends_clause":
                                for base in clause.children:
                                    if base.type == "identifier":
                                        relationships.append(CodeRelationship(
                                            repo=repo,
                                            source_filepath=filepath,
                                            source_symbol=c_name,
                                            target_symbol=get_node_text(base, code_bytes).strip(),
                                            relationship_type="INHERITS",
                                            line_number=line_num
                                        ))
                            elif clause.type == "implements_clause":
                                for iface in clause.children:
                                    if iface.type in ("type_identifier", "identifier"):
                                        relationships.append(CodeRelationship(
                                            repo=repo,
                                            source_filepath=filepath,
                                            source_symbol=c_name,
                                            target_symbol=get_node_text(iface, code_bytes).strip(),
                                            relationship_type="IMPLEMENTS",
                                            line_number=line_num
                                        ))
        elif language in ("c_sharp", "java") and node.type in ("class_declaration",):
            name_node = node.child_by_field_name("name")
            if name_node:
                c_name = get_node_text(name_node, code_bytes).strip()
                for child in node.children:
                    if child.type in ("base_list", "super_interfaces", "extends_interfaces"):
                        for base in child.children:
                            if base.type in ("identifier", "type_identifier", "generic_name"):
                                b_text = get_node_text(base, code_bytes).strip()
                                rel_type = "IMPLEMENTS" if b_text.startswith("I") and len(b_text) > 1 and b_text[1].isupper() else "INHERITS"
                                relationships.append(CodeRelationship(
                                    repo=repo,
                                    source_filepath=filepath,
                                    source_symbol=c_name,
                                    target_symbol=b_text,
                                    relationship_type=rel_type,
                                    line_number=line_num
                                ))

        for child in node.children:
            traverse(child)

    traverse(root_node)
    return relationships
