"""
Source text decoding for indexing and storage.

Repositories can contain UTF-16 or UTF-32 text files (for example SQL Server scripts or
`pip freeze` output written by Windows PowerShell). Decoding those bytes as UTF-8 keeps a
NUL character between the letters, and PostgreSQL rejects NUL in `text` and `jsonb` values.
This module decodes such files correctly and removes any remaining NUL characters.
"""

import codecs
from typing import Any, Optional

# UTF-32 LE must come before UTF-16 LE: its BOM starts with the UTF-16 LE BOM.
_BOM_CODECS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)

_SNIFF_BYTES = 4096
_ZERO_RATIO_FOR_UTF16 = 0.3
_MAX_ZERO_RATIO_OTHER_LANE = 0.05


def strip_nul(value: Any) -> Any:
    """Returns the value with every NUL character removed from its strings (recursively for dicts, lists, tuples)."""
    if isinstance(value, str):
        return value.replace("\x00", "") if "\x00" in value else value
    if isinstance(value, dict):
        return {key: strip_nul(item) for key, item in value.items()}
    if isinstance(value, list):
        return [strip_nul(item) for item in value]
    if isinstance(value, tuple):
        return tuple(strip_nul(item) for item in value)
    return value


def _detect_bom(raw: bytes) -> Optional[tuple]:
    for bom, codec in _BOM_CODECS:
        if raw.startswith(bom):
            return bom, codec
    return None


def _guess_utf16_without_bom(sample: bytes) -> Optional[str]:
    """Recognizes UTF-16 text without a BOM: mostly-ASCII UTF-16 has a zero byte in every other position."""
    if len(sample) < 4:
        return None
    even_lane, odd_lane = sample[0::2], sample[1::2]
    even_zero = even_lane.count(0) / len(even_lane)
    odd_zero = odd_lane.count(0) / len(odd_lane)
    if odd_zero > _ZERO_RATIO_FOR_UTF16 and even_zero < _MAX_ZERO_RATIO_OTHER_LANE:
        return "utf-16-le"
    if even_zero > _ZERO_RATIO_FOR_UTF16 and odd_zero < _MAX_ZERO_RATIO_OTHER_LANE:
        return "utf-16-be"
    return None


def decode_source_bytes(raw: bytes) -> str:
    """Decodes file bytes as UTF-8, UTF-16, or UTF-32 (BOM or UTF-16 without BOM) and removes NUL characters."""
    bom_match = _detect_bom(raw)
    if bom_match:
        bom, codec = bom_match
        text = raw[len(bom):].decode(codec, errors="replace")
    else:
        utf16_codec = _guess_utf16_without_bom(raw[:_SNIFF_BYTES])
        if utf16_codec:
            text = raw.decode(utf16_codec, errors="replace")
        else:
            text = raw.decode("utf-8", errors="ignore")
    return strip_nul(text)


def read_source_text(path: str) -> str:
    """Reads a repository file for indexing with encoding detection; the result never contains NUL characters."""
    with open(path, "rb") as handle:
        return decode_source_bytes(handle.read())
