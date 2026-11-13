# Benchmarks & Performance Baselines

ContextCortex includes an isolated benchmark suite under `benchmarks/` for regression-testing MCP tool schema size, direct tool latency versus `rg`, and end-to-end coding agent efficiency using OpenCode.

---

## Benchmark Architecture

1. **`benchmarks/setup_and_run_server.sh`**: Spins up an isolated ContextCortex instance on `127.0.0.1:18021` using `benchmarks/workspace/` and Qdrant collection `contextcortex_bench_pr140` (never modifying production instances). Automatically clones and syncs `contextcortex` plus optional sibling repositories (`csharp-mcp-router`, `llmlite-modelmanager`).
2. **`benchmarks/measure_tool_schemas.py`**: Inspects `tools/list` over Streamable HTTP (`/mcp`) and reports total tool count, JSON character footprint, estimated token overhead (`~chars/4`), description sizes, and parameter counts.
3. **`benchmarks/run_micro_bench.py`**: Measures multi-run median latency and response character size across `grep_code`, `search`, `find_symbol`, `trace_path`, and `diagnose_issue` alongside local `rg` comparisons.
4. **`benchmarks/run_benchmark.py`**: Runs controlled single-agent OpenCode A/B evaluations (`--arm cortex` with filesystem tools denied vs. `--arm raw` with `bash`/`read`/`glob`/`grep`/`list` allowed and zero MCP servers).

---

## Quick Start

```bash
export LITELLM_URL="http://127.0.0.1:8448/v1"
export LITELLM_API_KEY="sk-your-key"

# 1. Start isolated server and index repositories
./benchmarks/setup_and_run_server.sh start

# 2. Measure MCP schema size
python3 benchmarks/measure_tool_schemas.py --json benchmarks/results/schemas.json

# 3. Run 3-pass median micro-benchmark
python3 benchmarks/run_micro_bench.py --runs 3

# 4. Run self-contained example A/B tasks on contextcortex
export BENCH_LLM_BASE_URL="$LITELLM_URL"
export BENCH_LLM_API_KEY="$LITELLM_API_KEY"
python3 -u benchmarks/run_benchmark.py \
  --tasks-file benchmarks/examples/custom_tasks.example.json

# 5. Stop isolated server
./benchmarks/setup_and_run_server.sh stop
```

> [!NOTE]
> OpenCode configurations are rendered at runtime from `benchmarks/configs/opencode.*.template.json` into gitignored `benchmarks/workspace/configs/` using environment variables, keeping repository files completely free of API keys and machine-specific endpoints.

---

## Adding Custom Benchmarks & Examples

- **Example A/B Tasks**: [`benchmarks/examples/custom_tasks.example.json`](https://github.com/spelech/contextcortex/blob/main/benchmarks/examples/custom_tasks.example.json) provides self-contained tasks targeting `contextcortex` itself (`E1_explain_mcp_surface`, `E2_trace_grep_fast_path`).
- **Example Micro-Cases**: [`benchmarks/examples/micro_cases.example.json`](https://github.com/spelech/contextcortex/blob/main/benchmarks/examples/micro_cases.example.json) demonstrates custom `mcp` and `rg` benchmark queries.
- **Full 6-Task Baseline Catalog**: [`benchmarks/tasks.json`](https://github.com/spelech/contextcortex/blob/main/benchmarks/tasks.json) contains `T1`–`T6` spanning `explain_code`, `diagnose_bug`, and `trace_symbol`.

Pass any custom catalog via CLI flags (`--tasks-file`, `--cases-file`, `--runs`, `--arm`, `--model`, or positional task IDs) to iterate quickly on specific tools or queries.

---

## Recorded Baselines (`PR #140`)

Curated baseline snapshots are tracked in `benchmarks/baselines/`:
- `benchmarks/baselines/pr140_19tools_before.json` (19 tools, before disk-only grep fast path and CamelCase AST priority)
- `benchmarks/baselines/pr140_10tools_after.json` (10 default tools + disk-only grep fast path + CamelCase AST priority)

### Summary Comparison (`litellm/flash-latest`, 6 Tasks)

| Metric | 19-Tool PR #140 (Before) | 10-Tool PR #140 (After) | Raw (`rg` + `read` + `glob`) |
|---|---:|---:|---:|
| **MCP Tools / Schema Tokens** | 19 / ~7,384 | **10 / ~4,855 (-34.2%)** | 0 |
| **`grep_code` (72 hits, 3-run median)** | 488.1 ms | **93.1 ms (-80.9%)** | 6.4–13.0 ms (`rg`) |
| **`search` CamelCase (`OAuthEgressTokenManager`)** | 325.1 ms | **33.1 ms (-89.8%)** | 10.7–11.1 ms (`rg`) |
| **Tasks Completed / GT Score** | 6/6 (`48/48`) | **6/6** (`47/48`) | 5/6 (`40/48`) |
| **LLM Steps / Discovery Turns** | 101 / 17 | **86 / 8** | 134 / 0 |
| **Tool Execution Time / Total Wall** | 23.26s / 808.96s | **12.80s / 681.74s** | 15.95s / 863.22s |
| **Total Tokens / Cost** | 550,867 / \$1.3176 | **424,720 / \$1.0093** | 658,692 / \$1.8162 |
