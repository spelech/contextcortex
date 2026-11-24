"""Error terms for `diagnose_issue`: words from the issue text that show which code is related to the fault.

The terms rank the methods on a call path and select the evidence lines in each method. A small
vocabulary table adds the code words that usually go with common error words (for example, an
`ExecuteReader` error adds `query`, `command`, `transaction`, and `connection`). The table is
language-neutral: the terms are matched against camelCase and snake_case parts of the code lines.
"""

import re
from typing import Dict, Iterable, List, Optional

from app.services.stack_trace_parser import RE_EXCEPTION_NAME, RE_SYMBOL_CANDIDATE

# Weight of each term kind. Vocabulary terms and code identifiers from the issue are strong signals;
# plain words from the error message are weak signals.
VOCABULARY_WEIGHT = 3.0
IDENTIFIER_WEIGHT = 3.0
EXCEPTION_WEIGHT = 2.0
MESSAGE_WORD_WEIGHT = 1.0
STRONG_WEIGHT = 3.0
MAX_TERMS = 24

# Trigger (lowercase text in the issue) -> code words that usually go with that error.
ERROR_VOCABULARY: Dict[str, tuple] = {
    "executereader": ("query", "execute", "command", "transaction", "connection"),
    "executenonquery": ("execute", "command", "transaction", "connection"),
    "executescalar": ("execute", "command", "transaction", "connection"),
    "transaction": ("transaction", "commit", "rollback"),
    "connection": ("connection", "open"),
    "deadlock": ("deadlock", "lock", "transaction"),
    "timeout": ("timeout", "cancellation", "wait"),
    "timed out": ("timeout", "cancellation", "wait"),
    "nullreference": ("null",),
    "null reference": ("null",),
    "nullpointer": ("null",),
    "nonetype": ("none",),
    "undefined": ("undefined", "null"),
    "keyerror": ("key",),
    "keynotfound": ("key",),
    "indexoutofrange": ("index", "count", "length"),
    "indexerror": ("index", "len"),
    "outofrange": ("index", "count", "length"),
    "unauthorized": ("authorize", "permission", "access", "role"),
    "forbidden": ("authorize", "permission", "access", "role"),
    "access denied": ("permission", "access", "role"),
    "permission": ("permission", "access", "role"),
    "duplicate": ("insert", "unique", "exists"),
    "unique constraint": ("insert", "unique", "exists"),
    "foreign key": ("delete", "insert", "reference"),
    "serializ": ("serialize", "deserialize", "json"),
    "disposed": ("dispose", "using"),
    "deserializ": ("deserialize", "json"),
    "concurren": ("lock", "concurrent"),
    "race condition": ("lock", "concurrent"),
    "overflow": ("overflow", "checked"),
    "divide by zero": ("divide", "zero"),
    "zerodivision": ("divide", "zero"),
}

_STOP_WORDS = {
    "about", "above", "across", "actual", "actually", "after", "again", "against", "along", "already", "also",
    "although", "always", "anything", "anyone", "appear", "appears", "appeared", "appearing", "around", "assigned",
    "away", "back", "because", "been", "before", "behavior", "being", "below", "between", "both", "button",
    "cannot", "case", "check", "checked", "checking", "click", "clicked", "clicking", "client", "clients",
    "come", "comes", "came", "could", "currently", "customer", "customers", "does", "doesn", "doing", "done",
    "down", "during", "each", "error", "even", "every", "everything", "example", "exception", "expected",
    "fails", "failed", "failing", "find", "fine", "first", "found", "from", "further", "gave", "gets", "getting",
    "give", "gives", "goes", "going", "good", "happened", "happening", "happens", "have", "having", "here",
    "however", "http", "instance", "instead", "into", "issue", "just", "keep", "keeps", "kept", "know", "knows",
    "left", "logs", "look", "looked", "looking", "looks", "made", "make", "makes", "many", "maybe", "message",
    "more", "most", "much", "need", "needs", "never", "normally", "nothing", "object", "occurred", "often",
    "only", "onto", "other", "otherwise", "over", "page", "please", "possibly", "pretty", "previously", "problem",
    "probably", "property", "quite", "rather", "really", "recently", "report", "reported", "reports", "requires",
    "return", "returns", "right", "same", "screen", "seeing", "seems", "seen", "should", "shows", "since",
    "some", "someone", "something", "sometimes", "still", "sure", "system", "take", "takes", "than", "that",
    "their", "them", "then", "there", "therefore", "these", "they", "thing", "think", "this", "those", "though",
    "through", "thrown", "throws", "today", "took", "toward", "towards", "tried", "trying", "under", "unless",
    "until", "upon", "used", "users", "using", "usually", "value", "very", "want", "wants", "well", "went",
    "when", "whenever", "where", "which", "while", "will", "with", "within", "without", "working", "works",
    "would", "wrong", "yesterday",
}
_IDENT_PARTS = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,}")
_GENERIC_EXCEPTION_PARTS = {"invalid", "operation", "exception", "error", "argument", "system", "runtime"}
_HEX_ID_RE = re.compile(r"^[0-9a-f]{8,}$")
_DATA_CODE_RE = re.compile(r"^(?:[a-z]{1,4}[-_]?\d{3,}|\d{2,}[-_][a-z0-9]{2,}|[a-z0-9]{2,}-\d{2,}(?:-[a-z0-9]+)*)$")


def is_data_value_token(token: str) -> bool:
    """True for alphanumeric data values (product numbers, SKUs, IDs, hex hashes) that are not code terms."""
    t = (token or "").strip().lower()
    if not t:
        return True
    alnum = [c for c in t if c.isalnum()]
    digits = sum(1 for c in alnum if c.isdigit())
    if digits == 0:
        return False
    if digits == len(alnum):
        return True
    if _HEX_ID_RE.fullmatch(t):
        return True
    # Keep COBOL paragraph/section identifiers that have >= 2 alphabetic words (e.g. 1000-calc-tax).
    alpha_segments = [seg for seg in re.split(r"[-_]", t) if seg.isalpha() and len(seg) >= 2]
    if "-" in t and len(alpha_segments) >= 2:
        return False
    if _DATA_CODE_RE.fullmatch(t):
        return True
    if digits >= 3 and (digits / max(1, len(alnum))) >= 0.4:
        return True
    return False


def identifier_parts(text: str) -> List[str]:
    """Splits identifiers in a line into lowercase camelCase / snake_case parts."""
    parts: List[str] = []
    for token in re.findall(r"[A-Za-z0-9]+", text or ""):
        parts.extend(p.lower() for p in _IDENT_PARTS.findall(token))
    return parts


def _add(terms: Dict[str, float], term: str, weight: float) -> None:
    term = term.lower().strip()
    if len(term) >= 3 and term not in _STOP_WORDS and not is_data_value_token(term):
        terms[term] = max(terms.get(term, 0.0), weight)


def _error_lines(text: str, exceptions: Iterable[str]) -> List[str]:
    """Lines that carry the error message (they name an exception or an error)."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    keys = [e.lower() for e in exceptions] + ["error", "exception", "failed", "abend"]
    picked = [ln for ln in lines if any(k in ln.lower() for k in keys)]
    return picked or lines[:3]


def extract_error_terms(issue_text: str, signals: Optional[Dict[str, List]] = None) -> Dict[str, float]:
    """Returns {term: weight} for the issue: vocabulary words, code identifiers, exceptions, error-message words."""
    signals = signals or {}
    text = issue_text or ""
    low = text.lower()
    terms: Dict[str, float] = {}
    exceptions = list(signals.get("exceptions") or []) + RE_EXCEPTION_NAME.findall(text)

    for trigger, words in ERROR_VOCABULARY.items():
        if trigger in low:
            for word in words:
                _add(terms, word, VOCABULARY_WEIGHT)

    identifiers = list(signals.get("symbols") or []) + RE_SYMBOL_CANDIDATE.findall(text)
    identifiers += re.findall(r"\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b", text)
    for ident in identifiers:
        last = ident.split(".")[-1]
        if last in exceptions or RE_EXCEPTION_NAME.fullmatch(last):
            continue
        _add(terms, last, IDENTIFIER_WEIGHT)

    for exc in exceptions:
        name = exc.split(".")[-1]
        _add(terms, name, EXCEPTION_WEIGHT)
        for part in identifier_parts(name):
            if part not in _GENERIC_EXCEPTION_PARTS:
                _add(terms, part, EXCEPTION_WEIGHT)

    for line in _error_lines(text, exceptions):
        for word in _WORD.findall(line):
            if "_" not in word and not any(c.isupper() for c in word[1:]):
                _add(terms, word, MESSAGE_WORD_WEIGHT)

    ranked = sorted(terms.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_TERMS]
    return dict(ranked)


def line_term_hits(line: str, terms: Dict[str, float]) -> Dict[str, float]:
    """Terms that a code line contains: a whole camelCase/snake_case part, or a substring for long terms."""
    if not line or not terms:
        return {}
    parts = set(identifier_parts(line))
    low = line.lower()
    hits = {}
    for term, weight in terms.items():
        if term in parts or (len(term) >= 5 and term in low):
            hits[term] = weight
    return hits


def strong_terms(terms: Dict[str, float]) -> Dict[str, float]:
    return {t: w for t, w in terms.items() if w >= STRONG_WEIGHT}


__all__ = ["ERROR_VOCABULARY", "extract_error_terms", "identifier_parts", "line_term_hits", "strong_terms"]
