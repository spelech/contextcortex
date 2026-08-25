import os
from typing import Dict, Any, Optional

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

