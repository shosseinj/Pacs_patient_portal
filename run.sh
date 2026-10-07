#!/usr/bin/env bash
set -euo pipefail

port_listeners() {
    ss -H -ltnp "sport = :$1"
}

listener_pids() {
    port_listeners "$1" | sed -n 's/.*users:(/users:(/p' |
        tr ',' '\n' | sed -n 's/^pid=\([0-9][0-9]*\)$/\1/p' | sort -u
}

free_ports() {
    local port pid attempt
    local -a pids
    for port in "$@"; do
        if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
            echo "Invalid TCP port: $port" >&2
            return 1
        fi
        [[ -n "$(port_listeners "$port")" ]] || continue
        mapfile -t pids < <(listener_pids "$port")
        if (( ${#pids[@]} == 0 )); then
            echo "Port $port is occupied by a process this account cannot inspect or stop." >&2
            return 1
        fi
        echo "Freeing TCP port $port (PIDs: ${pids[*]})..."
        for pid in "${pids[@]}"; do
            kill -TERM "$pid" 2>/dev/null || true
        done
        for ((attempt = 0; attempt < 25; attempt++)); do
            [[ -n "$(port_listeners "$port")" ]] || break
            sleep 0.2
        done
        if [[ -n "$(port_listeners "$port")" ]]; then
            # Refresh the listeners so an exited process's reused PID is not killed.
            mapfile -t pids < <(listener_pids "$port")
            for pid in "${pids[@]}"; do
                kill -KILL "$pid" 2>/dev/null || true
            done
            for ((attempt = 0; attempt < 25; attempt++)); do
                [[ -n "$(port_listeners "$port")" ]] || break
                sleep 0.2
            done
        fi
        if [[ -n "$(port_listeners "$port")" ]]; then
            echo "Cannot free port $port. Stop its listener with an account that owns it, then retry." >&2
            return 1
        fi
    done
}

main() {
    if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
        echo 'Usage: bash run.sh'
        echo 'Starts the local portal, worker, Orthanc and OHIF; frees TCP ports 8000, 8042, 8080, 8081.'
        echo 'Python environment: ~/video/.venv/ (override with PACS_VENV).'
        return 0
    fi
    if (( $# != 0 )); then
        echo 'Usage: bash run.sh [--help]' >&2
        return 1
    fi
    local project venv
    project="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    venv="${PACS_VENV:-$HOME/video/.venv}"
    cd "$project"
    for command in python3 ss flock; do
        command -v "$command" >/dev/null || { echo "Required command missing: $command" >&2; return 1; }
    done
    mkdir -p data/runtime
    exec 9>data/runtime/run.lock
    flock -n 9 || { echo 'Another local launcher is already running.' >&2; return 1; }
    if [[ ! -x "$venv/bin/python" ]]; then
        echo "Creating Python environment at $venv..."
        python3 -m venv "$venv"
    fi
    if ! "$venv/bin/python" -c 'import sys; sys.exit(sys.version_info < (3, 12))'; then
        echo "Python 3.12 or newer is required in $venv." >&2
        return 1
    fi
    if ! "$venv/bin/python" - requirements.lock <<'PY'
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    for line in Path(sys.argv[1]).read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            package, expected = line.strip().split("==", 1)
            if version(package) != expected:
                sys.exit(1)
except PackageNotFoundError:
    sys.exit(1)
PY
    then
        echo "Installing Python packages in $venv..."
        "$venv/bin/python" -m pip install -r requirements.lock
    fi
    # Prepare and validate everything before stopping the running services.
    "$venv/bin/python" -m scripts.start_local --prepare
    "$venv/bin/python" -m scripts.start_local --stop
    free_ports 8000 8042 8080 8081
    "$venv/bin/python" -m scripts.start_local
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
