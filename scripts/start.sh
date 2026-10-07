#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
if [[ ! -f .env ]]; then
    echo 'First run: python3 scripts/configure.py [--url https://your-domain]' >&2
    exit 1
fi
if [[ ${#COMPOSE[@]} -gt 4 ]] && [[ ! -s deploy/tls/fullchain.pem || ! -s deploy/tls/privkey.pem ]]; then
    echo 'Provide deploy/tls/fullchain.pem and privkey.pem before starting HTTPS.' >&2
    exit 1
fi
compose config --quiet
compose up -d --build --wait --wait-timeout 180
compose ps
