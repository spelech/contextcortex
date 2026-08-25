import os
import re
import logging
from typing import Optional, List, Dict, Any
from app.services.db import get_db_connection

logger = logging.getLogger("contextcortex.architecture")

ENTRY_POINT_PATTERNS = [
    r"(^|/)(main|index|app|server|Program|manage|run)\.(py|ts|js|go|cs|cpp|rs|rb|java|php)$",
    r"(^|/)Dockerfile$",
    r"(^|/)docker-compose\.ya?ml$",
    r"(^|/)cmd/.+/main\.go$",
    r"(^|/)src/(index|main|app|server)\.(ts|js|jsx|tsx)$"
]

MANIFEST_FILENAMES = {
    "pyproject.toml": "Python (Poetry/Flit/Setuptools)",
    "requirements.txt": "Python (pip)",
    "package.json": "Node.js/TypeScript (npm/yarn/pnpm)",
    "go.mod": "Go Modules",
    "Cargo.toml": "Rust (Cargo)",
    "Dockerfile": "Docker Container",
    "docker-compose.yml": "Docker Compose",
    "docker-compose.yaml": "Docker Compose",
}

def detect_entry_points(filepaths: List[str]) -> List[str]:
    entry_points = []
    for fp in filepaths:
        clean_fp = fp.split("://")[-1] if "://" in fp else fp
        norm_fp = clean_fp.replace("\\", "/")
        filename = os.path.basename(norm_fp)

        # Exact match or pattern match
        if filename in ("main.py", "index.ts", "index.js", "Program.cs", "Dockerfile", "main.go", "app.py", "server.js", "server.ts"):
            entry_points.append(clean_fp)
        elif any(re.search(pat, norm_fp, re.IGNORECASE) for pat in ENTRY_POINT_PATTERNS):
            entry_points.append(clean_fp)

    return sorted(list(set(entry_points)))

def synthesize_architecture(repo: Optional[str] = None) -> str:
    """
    Synthesizes language distributions, key entry points, primary frameworks/modules,
    route counts, and active ADRs into a concise summary (<1,000 tokens).
    """
    try:
        with get_db_connection() as conn:
            # 1. Base files query
            if repo:
                file_rows = conn.execute("SELECT filepath, doc_type, language FROM indexed_files WHERE repo = ?", (repo,)).fetchall()
                adr_rows = conn.execute("SELECT id, title, status FROM architecture_decision_records WHERE repo = ? ORDER BY id ASC", (repo,)).fetchall()
                symbol_rows = conn.execute("SELECT filepath, name, kind, signature FROM ast_symbols WHERE repo = ?", (repo,)).fetchall()
            else:
                file_rows = conn.execute("SELECT filepath, doc_type, language, repo FROM indexed_files").fetchall()
                adr_rows = conn.execute("SELECT id, title, status, repo FROM architecture_decision_records ORDER BY id ASC").fetchall()
                symbol_rows = conn.execute("SELECT filepath, name, kind, signature, repo FROM ast_symbols").fetchall()

        total_files = len(file_rows)
        if total_files == 0:
            target_str = f"repository '{repo}'" if repo else "all registered repositories"
            return f"No indexed architecture data available for {target_str}."

        filepaths = [r["filepath"] for r in file_rows]

        # 2. Languages & Manifests Distribution
        lang_counts: Dict[str, int] = {}
        detected_manifests: List[str] = []

        for r in file_rows:
            raw_lang = (r["language"] or "text").strip()
            lang_map = {"python": "Python", "typescript": "TypeScript", "javascript": "JavaScript", "go": "Go", "csharp": "C#", "cpp": "C++", "rust": "Rust", "ruby": "Ruby", "markdown": "Markdown", "toml": "TOML"}
            lang = lang_map.get(raw_lang.lower(), raw_lang.capitalize())
            lang_counts[lang] = lang_counts.get(lang, 0) + 1

            clean_fp = r["filepath"].split("://")[-1] if "://" in r["filepath"] else r["filepath"]
            fname = os.path.basename(clean_fp)
            if fname in MANIFEST_FILENAMES:
                label = f"{fname} ({MANIFEST_FILENAMES[fname]})"
                if label not in detected_manifests:
                    detected_manifests.append(label)
            elif fname.endswith(".csproj"):
                label = f"{fname} (.NET C# Project)"
                if label not in detected_manifests:
                    detected_manifests.append(label)

        lang_summary_items = []
        for l_name, l_cnt in sorted(lang_counts.items(), key=lambda x: x[1], reverse=True):
            pct = (l_cnt / total_files) * 100
            lang_summary_items.append(f"{l_name}: {l_cnt} files ({pct:.1f}%)")

        # 3. Entry Points Detection
        entry_points = detect_entry_points(filepaths)

        # 4. Key Modules & Hub Symbols
        module_counts: Dict[str, int] = {}
        top_symbols: List[str] = []

        for sr in symbol_rows:
            fp = sr["filepath"].split("://")[-1] if "://" in sr["filepath"] else sr["filepath"]
            folder = os.path.dirname(fp) or "root"
            module_counts[folder] = module_counts.get(folder, 0) + 1

        sorted_modules = [mod for mod, _ in sorted(module_counts.items(), key=lambda x: x[1], reverse=True)[:5]]

        # Key symbols (functions/classes)
        for sr in symbol_rows[:10]:
            kind = sr["kind"]
            name = sr["name"]
            top_symbols.append(f"`{name}` ({kind})")

        # 5. API Surface Summary
        route_patterns = [
            r"@(app|router|api|server|v1)\.(get|post|put|delete|patch|options|head|route)",
            r"router\.(get|post|put|delete|patch)",
            r"app\.(get|post|put|delete|patch)",
            r"http\.HandleFunc",
            r"\[Http(Get|Post|Put|Delete|Patch|Head)\]"
        ]

        route_count = 0
        namespaces: List[str] = []

        for sr in symbol_rows:
            sig = sr["signature"] or ""
            name = sr["name"] or ""
            combined = f"{name} {sig}"
            if any(re.search(pat, combined, re.IGNORECASE) for pat in route_patterns):
                route_count += 1

        for fp in filepaths:
            clean_fp = fp.split("://")[-1] if "://" in fp else fp
            if any(p in clean_fp for p in ["api/", "routes/", "controllers/", "webhooks/", "v1/", "v2/"]):
                for ns in ["/api", "/v1", "/v2", "/webhooks", "/auth", "/health"]:
                    if ns in clean_fp and ns not in namespaces:
                        namespaces.append(ns)
            if re.search(r"(route|api|controller|endpoint)", clean_fp, re.IGNORECASE):
                route_count += 1

        # Deduplicate estimated routes minimum
        route_count = max(route_count, len(namespaces))

        # 6. Active ADRs
        active_adrs = []
        for adr in adr_rows:
            st = adr["status"].upper()
            if st in ("ACCEPTED", "PROPOSED"):
                active_adrs.append(f"- **{adr['id']}**: {adr['title']} (`{st}`)")

        # --- Build Markdown Summary ---
        header_title = f"# Architecture Overview: {repo}" if repo else "# Global Architecture Overview"
        out = [header_title, ""]

        out.append("### 1. Language & Tech Stack Distribution")
        out.append("- **Languages:** " + ", ".join(lang_summary_items))
        if detected_manifests:
            out.append("- **Framework & Manifest Configs:** " + ", ".join(detected_manifests))
        out.append("")

        out.append("### 2. Entry Points")
        if entry_points:
            for ep in entry_points[:8]:
                out.append(f"- `{ep}`")
        else:
            out.append("- *No explicit entry points matched heuristic patterns.*")
        out.append("")

        out.append("### 3. Key Modules & Hub Symbols")
        if sorted_modules:
            out.append(f"- **Primary Modules/Folders:** {', '.join([f'`{m}`' for m in sorted_modules])}")
        if top_symbols:
            out.append(f"- **Hub Symbols:** {', '.join(top_symbols[:6])}")
        out.append("")

        out.append("### 4. API Surface Summary")
        out.append(f"- **Detected HTTP Routes / Endpoints:** ~{route_count}")
        if namespaces:
            out.append(f"- **Prefix Namespaces:** {', '.join(namespaces)}")
        else:
            out.append("- **Prefix Namespaces:** Standard API routes & service handlers")
        out.append("")

        out.append("### 5. Active Architectural Decisions (ADRs)")
        if active_adrs:
            out.extend(active_adrs[:10])
        else:
            out.append("- *No active or accepted ADRs registered.*")

        return "\n".join(out)
    except Exception as e:
        logger.error(f"Error synthesizing architecture overview: {e}")
        return f"Error generating architecture overview: {str(e)}"
