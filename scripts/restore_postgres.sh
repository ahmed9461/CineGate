#!/usr/bin/env bash
set -euo pipefail

umask 077

: "${PGHOST:?PGHOST is required}"
: "${PGDATABASE:?PGDATABASE is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGPASSFILE:?PGPASSFILE is required}"
: "${CINEGATE_RESTORE_FILE:?CINEGATE_RESTORE_FILE is required}"

PGPORT="${PGPORT:-5432}"

if [[ "${CINEGATE_ALLOW_RESTORE:-}" != "YES" ]]; then
  echo "Refusing restore. Set CINEGATE_ALLOW_RESTORE=YES explicitly." >&2
  exit 2
fi

if [[ ! -f "${CINEGATE_RESTORE_FILE}" ]]; then
  echo "Backup file does not exist: ${CINEGATE_RESTORE_FILE}" >&2
  exit 2
fi

if [[ ! -f "${PGPASSFILE}" ]]; then
  echo "PGPASSFILE does not exist: ${PGPASSFILE}" >&2
  exit 2
fi

mode="$(stat -c '%a' "${PGPASSFILE}" 2>/dev/null || stat -f '%Lp' "${PGPASSFILE}")"
if [[ "${mode}" != "600" ]]; then
  echo "PGPASSFILE must have mode 600 (found ${mode})" >&2
  exit 2
fi

echo "Restoring into database: ${PGDATABASE}" >&2
echo "The target database should be fresh/empty." >&2

pg_restore   --host="${PGHOST}"   --port="${PGPORT}"   --username="${PGUSER}"   --dbname="${PGDATABASE}"   --no-owner   --no-privileges   --exit-on-error   "${CINEGATE_RESTORE_FILE}"
