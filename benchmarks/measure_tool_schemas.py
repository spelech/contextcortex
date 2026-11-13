#!/usr/bin/env python3
"""Measure MCP tools/list JSON character and estimated token footprint."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def measure_schemas(mcp_url: str) -> dict:
    async with streamablehttp_client(mcp_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.list_tools()
            tools = []
            for tool in res.tools:
                dumped = tool.model_dump(exclude_none=True)
                encoded = json.dumps(dumped)
                tools.append({
                    "name": tool.name,
                    "chars": len(encoded),
                    "est_tokens": round(len(encoded) / 4),
                    "desc_chars": len(tool.description or ""),
                    "params": len((tool.inputSchema or {}).get("properties", {})),
                })
            tools.sort(key=lambda item: item["chars"], reverse=True)
            total_chars = sum(item["chars"] for item in tools)
            return {
                "mcp_url": mcp_url,
                "total_tools": len(tools),
                "total_chars": total_chars,
                "est_tokens": round(total_chars / 4),
                "tools": tools,
            }


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure MCP tool schema size.")
    parser.add_argument(
        "--mcp-url",
        default=os.environ.get("CORTEX_MCP_URL", "http://127.0.0.1:18021/mcp"),
        help="Streamable HTTP MCP endpoint URL",
    )
    parser.add_argument("--json", type=Path, default=None, help="Optional output JSON path")
    args = parser.parse_args()

    summary = asyncio.run(measure_schemas(args.mcp_url))
    print(f"MCP URL: {summary['mcp_url']}")
    print(
        f"Total tools: {summary['total_tools']}, "
        f"Total JSON chars: {summary['total_chars']}, "
        f"Est tokens (~chars/4): {summary['est_tokens']}"
    )
    for item in summary["tools"]:
        print(
            f"  {item['name']:22s} | {item['chars']:5d} chars (~{item['est_tokens']:4d} tok) "
            f"| desc={item['desc_chars']:3d}c | params={item['params']}"
        )
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
