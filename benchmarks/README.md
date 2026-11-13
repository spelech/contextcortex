# ContextCortex Benchmarks

Reproducible benchmark suite for measuring ContextCortex across three dimensions:

1. **MCP Schema Footprint** ([`measure_tool_schemas.py`](measure_tool_schemas.py)) — measures `tools/list` JSON characters, estimated schema tokens, description lengths, and parameter counts.
2. **Direct MCP Latency vs. `rg`** ([`run_micro_bench.py`](run_micro_bench.py)) — times direct Streamable HTTP (`/mcp`) calls (`grep_code`, `search`, `find_symbol`, `trace_path`, `diagnose_issue`) against local `rg` across configurable multi-run medians.
3. **Controlled OpenCode A/B Suite** ([`run_benchmark.py`](run_benchmark.py)) — runs coding-agent investigation tasks (`Arm A: cortex` MCP-only vs. `Arm B: raw` `bash`/`read`/`glob`/`grep`/`list` on local shallow clones) and scores wall time, tool execution time, LLM steps, token consumption, cost, and ground-truth accuracy.

---

## Quick Start (Isolated `:18021` Server)

The benchmark launcher never touches a production `:8021` or `:3000` instance. It uses isolated data under `benchmarks/workspace/` (gitignored) and Qdrant collection `contextcortex_bench_pr140` on port `18021`.

```bash
# 1. Start isolated server & sync repositories
export LITELLM_URL="http://127.0.0.1:8448/v1"
export LITELLM_API_KEY="sk-your-key"
./benchmarks/setup_and_run_server.sh start

# 2. Measure tool schema footprint
python3 benchmarks/measure_tool_schemas.py

# 3. Run direct micro-benchmarks (3-run median)
python3 benchmarks/run_micro_bench.py --runs 3

#    Or run self-contained contextcortex-only micro-cases:
python3 benchmarks/run_micro_bench.py --cases-file benchmarks/examples/micro_cases.example.json

# 4. Run OpenCode A/B benchmark (example tasks targeting contextcortex only)
export BENCH_LLM_BASE_URL="$LITELLM_URL"
export BENCH_LLM_API_KEY="$LITELLM_API_KEY"
export BENCH_MODEL="litellm/flash-latest"
python3 -u benchmarks/run_benchmark.py --tasks-file benchmarks/examples/custom_tasks.example.json

#    Or run the full 6-task multi-repo baseline suite (requires sibling repos in ../)
python3 -u benchmarks/run_benchmark.py --arm cortex

# 5. Stop the isolated server
./benchmarks/setup_and_run_server.sh stop
```

---

## Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `CORTEX_BENCH_PORT` | Port for isolated benchmark server | `18021` |
| `CORTEX_MCP_URL` | Streamable HTTP endpoint for scripts | `http://127.0.0.1:18021/mcp` |
| `BENCH_WORKSPACE_DIR` | Scratch workspace & synced repos directory | `benchmarks/workspace` |
| `BENCH_RESULTS_DIR` | Output directory for run JSON/JSONL artifacts | `benchmarks/results` |
| `BENCH_REPOS_PARENT` | Parent folder searched for optional sibling repos | `..` (parent of repo) |
| `BENCH_MODEL` | OpenCode `provider/model` target | `litellm/flash-latest` |
| `BENCH_LLM_BASE_URL` | OpenAI-compatible base URL for OpenCode | `LITELLM_URL` or `http://127.0.0.1:8448/v1` |
| `BENCH_LLM_API_KEY` | API key passed to generated runtime OpenCode config | `LITELLM_API_KEY` / `OPENAI_API_KEY` |
| `BENCH_TASKS_FILE` | Default task catalog JSON file | `benchmarks/tasks.json` |
| `BENCH_ARM` | Restrict A/B run to `cortex` or `raw` | unset (runs both) |
| `BENCH_TIMEOUT` | Per-task OpenCode timeout (seconds) | `450` |

---

## Adding More Benchmark Tasks & Cases

- **Add A/B agent tasks**: Copy [`examples/custom_tasks.example.json`](examples/custom_tasks.example.json) or append entries to [`tasks.json`](tasks.json). Each task requires `id`, `category`, `repo`, `prompt`, and a `ground_truth` array of exact file/symbol/constant substrings verified case-insensitively against the agent's final response.
- **Add micro-benchmark cases**: Copy [`examples/micro_cases.example.json`](examples/micro_cases.example.json) and pass `--cases-file <path>` to `run_micro_bench.py`.
- **Save runtime configs safely**: `run_benchmark.py` renders [`configs/opencode.cortex.template.json`](configs/opencode.cortex.template.json) and [`configs/opencode.raw.template.json`](configs/opencode.raw.template.json) into gitignored `benchmarks/workspace/configs/` at runtime—never commit API keys or local secrets.

---

## Recorded Baselines (`baselines/`)

| Metric | 19-Tool PR #140 (Before) | 10-Tool PR #140 (After) | Raw (`rg` + `read` + `glob`) |
|---|---:|---:|---:|
| **MCP Tools / Schema Chars** | 19 / 29,538 (~7,384 tok) | **10 / 19,420 (~4,855 tok)** | 0 / local tools |
| **`grep_code` (`CompositeIdentityProvider`, 72 hits)** | 488.1 ms | **93.1 ms** | 6.4–13.0 ms (`rg`) |
| **`search` CamelCase (`OAuthEgressTokenManager`)** | 325.1 ms | **33.1 ms** (`#1` score `1.0`) | 10.7–11.1 ms (`rg`) |
| **6-Task Completion / GT Score** | 6/6 (`48/48`) | **6/6** (`47/48`) | 5/6 (`40/48`, `T1` timeout) |
| **6-Task LLM Steps / Discovery Calls** | 101 / 17 | **86 / 8** | 134 / 0 |
| **6-Task Tool Exec / Total Wall** | 23.26s / 808.96s | **12.80s / 681.74s** | 15.95s / 863.22s |
| **6-Task Total Tokens / Cost (`flash-latest`)** | 550,867 / \$1.3176 | **424,720 / \$1.0093** | 658,692 / \$1.8162 |

See [`baselines/pr140_19tools_before.json`](baselines/pr140_19tools_before.json) and [`baselines/pr140_10tools_after.json`](baselines/pr140_10tools_after.json) for full per-task breakdowns.
