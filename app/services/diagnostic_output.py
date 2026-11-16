"""Compact default output for diagnose_issue.

Agents need the leads (route handler, frames, candidates as symbol + file + lines + source/score), not every snippet.
Semantic candidates are built without code when detail=False (see find_semantic_candidates(include_code=...));
this module cuts the relation lists and adds a hint that tells the agent how to get the full output.
"""

from typing import Any, Dict

COMPACT_MAX_RELATIONS = 3
COMPACT_HINT = (
    "Compact output: candidates have no code and caller/callee lists are cut to 3. "
    "Set detail=true for candidate code and full lists, or call read_file on a file and lines."
)


def compact_diagnosis(result: Dict[str, Any]) -> Dict[str, Any]:
    """Cuts caller/callee/external-caller lists to COMPACT_MAX_RELATIONS and adds the hint. Frame code is kept."""
    for entry in result.get("resolved_frames", []) + result.get("semantic_candidates", []):
        for key in ("callers", "callees"):
            if isinstance(entry.get(key), list):
                entry[key] = entry[key][:COMPACT_MAX_RELATIONS]
    for route in result.get("matched_routes", []):
        if isinstance(route.get("external_callers"), list):
            route["external_callers"] = route["external_callers"][:COMPACT_MAX_RELATIONS]
    result["hint"] = COMPACT_HINT
    return result
