"""
Rules that keep trace_path trees on the production code of a repository.

- A private member is reachable only from its own class (or a class nested in it). A bare call such as
  `group.Count()` (LINQ) must not resolve to `private static int Count(...)` of an unrelated class.
- A call that does not resolve to an indexed symbol (a library call such as `string.IsNullOrEmpty`, or a call
  whose only candidates are test doubles) is not a tree node: trace_path lists its name in a compact
  `unresolved` list on the calling node.
- COBOL CALL targets are other programs (often in other libraries), not library noise, so they stay tree nodes.
"""

import re
from typing import Optional

_ATTRIBUTES = re.compile(r"\[[^\]]*\]")
_COBOL_SUFFIXES = (".cbl", ".cob", ".cpy")


def is_private_member(signature: Optional[str]) -> bool:
    """True for `private ...(` declarations (`private protected` is visible to derived classes, so it is not private here)."""
    head = _ATTRIBUTES.sub(" ", (signature or "").split("(", 1)[0])
    words = set(head.split())
    return "private" in words and "protected" not in words


def _owner(full_symbol: str) -> str:
    return full_symbol.rsplit(".", 1)[0] if "." in full_symbol else ""


def member_visible_from(candidate: dict, caller_sym: str) -> bool:
    """False when `candidate` is a private member of a class other than the caller's class (or a class that encloses it)."""
    if not is_private_member(candidate.get("signature")):
        return True
    cand_owner, caller_owner = _owner(candidate.get("full_symbol") or ""), _owner(caller_sym or "")
    if not cand_owner or not caller_owner:
        return True
    # Same class (with or without a namespace prefix), or a class nested in the candidate's class.
    return f".{cand_owner.split('.')[-1]}." in f".{caller_owner}."


def is_cobol_file(rel_path: Optional[str]) -> bool:
    return (rel_path or "").lower().endswith(_COBOL_SUFFIXES)


def _sig_mentions_type(sig_blob: str, type_name: str) -> bool:
    if not sig_blob or not type_name:
        return False
    short = type_name.split(".")[-1]
    return bool(re.search(rf"\b{re.escape(short)}\b", sig_blob))


def classify_caller_match(
    r_target: str,
    caller_sym: str,
    curr_sym: str,
    curr_ifaces: set,
    candidates: list,
    resolved: str,
    class_signatures: dict,
) -> Optional[str]:
    """Classifies a caller relationship for a qualified target as 'resolved', 'name_only', or None (skip).

    - Qualified calls matching `curr_sym` or one of its interfaces -> 'resolved'.
    - Calls from the target's own class, unique method names, DI-resolved calls, or callers whose
      class signatures reference the target class/interface -> 'resolved'.
    - Bare method calls that resolved to a different concrete class -> None (filtered out).
    - Undecidable bare method calls when multiple classes define that method -> 'name_only'.
    """
    if "." not in curr_sym or not r_target:
        return "resolved"
    if "." in r_target:
        if r_target == curr_sym or r_target.endswith(f".{curr_sym}") or curr_sym.endswith(f".{r_target}"):
            return "resolved"
        if r_target.rsplit(".", 1)[0].split(".")[-1] in curr_ifaces:
            return "resolved"
        return None
    curr_cls = curr_sym.rsplit(".", 1)[0]
    caller_cls = caller_sym.rsplit(".", 1)[0] if "." in caller_sym else caller_sym
    if caller_cls == curr_cls or caller_cls.endswith(f".{curr_cls}"):
        return "resolved"
    if len(candidates) < 2:
        return "resolved"
    if resolved == curr_sym or resolved.endswith(f".{curr_sym}"):
        return "resolved"
    if resolved != r_target:
        return None
    sig_blob = class_signatures.get(caller_cls.split(".")[-1], "")
    if _sig_mentions_type(sig_blob, curr_cls) or any(_sig_mentions_type(sig_blob, iface) for iface in curr_ifaces):
        return "resolved"
    return "name_only"
