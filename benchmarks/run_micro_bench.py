#!/usr/bin/env python3
"""Direct MCP tool latency & payload benchmark vs local ripgrep."""
import argparse
import asyncio
import json
import os
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

BENCH_DIR = Path(__file__).resolve().parent
SCRATCH = Path(os.environ.get("BENCH_WORKSPACE_DIR", str(BENCH_DIR / "workspace")))
RESULTS_DIR = Path(os.environ.get("BENCH_RESULTS_DIR", str(BENCH_DIR / "results")))
DEFAULT_MCP_URL = os.environ.get("CORTEX_MCP_URL", "http://127.0.0.1:18021/mcp")

DEFAULT_MCP_CASES = [
    {"label": "grep_code exact symbol", "tool": "grep_code", "args": {"pattern": "CompositeIdentityProvider", "repo": "csharp-mcp-router", "context_lines": 2}},
    {"label": "search CamelCase symbol (expect early-return)", "tool": "search", "args": {"query": "OAuthEgressTokenManager", "scope": "code", "repo": "csharp-mcp-router", "limit": 5}},
    {"label": "search multi-word agent query (expect early-return)", "tool": "search", "args": {"query": "execute_hybrid_search query router", "scope": "code", "repo": "contextcortex", "limit": 5}},
    {"label": "search conceptual natural language (expect semantic)", "tool": "search", "args": {"query": "how does authentication work in the gateway", "scope": "code", "repo": "csharp-mcp-router", "limit": 5}},
    {"label": "find_symbol AST lookup", "tool": "find_symbol", "args": {"name": "ResolveIdentityAsync", "repo": "csharp-mcp-router"}},
    {"label": "trace_path AST call graph", "tool": "trace_path", "args": {"symbol": "CompositeIdentityProvider", "repo": "csharp-mcp-router", "depth": 2}},
    {"label": "diagnose_issue stack trace", "tool": "diagnose_issue", "args": {"issue_text": "ValueError: Failed to parse provided SSH Private Key in app/remote_opencode_sync.py line 40", "repo": "llmlite-modelmanager"}},
]

DEFAULT_RG_CASES = [
    {"label": "rg exact symbol (csharp-mcp-router)", "cmd": ["rg", "-n", "-C", "2", "CompositeIdentityProvider", "{WORKSPACE}/csharp-mcp-router"]},
    {"label": "rg OAuthEgressTokenManager", "cmd": ["rg", "-n", "OAuthEgressTokenManager", "{WORKSPACE}/csharp-mcp-router"]},
    {"label": "rg multi-word files-with-matches", "cmd": ["rg", "-l", "execute_hybrid_search", "{WORKSPACE}/contextcortex"]},
    {"label": "rg auth middleware search", "cmd": ["rg", "-n", "Authentication", "{WORKSPACE}/csharp-mcp-router"]},
]


def load_cases(cases_file: Optional[Path]) -> Dict[str, List[Dict[str, Any]]]:
    if cases_file is None:
        return {"mcp": DEFAULT_MCP_CASES, "rg": DEFAULT_RG_CASES}
    data = json.loads(cases_file.read_text(encoding="utf-8"))
    return {"mcp": list(data.get("mcp", [])), "rg": list(data.get("rg", []))}


def extract_response_meta(text: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    meta = {k: parsed.get(k) for k in ("mode", "intent", "early_return", "total", "total_matches") if k in parsed}
    if not meta and isinstance(parsed.get("routing"), dict):
        meta = dict(parsed["routing"])
    return meta


async def run_suite(mcp_url: str, cases: Dict[str, List[Dict[str, Any]]], workspace: Path, runs: int) -> Dict[str, Any]:
    mcp_samples: Dict[int, List[float]] = {i: [] for i in range(len(cases["mcp"]))}
    mcp_latest: Dict[int, Dict[str, Any]] = {}

    async with streamablehttp_client(mcp_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for _ in range(runs):
                for idx, case in enumerate(cases["mcp"]):
                    t0 = time.monotonic()
                    res = await session.call_tool(case["tool"], case["args"])
                    ms = round((time.monotonic() - t0) * 1000, 1)
                    text = "".join(getattr(c, "text", "") for c in res.content)
                    mcp_samples[idx].append(ms)
                    mcp_latest[idx] = {
                        "label": case["label"],
                        "tool": case["tool"],
                        "chars": len(text),
                        "meta": extract_response_meta(text),
                    }

    mcp_rows = []
    for idx in range(len(cases["mcp"])):
        row = dict(mcp_latest[idx])
        row["samples_ms"] = mcp_samples[idx]
        row["median_ms"] = round(statistics.median(mcp_samples[idx]), 1)
        row["latency_ms"] = row["median_ms"]
        mcp_rows.append(row)
        print(f"[MCP] {row['label']}: {row['median_ms']} ms median (runs={row['samples_ms']}) | {row['chars']} chars | meta={row['meta']}")

    rg_samples: Dict[int, List[float]] = {i: [] for i in range(len(cases["rg"]))}
    rg_latest: Dict[int, Dict[str, Any]] = {}
    for _ in range(runs):
        for idx, case in enumerate(cases["rg"]):
            cmd = [part.replace("{WORKSPACE}", str(workspace)) for part in case["cmd"]]
            t0 = time.monotonic()
            proc = subprocess.run(cmd, capture_output=True, text=True)
            ms = round((time.monotonic() - t0) * 1000, 1)
            rg_samples[idx].append(ms)
            rg_latest[idx] = {"label": case["label"], "chars": len(proc.stdout), "returncode": proc.returncode}

    rg_rows = []
    for idx in range(len(cases["rg"])):
        row = dict(rg_latest[idx])
        row["samples_ms"] = rg_samples[idx]
        row["median_ms"] = round(statistics.median(rg_samples[idx]), 1)
        row["latency_ms"] = row["median_ms"]
        rg_rows.append(row)
        print(f"[RG ] {row['label']}: {row['median_ms']} ms median (runs={row['samples_ms']}) | {row['chars']} chars")

    return {"mcp_url": mcp_url, "runs": runs, "mcp": mcp_rows, "rg": rg_rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run direct ContextCortex MCP vs ripgrep micro-benchmarks.")
    parser.add_argument("--mcp-url", default=DEFAULT_MCP_URL, help="Streamable HTTP MCP URL")
    parser.add_argument("--cases-file", type=Path, default=None, help="Optional JSON file of mcp/rg cases")
    parser.add_argument("--workspace", type=Path, default=SCRATCH / "arm_b_workspace", help="Local clone workspace for rg")
    parser.add_argument("--runs", type=int, default=3, help="Number of timed passes per case (reports median)")
    parser.add_argument("--output", type=Path, default=RESULTS_DIR / "micro_bench.json", help="Output JSON path")
    args = parser.parse_args()

    cases = load_cases(args.cases_file)
    results = asyncio.run(run_suite(args.mcp_url, cases, args.workspace, max(1, args.runs)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Saved micro-benchmark results to {args.output}")


if __name__ == "__main__":
    main()
