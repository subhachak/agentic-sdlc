#!/usr/bin/env bash
# Runs the agentic SDLC platform locally: FastAPI + LangGraph control plane
# (:8020) and the Next.js console (:3020).
#
#   ./run.sh start            # start both in the background, open Chrome
#   ./run.sh stop
#   ./run.sh restart
#   ./run.sh status           # ports, pids, and which adapters are actually live
#   ./run.sh logs [api|web]
#   ./run.sh keys [status|import] [--github]   # set up API keys
#   ./run.sh seed [repo] [ref]  # derive the context graph from a repository
#   ./run.sh demo [repo]      # reset, start, seed — a clean demo in one command
#   ./run.sh qa               # run the QA pipeline against demo-app (dry run)
#   ./run.sh test             # both test suites
#   ./run.sh reset            # wipe the local databases and run artifacts
#
# Ports deliberately avoid 8000/3000 and 8010/3010: the sibling projects on
# this machine use those and their launchers kill whatever holds the port.
# demo-app also binds :3000 while the QA pipeline runs. Override with
# API_PORT / WEB_PORT.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$SCRIPT_DIR/control-plane/api"
WEB_DIR="$SCRIPT_DIR/control-plane/web"
QA_DIR="$SCRIPT_DIR/execution-plane/qa"
APP_DIR="$SCRIPT_DIR/demo-app"
RUN_DIR="$SCRIPT_DIR/.run"

API_PORT="${API_PORT:-8020}"
WEB_PORT="${WEB_PORT:-3020}"
APP_URL="http://localhost:$WEB_PORT"
API_URL="http://localhost:$API_PORT"

# The repository the graph is seeded from when none is given.
DEFAULT_SEED_REPO="${SEED_REPO:-subhachak/agentic-sdlc}"

mkdir -p "$RUN_DIR"
API_LOG="$RUN_DIR/api.log"; API_PID_FILE="$RUN_DIR/api.pid"
WEB_LOG="$RUN_DIR/web.log"; WEB_PID_FILE="$RUN_DIR/web.pid"

# Keys and settings live in one .env at the repository root. Exporting them
# here means the QA pipeline and the seeding script see the same values the
# control plane does, rather than each having its own idea of where to look.
load_env() {
  if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    . "$SCRIPT_DIR/.env"
    set +a
  fi
}

load_env

# --- helpers ---------------------------------------------------------------

is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] && kill -0 "$(<"$pid_file")" 2>/dev/null
}

wait_for_http() {
  local url="$1" timeout="$2" waited=0
  while (( waited < timeout )); do
    curl -fs -o /dev/null "$url" && return 0
    sleep 1
    waited=$((waited + 1))
  done
  return 1
}

free_port() {
  local port="$1" pids
  pids="$(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "Port $port is already in use (pid(s) ${pids//$'\n'/, }) — stopping it to take over."
    kill $pids 2>/dev/null || true
    sleep 1
    pids="$(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null || true)"
    [[ -n "$pids" ]] && kill -9 $pids 2>/dev/null || true
  fi
  return 0
}

kill_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

stop_pid_tree() {
  local pid_file="$1" name="$2"
  if is_running "$pid_file"; then
    local pid waited=0
    pid="$(<"$pid_file")"
    echo "Stopping $name (pid $pid)..."
    kill_tree "$pid"
    # uvicorn --reload leaves a reloader child that outlives the parent by a
    # moment; without this, `restart` reports the port still in use and kills
    # it a second time.
    while (( waited < 10 )) && kill -0 "$pid" 2>/dev/null; do
      sleep 0.5
      waited=$((waited + 1))
    done
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
}

# Next refuses to start a second dev server for the same project directory,
# whatever port it was given — so freeing the port is not enough. Find any dev
# server already serving this app and stop it, or `start` fails with an error
# about a server on a port we never asked for.
free_next_dev() {
  local pids pid cwd
  pids="$(pgrep -f "next.*dev" 2>/dev/null || true)"
  for pid in $pids; do
    cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)"
    if [[ -n "$cwd" && "$cwd" == "$WEB_DIR"* ]]; then
      echo "web: another dev server for this app is running (pid $pid) — stopping it to take over."
      kill_tree "$pid"
      sleep 1
    fi
  done
  return 0
}

# --- dependencies ----------------------------------------------------------

ensure_dependencies() {
  command -v uv >/dev/null 2>&1 || { echo "uv is required: https://docs.astral.sh/uv/" >&2; exit 1; }

  if [[ ! -x "$API_DIR/.venv/bin/uvicorn" || "$API_DIR/pyproject.toml" -nt "$API_DIR/.venv/bin/uvicorn" ]]; then
    echo "api: syncing dependencies..."
    (cd "$API_DIR" && uv sync --all-groups >/dev/null)
  fi

  if [[ ! -d "$WEB_DIR/node_modules" || "$WEB_DIR/package-lock.json" -nt "$WEB_DIR/node_modules" ]]; then
    echo "web: installing dependencies..."
    (cd "$WEB_DIR" && npm ci --silent)
  fi
}

# --- lifecycle -------------------------------------------------------------

do_start() {
  if is_running "$API_PID_FILE" || is_running "$WEB_PID_FILE"; then
    echo "agentic-sdlc is already running (use ./run.sh restart)."
    exit 0
  fi

  ensure_dependencies
  free_port "$API_PORT"
  free_port "$WEB_PORT"
  free_next_dev

  echo "api: starting on :$API_PORT (log: $API_LOG)"
  (
    cd "$API_DIR"
    # CORS is pinned to whichever port the console actually got, so overriding
    # WEB_PORT does not silently break every request the browser makes.
    export WEB_ORIGIN="$APP_URL"
    exec .venv/bin/uvicorn app.main:app --reload --port "$API_PORT"
  ) > "$API_LOG" 2>&1 &
  echo $! > "$API_PID_FILE"

  if wait_for_http "$API_URL/api/health" 45; then
    echo "api: ready"
  else
    echo "api: failed to start — check $API_LOG" >&2
    do_stop
    exit 1
  fi

  echo "web: starting on :$WEB_PORT (log: $WEB_LOG)"
  (
    cd "$WEB_DIR"
    export NEXT_PUBLIC_API_URL="$API_URL"
    exec npm run dev -- --port "$WEB_PORT"
  ) > "$WEB_LOG" 2>&1 &
  echo $! > "$WEB_PID_FILE"

  if wait_for_http "$APP_URL" 60; then
    echo "web: ready"
  else
    echo "web: failed to start — check $WEB_LOG" >&2
    do_stop
    exit 1
  fi

  echo
  do_adapters
  echo
  echo "Opening $APP_URL..."
  open -a "Google Chrome" "$APP_URL" 2>/dev/null || open "$APP_URL" 2>/dev/null \
    || echo "Open this manually: $APP_URL"
  echo "agentic-sdlc is running. Use ./run.sh stop to shut it down."
}

do_stop() {
  stop_pid_tree "$WEB_PID_FILE" "web"
  stop_pid_tree "$API_PID_FILE" "api"
  echo "agentic-sdlc stopped."
}

# Which adapters are actually live, read from the API rather than guessed from
# the env file — this is the usual answer to "why is nothing calling Claude".
do_adapters() {
  local config
  config="$(curl -fs "$API_URL/api/config" 2>/dev/null || true)"
  [[ -z "$config" ]] && return 0
  # %-formatting rather than f-strings: this whole program is a single-quoted
  # shell argument, so any nested quote inside an f-string expression breaks it.
  echo "$config" | "$API_DIR/.venv/bin/python" -c '
import json, sys
data = json.load(sys.stdin)
print("adapters:")
for name, value in data.get("active", {}).items():
    print("  %-18s %s" % (name.replace("_", " "), value))
secrets = [e for e in data.get("settings", []) if e.get("kind") == "secret"]
if secrets:
    print("secrets:")
    for entry in secrets:
        state = "configured" if entry.get("configured") else "not set"
        print("  %-18s %s" % (entry.get("label"), state))
' 2>/dev/null || true
}

do_status() {
  local name pid_file port
  for entry in "api:$API_PID_FILE:$API_PORT" "web:$WEB_PID_FILE:$WEB_PORT"; do
    IFS=: read -r name pid_file port <<<"$entry"
    if is_running "$pid_file"; then
      printf "%-4s running  pid %-8s http://localhost:%s\n" "$name" "$(<"$pid_file")" "$port"
    elif lsof -ti "tcp:$port" -sTCP:LISTEN >/dev/null 2>&1; then
      printf "%-4s running  (not started by this script, port %s in use)\n" "$name" "$port"
    else
      printf "%-4s stopped\n" "$name"
    fi
  done
  echo
  do_adapters
}

do_logs() {
  case "${1:-all}" in
    api) tail -f "$API_LOG" ;;
    web) tail -f "$WEB_LOG" ;;
    all) tail -f "$API_LOG" "$WEB_LOG" 2>/dev/null ;;
    *)   echo "Usage: $0 logs [api|web|all]" >&2; exit 1 ;;
  esac
}

# --- keys ------------------------------------------------------------------

# Where to look for keys already configured on this machine.
SIBLING_ROOT="${SIBLING_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
WANTED_KEYS=(ANTHROPIC_API_KEY GITHUB_TOKEN)

# Values are moved from file to file and never printed. Everything this
# command reports is a key *name* and which project it came from.
sibling_env_files() {
  find "$SIBLING_ROOT" -maxdepth 2 -name .env -not -path "$SCRIPT_DIR/*" 2>/dev/null | sort
}

# Missing file, missing key, unreadable file: all "no value", never an error.
# Under `set -e` a failing pipeline inside a command substitution takes the
# whole script down, which is how `keys status` silently printed nothing.
read_key_from() {
  [[ -f "$1" ]] || return 0
  sed -n "s/^$2=//p" "$1" 2>/dev/null | head -1 | tr -d "\"' \r" || true
}

# Find the first sibling that defines a key, printing the project name only.
locate_key() {
  local key="$1" file value
  while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    value="$(read_key_from "$file" "$key")"
    if [[ -n "$value" ]]; then
      echo "$file"
      return 0
    fi
  done < <(sibling_env_files)
  return 1
}

# Rewrite one line of .env in place. The value travels through the
# environment rather than argv, so it never appears in the process list.
upsert_env() {
  KEY="$1" VALUE="$2" "$API_DIR/.venv/bin/python" - "$SCRIPT_DIR/.env" <<'PY'
import os, pathlib, sys
path = pathlib.Path(sys.argv[1])
key, value = os.environ["KEY"], os.environ["VALUE"]
lines = path.read_text().splitlines() if path.exists() else []
out, replaced = [], False
for line in lines:
    stripped = line.lstrip()
    if not stripped.startswith("#") and line.split("=", 1)[0].strip() == key:
        out.append(f"{key}={value}")
        replaced = True
    else:
        out.append(line)
if not replaced:
    out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n")
PY
}

do_keys() {
  local action="${1:-status}" push_github=0
  shift || true
  for arg in "$@"; do
    [[ "$arg" == "--github" ]] && push_github=1
  done

  local key source have
  case "$action" in
    status)
      echo "Looking under $SIBLING_ROOT"
      for key in "${WANTED_KEYS[@]}"; do
        have="$(read_key_from "$SCRIPT_DIR/.env" "$key")"
        if [[ -n "$have" ]]; then
          printf "  %-20s already set in .env\n" "$key"
        elif source="$(locate_key "$key")"; then
          printf "  %-20s available from %s\n" "$key" "$(basename "$(dirname "$source")")"
        else
          printf "  %-20s not found in any sibling project\n" "$key"
        fi
      done
      echo
      echo "Run './run.sh keys import' to copy them into .env,"
      echo "or add --github to also set the Actions secret."
      ;;

    import)
      [[ -f "$SCRIPT_DIR/.env" ]] || cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
      ensure_dependencies

      for key in "${WANTED_KEYS[@]}"; do
        if [[ -n "$(read_key_from "$SCRIPT_DIR/.env" "$key")" ]]; then
          printf "  %-20s already set — leaving it alone\n" "$key"
          continue
        fi
        if ! source="$(locate_key "$key")"; then
          printf "  %-20s not found in any sibling project\n" "$key"
          continue
        fi
        upsert_env "$key" "$(read_key_from "$source" "$key")"
        printf "  %-20s imported from %s\n" "$key" "$(basename "$(dirname "$source")")"
      done

      chmod 600 "$SCRIPT_DIR/.env"

      # A key is only useful to the agents if the provider is switched over.
      if [[ -n "$(read_key_from "$SCRIPT_DIR/.env" ANTHROPIC_API_KEY)" ]]; then
        upsert_env LLM_PROVIDER_ADAPTER claude
        echo "  LLM_PROVIDER_ADAPTER set to claude"
      fi

      if (( push_github )); then
        if ! command -v gh >/dev/null 2>&1; then
          echo "  gh is not installed — skipping the Actions secret." >&2
        else
          local repo value
          repo="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)"
          value="$(read_key_from "$SCRIPT_DIR/.env" ANTHROPIC_API_KEY)"
          if [[ -n "$repo" && -n "$value" ]]; then
            printf "%s" "$value" | gh secret set ANTHROPIC_API_KEY --repo "$repo" >/dev/null \
              && echo "  ANTHROPIC_API_KEY set as an Actions secret on $repo"
          else
            echo "  could not set the Actions secret — no repo or no key." >&2
          fi
        fi
      fi

      echo
      echo ".env written (mode 600, gitignored). Check it took with ./run.sh status."
      ;;

    *)
      echo "Usage: $0 keys [status|import] [--github]" >&2
      exit 1
      ;;
  esac
}

# --- graph, QA, tests ------------------------------------------------------

do_seed() {
  ensure_dependencies
  local repo="${1:-$DEFAULT_SEED_REPO}" ref="${2:-main}"
  echo "Deriving the context graph from $repo@$ref..."
  echo "(reads source and parses imports; never executes what it fetches)"
  (cd "$API_DIR" && .venv/bin/python scripts/seed_graph.py --repo "$repo" --ref "$ref")
  # The execution plane runs in CI with no route to the control plane's
  # database, so it reads a generated export instead of querying the graph.
  # Exporting here is what keeps the two planes describing one commit.
  echo
  echo "Exporting the demo-app slice for the QA pipeline..."
  (cd "$API_DIR" && .venv/bin/python scripts/export_code_graph.py --scope demo-app)
}

do_qa() {
  if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "The QA pipeline calls a model — set ANTHROPIC_API_KEY in .env," >&2
    echo "or run ./run.sh keys import. Everything else runs without one;" >&2
    echo "the control plane defaults to the mock provider." >&2
    exit 1
  fi
  "$SCRIPT_DIR/scripts/local-demo.sh"
}

do_test() {
  ensure_dependencies
  echo "== control plane =="
  (cd "$API_DIR" && uv run pytest -q)
  echo "== execution plane =="
  (cd "$QA_DIR" && python -m pytest tests/ -q)
}

do_reset() {
  if is_running "$API_PID_FILE"; then
    echo "agentic-sdlc is running — stop it first (./run.sh stop) so the DB isn't reset out from under it." >&2
    exit 1
  fi
  rm -f "$API_DIR"/*.db "$API_DIR"/*_checkpoints.sqlite
  rm -rf "$SCRIPT_DIR/evidence" "$APP_DIR/generated-tests"
  echo "Local databases and run artifacts wiped. The schema is recreated on the next start."
}

do_demo() {
  do_stop >/dev/null 2>&1 || true
  do_reset
  do_start
  echo
  do_seed "${1:-$DEFAULT_SEED_REPO}"
  echo
  echo "Ready. Submit a requirement at $APP_URL/new and approve at each gate."
}

case "${1:-}" in
  start)   do_start ;;
  stop)    do_stop ;;
  restart) do_stop; do_start ;;
  status)  do_status ;;
  logs)    do_logs "${2:-all}" ;;
  seed)    shift; do_seed "$@" ;;
  demo)    shift; do_demo "$@" ;;
  keys)    shift; do_keys "$@" ;;
  qa)      do_qa ;;
  test)    do_test ;;
  reset)   do_reset ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs|keys|seed|demo|qa|test|reset}"
    exit 1
    ;;
esac
