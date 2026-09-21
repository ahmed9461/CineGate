#!/usr/bin/env bash
set -euo pipefail

umask 077

: "${PGHOST:?PGHOST is required}"
: "${PGDATABASE:?PGDATABASE is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGPASSFILE:?PGPASSFILE is required}"
: "${CINEGATE_BACKUP_DIR:?CINEGATE_BACKUP_DIR is required}"

PGPORT="${PGPORT:-5432}"

if [[ ! -f "${PGPASSFILE}" ]]; then
  echo "PGPASSFILE does not exist: ${PGPASSFILE}" >&2
  exit 2
fi

mode="$(stat -c '%a' "${PGPASSFILE}" 2>/dev/null || stat -f '%Lp' "${PGPASSFILE}")"
if [[ "${mode}" != "600" ]]; then
  echo "PGPASSFILE must have mode 600 (found ${mode})" >&2
  exit 2
fi

mkdir -p "${CINEGATE_BACKUP_DIR}"
chmod 700 "${CINEGATE_BACKUP_DIR}"

timestamp="$(date -u +'%Y%m%dT%H%M%SZ')"
output="${CINEGATE_BACKUP_DIR}/cinegate-${timestamp}.dump"

pg_dump   --host="${PGHOST}"   --port="${PGPORT}"   --username="${PGUSER}"   --dbname="${PGDATABASE}"   --format=custom   --compress=6   --no-owner   --no-privileges   --file="${output}"

chmod 600 "${output}"
echo "${output}"
