import os
import re
import json
import logging
from typing import Optional, List, Dict, Any
from app.services.database import get_db_connection

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

_NOISY_HUB_NAMES = frozenset({
    "constructor", "__init__", "__new__", "__str__", "__repr__",
    "start", "stop", "main", "init", "setup", "teardown",
    "dispose", "disposeasync", "tostring", "equals", "gethashcode",
    "anonymous", "configure", "build", "render", "ngoninit",
    "componentdidmount", "useeffect",
})


def detect_entry_points(filepaths: List[str]) -> List[str]:
    entry_points = []
    for fp in filepaths:
        clean_fp = fp.split("://")[-1] if "://" in fp else fp
        norm_fp = clean_fp.replace("\\", "/")
        filename = os.path.basename(norm_fp)

        # Exact match or pattern match
        if filename in ("main.py", "index.ts", "index.js", "Program.cs", "Dockerfile", "main.go", "app.py", "server.js", "server.ts", "main.tsx", "App.tsx"):
            entry_points.append(norm_fp)
        elif any(re.search(pat, norm_fp, re.IGNORECASE) for pat in ENTRY_POINT_PATTERNS):
            entry_points.append(norm_fp)

    return sorted(list(set(entry_points)))


def synthesize_architecture(repo: Optional[str] = None) -> str:
    """
    Synthesizes language distributions, key entry points, primary frameworks/modules,
    route counts, and active ADRs into a compact JSON summary (<1,000 tokens).
    """
    try:
        with get_db_connection() as conn:
            # 1. Base files query
            try:
                ip_rows = conn.execute("SELECT path, repo FROM indexed_paths").fetchall()
                local_roots = [r["path"].replace("\\", "/").rstrip("/") for r in ip_rows if r["path"]]
            except Exception:
                local_roots = []
            if repo:
                file_rows = conn.execute("SELECT filepath, doc_type, language FROM indexed_files WHERE repo = ?", (repo,)).fetchall()
                adr_rows = conn.execute("SELECT id, title, status FROM architecture_decision_records WHERE repo = ? ORDER BY id ASC", (repo,)).fetchall()
                symbol_rows = conn.execute("SELECT id, filepath, name, full_symbol, kind, signature, repo FROM ast_symbols WHERE repo = ?", (repo,)).fetchall()
                rel_rows = conn.execute(
                    "SELECT source_symbol_id, target_symbol, relationship_type FROM ast_relationships WHERE repo = ?",
                    (repo,)
                ).fetchall()
                indexed_route_count = conn.execute("SELECT count(*) FROM api_routes WHERE repo = ?", (repo,)).fetchone()[0]
            else:
                file_rows = conn.execute("SELECT filepath, doc_type, language, repo FROM indexed_files").fetchall()
                adr_rows = conn.execute("SELECT id, title, status, repo FROM architecture_decision_records ORDER BY id ASC").fetchall()
                symbol_rows = conn.execute("SELECT id, filepath, name, full_symbol, kind, signature, repo FROM ast_symbols").fetchall()
                rel_rows = conn.execute(
                    "SELECT source_symbol_id, target_symbol, relationship_type FROM ast_relationships"
                ).fetchall()
                indexed_route_count = conn.execute("SELECT count(*) FROM api_routes").fetchone()[0]

        def _rel_fp(raw_fp: str) -> str:
            clean = (raw_fp.split("://")[-1] if "://" in raw_fp else raw_fp).replace("\\", "/")
            for root_p in local_roots:
                if root_p and clean.startswith(root_p + "/"):
                    return clean[len(root_p) + 1:]
            return clean

        total_files = len(file_rows)
        if total_files == 0:
            return json.dumps({
                "repo": repo,
                "total_files": 0,
                "languages": [],
                "manifests": [],
                "entry_points": [],
                "modules": [],
                "hub_symbols": [],
                "api_surface": {"estimated_routes": 0, "namespaces": []},
                "active_adrs": [],
            })

        filepaths = [_rel_fp(r["filepath"]) for r in file_rows]

        # 2. Languages & Manifests Distribution
        lang_counts: Dict[str, int] = {}
        detected_manifests: List[str] = []

        for r in file_rows:
            raw_lang = (r["language"] or "text").strip()
            lang_map = {"python": "Python", "typescript": "TypeScript", "javascript": "JavaScript", "go": "Go", "csharp": "C#", "c_sharp": "C#", "cpp": "C++", "rust": "Rust", "ruby": "Ruby", "markdown": "Markdown", "toml": "TOML"}
            lang = lang_map.get(raw_lang.lower(), raw_lang.capitalize())
            lang_counts[lang] = lang_counts.get(lang, 0) + 1

            clean_fp = _rel_fp(r["filepath"])
            fname = os.path.basename(clean_fp)
            if fname in MANIFEST_FILENAMES:
                label = f"{fname} ({MANIFEST_FILENAMES[fname]})"
                if label not in detected_manifests:
                    detected_manifests.append(label)
            elif fname.endswith(".csproj"):
                label = f"{fname} (.NET C# Project)"
                if label not in detected_manifests:
                    detected_manifests.append(label)

        languages = []
        for l_name, l_cnt in sorted(lang_counts.items(), key=lambda x: x[1], reverse=True):
            pct = round((l_cnt / total_files) * 100, 1)
            languages.append({"language": l_name, "files": l_cnt, "percent": pct})

        # 3. Entry Points Detection
        entry_points = detect_entry_points(filepaths)

        # 4. Key Modules & Hub Symbols (ranked by call/inheritance degree, excluding generic boilerplate & test fixtures)
        def _is_test_or_asset_path(p: str) -> bool:
            norm = p.replace("\\", "/").strip("/")
            parts = [seg.lower() for seg in norm.split("/") if seg]
            if any(seg in ("tests", "test", "__tests__", "wwwroot", "_framework", "dist", "build", "node_modules", "vendor", "coverage") for seg in parts):
                return True
            if norm.lower().startswith("www/assets"):
                return True
            bname = os.path.basename(norm)
            if bname.startswith("test_") or bname.endswith(("_test.py", "_test.go", ".test.ts", ".test.tsx", ".test.js", ".spec.ts", ".spec.tsx", ".spec.js", "Tests.cs", "Test.cs")):
                return True
            return False

        prod_module_counts: Dict[str, int] = {}
        all_module_counts: Dict[str, int] = {}
        top_symbols: List[Dict[str, Any]] = []

        inbound_counts: Dict[str, int] = {}
        outbound_counts: Dict[str, int] = {}
        for rel in rel_rows:
            rel_type = (rel["relationship_type"] or "").upper()
            if rel_type == "IMPORTS":
                continue
            src_id = rel["source_symbol_id"]
            tgt = rel["target_symbol"]
            if src_id:
                outbound_counts[src_id] = outbound_counts.get(src_id, 0) + 1
            if tgt:
                inbound_counts[tgt] = inbound_counts.get(tgt, 0) + 1
                if "." in tgt:
                    short_tgt = tgt.rsplit(".", 1)[-1]
                    inbound_counts[short_tgt] = inbound_counts.get(short_tgt, 0) + 1

        prod_scored_symbols = []
        all_scored_symbols = []
        seen_file_syms = set()
        for sr in symbol_rows:
            fp = _rel_fp(sr["filepath"])
            name = (sr["name"] or "").strip()
            full_sym = (sr["full_symbol"] or name).strip()
            kind = (sr["kind"] or "").lower()

            dedup_sym_key = (fp, full_sym, kind)
            if dedup_sym_key in seen_file_syms:
                continue
            seen_file_syms.add(dedup_sym_key)

            folder = os.path.dirname(fp) or "root"
            is_test_or_asset = _is_test_or_asset_path(fp)
            all_module_counts[folder] = all_module_counts.get(folder, 0) + 1
            if not is_test_or_asset:
                prod_module_counts[folder] = prod_module_counts.get(folder, 0) + 1

            if not name or name.lower() in _NOISY_HUB_NAMES or kind == "arrow_function":
                continue
            if kind in ("constructor", "variable", "property", "field"):
                continue

            sym_id = sr["id"] if "id" in sr.keys() else None
            in_deg = inbound_counts.get(full_sym, 0) + (inbound_counts.get(name, 0) if full_sym != name else 0)
            out_deg = outbound_counts.get(sym_id, 0) if sym_id else 0
            kind_bonus = 2 if kind in ("class", "interface", "struct", "class_declaration", "class_definition", "interface_declaration", "struct_declaration") else 1
            score = (in_deg * 3) + out_deg + kind_bonus
            item_tuple = (score, in_deg + out_deg, full_sym, name, sr["kind"], fp)
            all_scored_symbols.append(item_tuple)

            lower_name = name.lower()
            if not is_test_or_asset and not lower_name.startswith(("test_", "setup_", "teardown_")) and not name.endswith(("Tests", "Test")):
                prod_scored_symbols.append(item_tuple)

        effective_modules = prod_module_counts if prod_module_counts else all_module_counts
        sorted_modules = [mod for mod, _ in sorted(effective_modules.items(), key=lambda x: x[1], reverse=True)[:5]]

        scored_symbols = prod_scored_symbols if prod_scored_symbols else all_scored_symbols
        scored_symbols.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        seen_hub_keys = set()
        for _, degree, full_sym, name, kind, fp in scored_symbols:
            dedup_key = (full_sym, fp)
            if dedup_key in seen_hub_keys:
                continue
            seen_hub_keys.add(dedup_key)
            hub_entry: Dict[str, Any] = {
                "name": full_sym if "." in full_sym else name,
                "kind": kind,
                "file": fp,
            }
            if degree > 0:
                hub_entry["connections"] = degree
            top_symbols.append(hub_entry)
            if len(top_symbols) >= 6:
                break

        # Fallback if all symbols were filtered out
        if not top_symbols:
            for sr in symbol_rows[:6]:
                fp = (sr["filepath"].split("://")[-1] if "://" in sr["filepath"] else sr["filepath"]).replace("\\", "/")
                top_symbols.append({
                    "name": sr["full_symbol"] or sr["name"],
                    "kind": sr["kind"],
                    "file": fp,
                })

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
            clean_fp = (fp.split("://")[-1] if "://" in fp else fp).replace("\\", "/")
            if any(p in clean_fp for p in ["api/", "routes/", "controllers/", "webhooks/", "v1/", "v2/"]):
                for ns in ["/api", "/v1", "/v2", "/webhooks", "/auth", "/health"]:
                    if ns in clean_fp and ns not in namespaces:
                        namespaces.append(ns)
            if re.search(r"(route|api|controller|endpoint)", clean_fp, re.IGNORECASE):
                route_count += 1

        route_count = max(int(indexed_route_count or 0), route_count, len(namespaces))

        # 6. Active ADRs
        active_adrs = []
        for adr in adr_rows:
            st = adr["status"].upper()
            if st in ("ACCEPTED", "PROPOSED"):
                active_adrs.append({"id": adr["id"], "title": adr["title"], "status": st})

        return json.dumps({
            "repo": repo,
            "total_files": total_files,
            "languages": languages,
            "manifests": detected_manifests,
            "entry_points": entry_points[:8],
            "modules": sorted_modules,
            "hub_symbols": top_symbols[:6],
            "api_surface": {
                "estimated_routes": route_count,
                "namespaces": namespaces,
            },
            "active_adrs": active_adrs[:10],
        })
    except Exception as e:
        logger.error(f"Error synthesizing architecture overview: {e}")
        return json.dumps({"error": f"Error generating architecture overview: {str(e)}"})
