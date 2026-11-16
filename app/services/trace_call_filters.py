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
