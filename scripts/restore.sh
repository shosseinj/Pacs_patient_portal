#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
if [[ $# -ne 5 || $1 != --confirm || $3 != --identity || $5 != --replace-all-data ]]; then
    echo 'Usage: bash scripts/restore.sh --confirm BACKUP.tar.gz.age --identity AGE_KEY_FILE --replace-all-data' >&2
    exit 2
fi
command -v age >/dev/null || { echo 'Install age first.' >&2; exit 1; }
backup=$(realpath "$2")
identity_file=$(realpath "$4")
umask 077
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
age -d -i "$identity_file" "$backup" > "$work/bundle.tar.gz"
# Inspect and safely unpack the encrypted bundle using the app image.
compose --profile maintenance run --rm -T --no-deps maintenance python -m scripts.validate_bundle < "$work/bundle.tar.gz"
tar --no-same-owner -C "$work" -xzf "$work/bundle.tar.gz"
test -s "$work/portal.dump"
test -s "$work/orthanc.dump"
test -s "$work/volumes.tar.gz"
# Parse all dump data and snapshot structure before touching current databases.
compose exec -T db pg_restore --file=/dev/null < "$work/portal.dump"
compose exec -T db pg_restore --file=/dev/null < "$work/orthanc.dump"
compose --profile maintenance run --rm -T --no-deps maintenance python -m scripts.snapshot verify < "$work/volumes.tar.gz"
compose stop gateway worker portal orthanc
compose exec -T db psql -U pacs -d postgres -v ON_ERROR_STOP=1 -c 'DROP DATABASE pacs_portal WITH (FORCE)' -c 'CREATE DATABASE pacs_portal' -c 'DROP DATABASE orthanc WITH (FORCE)' -c 'CREATE DATABASE orthanc'
compose exec -T db pg_restore -U pacs -d pacs_portal --exit-on-error < "$work/portal.dump"
compose exec -T db pg_restore -U pacs -d orthanc --exit-on-error < "$work/orthanc.dump"
compose --profile maintenance run --rm -T --no-deps maintenance python -m scripts.snapshot import < "$work/volumes.tar.gz"
compose exec -T db psql -U pacs -d pacs_portal -v ON_ERROR_STOP=1 -c 'DELETE FROM sessions;'
compose start orthanc portal worker gateway
echo 'Restore complete. Sessions revoked. Verify a known study and run the patient access check.'
