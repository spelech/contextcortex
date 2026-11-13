"""Regression tests for the benchmarks/ harness, templates, examples, and baseline snapshots."""

import json
import re
from pathlib import Path

from benchmarks.run_benchmark import (
    load_tasks,
    parse_opencode_events,
    render_opencode_config,
    score_ground_truth,
)
from benchmarks.run_micro_bench import extract_response_meta, load_cases

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BENCH_DIR = PROJECT_ROOT / "benchmarks"


def test_benchmark_tasks_and_examples_valid():
    for rel in ("tasks.json", "examples/custom_tasks.example.json"):
        tasks = load_tasks(BENCH_DIR / rel)
        assert len(tasks) >= 2
        ids = [t["id"] for t in tasks]
        assert len(ids) == len(set(ids)), f"Duplicate task IDs in {rel}"
        for task in tasks:
            assert isinstance(task["ground_truth"], list) and len(task["ground_truth"]) >= 4


def test_micro_benchmark_cases_valid():
    cases = load_cases(BENCH_DIR / "examples/micro_cases.example.json")
    assert len(cases["mcp"]) >= 4
    assert len(cases["rg"]) >= 1
    for item in cases["mcp"]:
        assert {"label", "tool", "args"} <= set(item.keys())


def test_opencode_templates_render_without_secrets():
    for tpl in ("opencode.cortex.template.json", "opencode.raw.template.json"):
        rendered = render_opencode_config(
            BENCH_DIR / "configs" / tpl,
            model="litellm/flash-latest",
            base_url="http://127.0.0.1:8448/v1",
            mcp_url="http://127.0.0.1:18021/mcp",
        )
        parsed = json.loads(rendered)
        assert parsed["model"] == "litellm/flash-latest"
        assert parsed["providers"]["litellm"]["settings"]["apiKey"] == "{env:BENCH_LLM_API_KEY}"
        assert parsed["permission"]["task"] == "deny"


def test_benchmarks_directory_contains_no_hardcoded_api_keys():
    key_pattern = re.compile(r"sk-[A-Za-z0-9_-]{16,}")
    for path in BENCH_DIR.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if "workspace" in path.parts or "results" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert not key_pattern.search(text), f"Hardcoded API key found in {path.relative_to(PROJECT_ROOT)}"


def test_parse_opencode_events_and_scoring():
    sample_stdout = "\n".join([
        json.dumps({"type": "step_start"}),
        json.dumps({
            "type": "tool_use",
            "part": {
                "tool": "contextcortex_grep_code",
                "state": {
                    "status": "completed",
                    "time": {"start": 100, "end": 190},
                    "metadata": {"metadata": {"toolCalls": [{"tool": "contextcortex.grep_code"}]}},
                },
            },
        }),
        json.dumps({"type": "text", "part": {"text": "Found execute_hybrid_search in query_router.py."}}),
        json.dumps({"type": "step_finish", "part": {"tokens": {"input": 100, "output": 25, "reasoning": 5, "cache": {"read": 50}}, "cost": 0.0012}}),
    ])
    parsed = parse_opencode_events(sample_stdout)
    assert parsed["steps"] == 1
    assert parsed["total_tokens"] == 130
    assert parsed["inner_tool_calls"] == ["contextcortex.grep_code"]
    assert parsed["outer_tools"][0]["duration_ms"] == 90

    scored = score_ground_truth(parsed["answer_text"], ["execute_hybrid_search", "query_router.py", "missing_sym"])
    assert scored["gt_hits"] == 2
    assert scored["gt_total"] == 3
    assert scored["missing_gt"] == ["missing_sym"]

    meta = extract_response_meta(json.dumps({"mode": "hybrid", "total": 6}))
    assert meta == {"mode": "hybrid", "total": 6}


def test_baseline_snapshots_consistent():
    before = json.loads((BENCH_DIR / "baselines/pr140_19tools_before.json").read_text(encoding="utf-8"))
    after = json.loads((BENCH_DIR / "baselines/pr140_10tools_after.json").read_text(encoding="utf-8"))
    assert before["schema"]["total_tools"] == 19
    assert after["schema"]["total_tools"] == 10
    assert after["schema"]["total_chars"] < before["schema"]["total_chars"]
    assert after["aggregates"]["cortex"]["total_tokens"] < before["aggregates"]["cortex"]["total_tokens"]
    assert after["micro_bench_3run_median_ms"]["grep_code exact symbol"] < before["micro_bench_3run_median_ms"]["grep_code exact symbol"]
