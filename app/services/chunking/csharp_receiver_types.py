"""
Declared types of C# call receivers, so that `_toolService.PublishInstance()` is stored as
`ToolService.PublishInstance` and not as the bare `PublishInstance`.

A bare method name matches every class that has a method with that name: a controller, its
service, and the service's repository often all have `PublishInstance`. With the receiver's
declared type, trace_path and the topology graph connect the call to the correct class.

The receiver must be a simple name (`x` or `this.x`). Its type comes from the nearest scope that
declares it: a parameter, local variable, `foreach` variable, or lambda parameter of an enclosing
method; or a field, property, or primary-constructor parameter of the enclosing type. `var x = new T()`
gives `T`. A call without a receiver (`Method(...)` or `this.Method(...)`) gets the enclosing type when that
type declares the method. When no declaration is found (static calls, `var` without `new`, inherited
members), the call keeps the bare name.
"""

import re
from typing import Dict, Optional, Tuple

_TYPE_DECLARATIONS = frozenset({
    "class_declaration", "struct_declaration", "record_declaration",
    "record_struct_declaration", "interface_declaration",
})
_SCOPES = frozenset({
    "method_declaration", "constructor_declaration", "local_function_statement",
    "lambda_expression", "anonymous_method_expression", "accessor_declaration",
    "operator_declaration", "conversion_operator_declaration", "destructor_declaration",
})
_SKIP_TYPES = frozenset({
    "var", "dynamic", "object", "string", "bool", "byte", "sbyte", "char", "decimal", "double",
    "float", "int", "uint", "long", "ulong", "short", "ushort", "nint", "nuint",
})
_SIMPLE_RECEIVER = re.compile(r"^(?:this\.)?([A-Za-z_]\w*)$")

ScopeTypes = Dict[str, str]
TypeCache = Dict[Tuple[int, int, str], ScopeTypes]


def _text(node, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore").strip()


def _clean_type(node, source_bytes: bytes) -> Optional[str]:
    """`Ns.ToolService`, `ILogger<T>`, `ToolService?` -> the simple type name; None for `var`, arrays, built-ins."""
    if node is None or node.type in ("implicit_type", "predefined_type", "array_type", "tuple_type", "pointer_type"):
        return None
    raw = re.sub(r"<.*>", "", _text(node, source_bytes)).rstrip("?").strip()
    name = raw.rsplit(".", 1)[-1].split("::")[-1]
    if not re.fullmatch(r"[A-Za-z_]\w*", name) or name in _SKIP_TYPES:
        return None
    return name


def _declarator_name(declarator, source_bytes: bytes) -> Optional[str]:
    name_node = declarator.child_by_field_name("name")
    if name_node is None:
        name_node = next((c for c in declarator.children if c.type == "identifier"), None)
    return _text(name_node, source_bytes) if name_node is not None else None


def _created_type(declarator, source_bytes: bytes) -> Optional[str]:
    """`var x = new T(...)` -> T (the creation must be the whole initializer, not a nested argument)."""
    for child in declarator.children:
        target = child
        if target.type == "equals_value_clause":
            target = next((c for c in target.children if c.is_named), None)
        if target is not None and target.type == "object_creation_expression":
            return _clean_type(target.child_by_field_name("type"), source_bytes)
    return None


def _add_variable_declaration(decl, source_bytes: bytes, out: ScopeTypes) -> None:
    declared = _clean_type(decl.child_by_field_name("type"), source_bytes)
    for child in decl.children:
        if child.type != "variable_declarator":
            continue
        name = _declarator_name(child, source_bytes)
        var_type = declared or _created_type(child, source_bytes)
        if name and var_type:
            out.setdefault(name, var_type)


def _add_parameters(param_list, source_bytes: bytes, out: ScopeTypes) -> None:
    for param in param_list.children:
        if param.type != "parameter":
            continue
        name_node, type_node = param.child_by_field_name("name"), param.child_by_field_name("type")
        p_type = _clean_type(type_node, source_bytes)
        if name_node is not None and p_type:
            out.setdefault(_text(name_node, source_bytes), p_type)


def _scope_types(scope, source_bytes: bytes) -> ScopeTypes:
    """Parameters and locals of one method-like scope (nested methods and types are not entered)."""
    out: ScopeTypes = {}
    for child in scope.children:
        if child.type == "parameter_list":
            _add_parameters(child, source_bytes, out)
    stack = [c for c in scope.children if c.type != "parameter_list"]
    while stack:
        node = stack.pop()
        if node.type in _SCOPES or node.type in _TYPE_DECLARATIONS:
            continue
        if node.type == "variable_declaration" and node.parent is not None and node.parent.type != "field_declaration":
            _add_variable_declaration(node, source_bytes, out)
        elif node.type == "foreach_statement":
            f_type = _clean_type(node.child_by_field_name("type"), source_bytes)
            left = node.child_by_field_name("left")
            if f_type and left is not None and left.type == "identifier":
                out.setdefault(_text(left, source_bytes), f_type)
        stack.extend(node.children)
    return out


def _type_member_types(type_decl, source_bytes: bytes) -> ScopeTypes:
    """Fields, properties, and primary-constructor parameters of one type declaration."""
    out: ScopeTypes = {}
    for child in type_decl.children:
        if child.type == "parameter_list":
            _add_parameters(child, source_bytes, out)
        elif child.type == "declaration_list":
            for member in child.children:
                if member.type in ("field_declaration", "event_field_declaration"):
                    for decl in member.children:
                        if decl.type == "variable_declaration":
                            _add_variable_declaration(decl, source_bytes, out)
                elif member.type == "property_declaration":
                    p_type = _clean_type(member.child_by_field_name("type"), source_bytes)
                    name_node = member.child_by_field_name("name")
                    if p_type and name_node is not None:
                        out.setdefault(_text(name_node, source_bytes), p_type)
    return out


def _cached(cache: TypeCache, node, source_bytes: bytes, builder) -> ScopeTypes:
    key = (node.start_byte, node.end_byte, node.type)
    if key not in cache:
        cache[key] = builder(node, source_bytes)
    return cache[key]


def receiver_type(call_node, source_bytes: bytes, cache: TypeCache) -> Optional[str]:
    """Declared type of the receiver of `receiver.Method(...)`, or None when it is not known."""
    fn_node = call_node.child_by_field_name("function")
    if fn_node is None or fn_node.type != "member_access_expression":
        return None
    receiver = fn_node.child_by_field_name("expression")
    if receiver is None:
        return None
    m = _SIMPLE_RECEIVER.match(_text(receiver, source_bytes))
    if not m:
        return None
    name, via_this = m.group(1), receiver.type == "member_access_expression"
    node = call_node.parent
    while node is not None:
        if node.type in _SCOPES and not via_this:
            found = _cached(cache, node, source_bytes, _scope_types).get(name)
            if found:
                return found
        elif node.type in _TYPE_DECLARATIONS:
            return _cached(cache, node, source_bytes, _type_member_types).get(name)
        node = node.parent
    return None


def _declared_methods(type_decl, source_bytes: bytes) -> ScopeTypes:
    """Method names declared directly in a type (name -> type name), for calls without a receiver."""
    name_node = type_decl.child_by_field_name("name")
    type_name = _text(name_node, source_bytes) if name_node is not None else ""
    out: ScopeTypes = {}
    for child in type_decl.children:
        if child.type == "declaration_list" and type_name:
            for member in child.children:
                m_name = member.child_by_field_name("name") if member.type == "method_declaration" else None
                if m_name is not None:
                    out.setdefault(_text(m_name, source_bytes), type_name)
    return out


def own_class_type(call_node, source_bytes: bytes, target: str, cache: TypeCache) -> Optional[str]:
    """The enclosing type for `Method(...)` or `this.Method(...)` when that type declares `Method`, else None."""
    fn_node = call_node.child_by_field_name("function")
    if fn_node is None:
        return None
    if fn_node.type == "member_access_expression":
        receiver = fn_node.child_by_field_name("expression")
        if receiver is None or receiver.type != "this":
            return None
    elif fn_node.type not in ("identifier", "generic_name"):
        return None
    node = call_node.parent
    while node is not None and node.type not in _TYPE_DECLARATIONS:
        node = node.parent
    if node is None:
        return None
    key = (node.start_byte, node.end_byte, "declared_methods")
    if key not in cache:
        cache[key] = _declared_methods(node, source_bytes)
    return cache[key].get(target)


def qualify_csharp_call(call_node, source_bytes: bytes, target: str, cache: TypeCache) -> str:
    """`Type.target` when the receiver's declared type (or, without a receiver, the own class) is known."""
    if call_node.type != "invocation_expression" or not target or "." in target:
        return target
    r_type = receiver_type(call_node, source_bytes, cache) or own_class_type(call_node, source_bytes, target, cache)
    return f"{r_type}.{target}" if r_type else target
