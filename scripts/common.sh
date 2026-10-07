#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
COMPOSE=(docker compose -f compose.yaml)
if [[ -f .env ]] && [[ $(sed -n 's/^SECURE_COOKIES=//p' .env) == true ]]; then
    COMPOSE+=(-f compose.production.yaml)
fi
compose() { "${COMPOSE[@]}" "$@"; }
