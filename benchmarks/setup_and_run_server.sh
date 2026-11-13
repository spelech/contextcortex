#!/usr/bin/env bash
set -euo pipefail

# Sets up isolated A/B workspaces and starts an isolated ContextCortex benchmark
# server on 127.0.0.1:18021 (never touching production :8021).
#
# Usage:
#   ./benchmarks/setup_and_run_server.sh start
#   ./benchmarks/setup_and_run_server.sh stop

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WS="${BENCH_WORKSPACE_DIR:-$SCRIPT_DIR/workspace}"
REPOS_PARENT="${BENCH_REPOS_PARENT:-$(cd "$REPO_ROOT/.." && pwd)}"
PORT="${CORTEX_BENCH_PORT:-18021}"
PID_FILE="$WS/server.pid"

case "${1:-start}" in
  stop)
    if [[ -f "$PID_FILE" ]]; then
      PID="$(cat "$PID_FILE")"
      kill "$PID" 2>/dev/null || true
      sleep 1
      kill -9 "$PID" 2>/dev/null || true
      rm -f "$PID_FILE"
      echo "Stopped benchmark server PID $PID"
    else
      echo "No PID file at $PID_FILE"
    fi
    exit 0
    ;;
  start)
    ;;
  *)
    echo "Usage: $0 [start|stop]" >&2
    exit 1
    ;;
esac

mkdir -p "$WS/arm_cortex" "$WS/arm_b_workspace" "$WS/server_data/repos" "$WS/tmp_repos" "$WS/docs"

if [[ ! -d "$WS/arm_cortex/.git" ]]; then
  git -C "$WS/arm_cortex" init -q
fi
if [[ ! -d "$WS/arm_b_workspace/.git" ]]; then
  git -C "$WS/arm_b_workspace" init -q
fi

clone_if_missing() {
  local src="$1" branch="$2" dst="$3"
  if [[ ! -d "$dst/.git" ]]; then
    git clone --depth 1 --branch "$branch" "file://$src" "$dst"
  fi
}

register_repo() {
  local name="$1" src="$2" branch="$3"
  curl -sf -X POST "http://127.0.0.1:$PORT/admin/api/repos" \
    -H 'Content-Type: application/json' \
    -d "{\"name\":\"$name\",\"url\":\"file://$src\",\"branch\":\"$branch\",\"auto_sync\":false,\"keep_shallow\":true,\"retain_commits_count\":20}" >/dev/null || true
}

CORTEX_BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
clone_if_missing "$REPO_ROOT" "$CORTEX_BRANCH" "$WS/arm_b_workspace/contextcortex"

OPTIONAL_SIBLINGS=("csharp-mcp-router" "llmlite-modelmanager")
SIBLING_BRANCHES=()
for sibling in "${OPTIONAL_SIBLINGS[@]}"; do
  if [[ -d "$REPOS_PARENT/$sibling/.git" ]]; then
    S_BRANCH="$(git -C "$REPOS_PARENT/$sibling" rev-parse --abbrev-ref HEAD)"
    SIBLING_BRANCHES+=("$sibling|$REPOS_PARENT/$sibling|$S_BRANCH")
    clone_if_missing "$REPOS_PARENT/$sibling" "$S_BRANCH" "$WS/arm_b_workspace/$sibling"
  fi
done

if ! curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
  pushd "$REPO_ROOT" >/dev/null
  DATA_DIR="$WS/server_data" \
  VAULT_PATH="$WS/docs" \
  CACHE_DB_PATH="$WS/server_data/index_cache.db" \
  PERSISTENT_REPOS_DIR="$WS/server_data/repos" \
  TMP_REPOS_DIR="$WS/tmp_repos" \
  QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:8010}" \
  COLLECTION_NAME="${COLLECTION_NAME:-contextcortex_bench_pr140}" \
  EMBEDDING_PROVIDER="${EMBEDDING_PROVIDER:-api}" \
  EMBEDDING_MODEL="${EMBEDDING_MODEL:-gemini-embedding-001}" \
  LITELLM_URL="${LITELLM_URL:-http://127.0.0.1:8448/v1}" \
  LITELLM_API_KEY="${LITELLM_API_KEY:-${OPENAI_API_KEY:-}}" \
  AUTH_ENABLED="false" \
  CODE_CHUNK_SIZE="${CODE_CHUNK_SIZE:-4000}" \
  HOST="127.0.0.1" \
  PORT="$PORT" \
  nohup setsid python3 -u main.py </dev/null >"$WS/server.log" 2>&1 &
  echo $! > "$PID_FILE"
  popd >/dev/null

  for _ in $(seq 1 25); do
    if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
fi

curl -sf "http://127.0.0.1:$PORT/health"
echo ""

register_repo "contextcortex" "$REPO_ROOT" "$CORTEX_BRANCH"
for entry in "${SIBLING_BRANCHES[@]:-}"; do
  [[ -z "$entry" ]] && continue
  IFS='|' read -r s_name s_src s_branch <<< "$entry"
  register_repo "$s_name" "$s_src" "$s_branch"
done

echo "Waiting for repositories to finish syncing on :$PORT..."
for _ in $(seq 1 150); do
  PENDING="$(curl -s "http://127.0.0.1:$PORT/admin/api/repos" | python3 -c 'import sys,json; rs=json.load(sys.stdin); print(sum(1 for r in rs if r["status"]!="synced"))')"
  if [[ "$PENDING" == "0" ]]; then
    break
  fi
  sleep 2
done

curl -s "http://127.0.0.1:$PORT/admin/api/repos" | python3 -c '
import sys, json
for r in json.load(sys.stdin):
    print("  %s: status=%s files=%s branch=%s" % (r.get("name"), r.get("status"), r.get("file_count"), r.get("branch")))
'
echo "Ready. Run: python3 -u $SCRIPT_DIR/run_benchmark.py"
