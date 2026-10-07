#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
if [[ $# -ne 2 || $1 != --recipient || $2 != age1* ]]; then
    echo 'Usage: bash scripts/backup.sh --recipient age1PUBLIC_KEY' >&2
    exit 2
fi
command -v age >/dev/null || { echo 'Install age first. Backups containing medical data and secrets must be encrypted.' >&2; exit 1; }
umask 077
mkdir -p backups
work=$(mktemp -d)
mapfile -t running < <(compose ps --status running --services | sed '/^db$/d;/^maintenance$/d')
if [[ ${#running[@]} -eq 0 ]]; then echo 'No running services; start the stack first.' >&2; exit 1; fi
cleanup() { compose start "${running[@]}" >/dev/null || true; rm -rf "$work"; }
trap cleanup EXIT
compose stop "${running[@]}"
compose exec -T db pg_dump -U pacs -Fc pacs_portal > "$work/portal.dump"
compose exec -T db pg_dump -U pacs -Fc orthanc > "$work/orthanc.dump"
compose --profile maintenance run --rm -T --no-deps maintenance python -m scripts.snapshot export > "$work/volumes.tar.gz"
cp .env "$work/config.env"
cp compose.yaml compose.production.yaml "$work/"
cp -R deploy "$work/deploy"
destination="backups/pacs-$(date -u +%Y%m%dT%H%M%SZ).tar.gz.age"
tar -C "$work" -czf - . | age -r "$2" -o "$destination"
test -s "$destination"
echo "Encrypted backup: $destination"
