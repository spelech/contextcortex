#!/usr/bin/env python3
"""Controlled OpenCode A/B benchmark runner: ContextCortex MCP vs Raw Repo + Ripgrep."""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

BENCH_DIR = Path(__file__).resolve().parent
SCRATCH = Path(os.environ.get("BENCH_WORKSPACE_DIR", str(BENCH_DIR / "workspace")))
TEMPLATES_DIR = Path(os.environ.get("BENCH_TEMPLATES_DIR", str(BENCH_DIR / "configs")))
RESULTS_DIR = Path(os.environ.get("BENCH_RESULTS_DIR", str(BENCH_DIR / "results")))
DEFAULT_TASKS_FILE = Path(os.environ.get("BENCH_TASKS_FILE", str(BENCH_DIR / "tasks.json")))
TIMEOUT_SECONDS = int(os.environ.get("BENCH_TIMEOUT", "450"))
DEFAULT_MODEL = os.environ.get("BENCH_MODEL", "litellm/flash-latest")


def load_tasks(tasks_file: Path) -> List[Dict[str, Any]]:
    tasks = json.loads(tasks_file.read_text(encoding="utf-8"))
    if not isinstance(tasks, list):
        raise ValueError(f"Tasks file must contain a JSON array: {tasks_file}")
    required = {"id", "category", "repo", "prompt", "ground_truth"}
    for idx, task in enumerate(tasks):
        missing = required - set(task.keys())
        if missing:
            raise ValueError(f"Task #{idx} missing keys: {sorted(missing)}")
    return tasks


def render_opencode_config(template_path: Path, model: str, base_url: str, api_key: str, mcp_url: str) -> str:
    provider, model_id = model.split("/", 1) if "/" in model else ("litellm", model)
    raw = template_path.read_text(encoding="utf-8")
    replacements = {
        "${BENCH_MODEL}": model,
        "${BENCH_PROVIDER}": provider,
        "${BENCH_MODEL_ID}": model_id,
        "${BENCH_LLM_BASE_URL}": base_url,
        "${BENCH_LLM_API_KEY}": api_key,
        "${CORTEX_MCP_URL}": mcp_url,
    }
    for token, value in replacements.items():
        raw = raw.replace(token, value)
    json.loads(raw)
    return raw


def prepare_runtime_homes(scratch: Path, templates_dir: Path, model: str, base_url: str, api_key: str, mcp_url: str) -> Dict[str, Path]:
    custom_configs = os.environ.get("BENCH_CONFIGS_DIR")
    if custom_configs:
        base = Path(custom_configs)
        return {"cortex": base / "home_arm_a", "raw": base / "home_arm_b"}

    homes: Dict[str, Path] = {}
    mapping = {"cortex": ("home_arm_a", "opencode.cortex.template.json"), "raw": ("home_arm_b", "opencode.raw.template.json")}
    for arm, (home_name, tpl_name) in mapping.items():
        home_dir = scratch / "configs" / home_name
        cfg_file = home_dir / ".config" / "opencode" / "opencode.json"
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        cfg_file.write_text(render_opencode_config(templates_dir / tpl_name, model, base_url, api_key, mcp_url), encoding="utf-8")
        homes[arm] = home_dir
    return homes


def score_ground_truth(answer_text: str, ground_truth: List[str]) -> Dict[str, Any]:
    lowered = answer_text.lower()
    hits = [kw for kw in ground_truth if kw.lower() in lowered]
    missing = [kw for kw in ground_truth if kw not in hits]
    score = round(len(hits) / len(ground_truth), 3) if ground_truth else 1.0
    return {"gt_hits": len(hits), "gt_total": len(ground_truth), "gt_score": score, "missing_gt": missing}


def parse_opencode_events(stdout: str) -> Dict[str, Any]:
    steps = 0
    input_tokens = output_tokens = reasoning_tokens = cache_read = 0
    cost = 0.0
    tool_calls: List[Optional[str]] = []
    outer_tools: List[Dict[str, Any]] = []
    answer_chunks: List[str] = []
    errors: List[Any] = []

    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        etype = ev.get("type")
        if etype == "step_start":
            steps += 1
        elif etype == "step_finish":
            part = ev.get("part", {})
            tok = part.get("tokens", {})
            input_tokens += tok.get("input", 0)
            output_tokens += tok.get("output", 0)
            reasoning_tokens += tok.get("reasoning", 0)
            cache_read += (tok.get("cache") or {}).get("read", 0)
            cost += float(part.get("cost", 0.0) or 0.0)
        elif etype == "tool_use":
            part = ev.get("part", {})
            outer_tool = part.get("tool")
            state = part.get("state", {})
            t_info = state.get("time", {})
            dur_ms = t_info["end"] - t_info["start"] if isinstance(t_info, dict) and "start" in t_info and "end" in t_info else None
            outer_tools.append({"tool": outer_tool, "duration_ms": dur_ms, "status": state.get("status")})
            inner_calls = ((state.get("metadata") or {}).get("metadata") or {}).get("toolCalls") or []
            if inner_calls:
                tool_calls.extend(ic.get("tool") for ic in inner_calls)
            else:
                tool_calls.append(outer_tool)
        elif etype == "text":
            txt = (ev.get("part") or {}).get("text", "")
            if txt:
                answer_chunks.append(txt)
        elif etype == "error":
            errors.append(ev.get("error"))

    return {
        "steps": steps,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": input_tokens + output_tokens + reasoning_tokens,
        "cache_read": cache_read,
        "cost_usd": round(cost, 6),
        "outer_tools": outer_tools,
        "inner_tool_calls": tool_calls,
        "answer_text": "\n".join(answer_chunks),
        "errors": errors,
    }


def run_arm(arm_name: str, task: Dict[str, Any], home_dir: Path, scratch: Path, results_dir: Path, model: str, timeout_s: int) -> Dict[str, Any]:
    task_id = task["id"]
    out_file = results_dir / f"{task_id}__{arm_name}.jsonl"
    cwd = scratch / ("arm_cortex" if arm_name == "cortex" else "arm_b_workspace")
    env = os.environ.copy()
    env.update({"OPENCODE_DB": ":memory:", "OPENCODE_DISABLE_PROJECT_CONFIG": "1", "OPENCODE_DISABLE_FILEWATCHER": "1", "HOME": str(home_dir), "PWD": str(cwd)})

    t0 = time.monotonic()
    try:
        proc = subprocess.run(["opencode", "run", "--standalone", "--format", "json", "-m", model, task["prompt"]], cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout_s)
        stdout, stderr, exit_code, timed_out = proc.stdout, proc.stderr, proc.returncode, False
    except subprocess.TimeoutExpired as te:
        stdout = (te.stdout or b"").decode("utf-8", errors="replace") if isinstance(te.stdout, bytes) else (te.stdout or "")
        stderr = (te.stderr or b"").decode("utf-8", errors="replace") if isinstance(te.stderr, bytes) else (te.stderr or "")
        exit_code, timed_out = 124, True
    wall_s = round(time.monotonic() - t0, 3)

    out_file.write_text(stdout + ("\n" + stderr if stderr else ""), encoding="utf-8")
    parsed = parse_opencode_events(stdout)
    gt = score_ground_truth(parsed["answer_text"], task["ground_truth"])

    return {
        "task_id": task_id,
        "category": task["category"],
        "repo": task["repo"],
        "arm": arm_name,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "wall_seconds": wall_s,
        "steps": parsed["steps"],
        "outer_tool_count": len(parsed["outer_tools"]),
        "outer_tools": parsed["outer_tools"],
        "inner_tool_calls": parsed["inner_tool_calls"],
        "inner_tool_count": len(parsed["inner_tool_calls"]),
        "input_tokens": parsed["input_tokens"],
        "output_tokens": parsed["output_tokens"],
        "reasoning_tokens": parsed["reasoning_tokens"],
        "total_tokens": parsed["total_tokens"],
        "cache_read": parsed["cache_read"],
        "cost_usd": parsed["cost_usd"],
        **gt,
        "answer_chars": len(parsed["answer_text"]),
        "errors": parsed["errors"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run controlled ContextCortex vs Raw OpenCode A/B benchmark.")
    parser.add_argument("task_ids", nargs="*", help="Optional subset of task IDs to run")
    parser.add_argument("--tasks-file", type=Path, default=DEFAULT_TASKS_FILE, help="Task catalog JSON path")
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR, help="Output directory")
    parser.add_argument("--arm", choices=("cortex", "raw"), default=os.environ.get("BENCH_ARM"), help="Run only one arm")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenCode provider/model identifier")
    parser.add_argument("--timeout", type=int, default=TIMEOUT_SECONDS, help="Per-task timeout in seconds")
    args = parser.parse_args()

    args.results_dir.mkdir(parents=True, exist_ok=True)
    tasks = load_tasks(args.tasks_file)
    base_url = os.environ.get("BENCH_LLM_BASE_URL", os.environ.get("LITELLM_URL", "http://127.0.0.1:8448/v1"))
    api_key = os.environ.get("BENCH_LLM_API_KEY", os.environ.get("LITELLM_API_KEY", os.environ.get("OPENAI_API_KEY", "")))
    mcp_url = os.environ.get("CORTEX_MCP_URL", "http://127.0.0.1:18021/mcp")
    homes = prepare_runtime_homes(SCRATCH, TEMPLATES_DIR, args.model, base_url, api_key, mcp_url)

    selected = set(args.task_ids) if args.task_ids else None
    summary_path = args.results_dir / "benchmark_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() and (selected or args.arm) else []
    arms = (args.arm,) if args.arm else ("cortex", "raw")

    for task in tasks:
        if selected and task["id"] not in selected:
            continue
        for arm in arms:
            summary = [r for r in summary if not (r["task_id"] == task["id"] and r["arm"] == arm)]
            print(f"Running {task['id']} [{arm}]...", flush=True)
            res = run_arm(arm, task, homes[arm], SCRATCH, args.results_dir, args.model, args.timeout)
            summary.append(res)
            print(
                f"  -> wall={res['wall_seconds']}s steps={res['steps']} "
                f"tools={res['inner_tool_calls']} tok={res['total_tokens']} "
                f"gt={res['gt_hits']}/{res['gt_total']} errors={len(res['errors'])}",
                flush=True,
            )
            summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nSaved summary to {summary_path}")


if __name__ == "__main__":
    main()
