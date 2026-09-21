# CineGate Backup & Restore

## What must be backed up

PostgreSQL is CineGate's durable application state:

- movie/index metadata
- Archive Telegram message references
- search sessions
- rewards/deliveries/deletion deadlines
- runtime settings/templates
- owner audit state
- historical-import mappings/checkpoints

Movie media itself is **not** stored in PostgreSQL. The private Telegram Archive Channel remains the media source of truth.

## Credential handling

Do not place the database password in shell command arguments or commit it to the repository.

Use a dedicated PostgreSQL passfile:

```text
hostname:5432:database:username:password
```

Then:

```bash
chmod 600 /etc/cinegate/pgpass
export PGPASSFILE=/etc/cinegate/pgpass
```

The supplied scripts refuse a passfile that is not mode `600`.

## Backup

Set non-secret connection selectors and a protected output directory:

```bash
export PGHOST=127.0.0.1
export PGPORT=5432
export PGDATABASE=cinegate
export PGUSER=cinegate
export PGPASSFILE=/etc/cinegate/pgpass
export CINEGATE_BACKUP_DIR=/var/backups/cinegate

./scripts/backup_postgres.sh
```

The output is a timestamped, uniquely suffixed custom-format `pg_dump` file with mode `600`, for example:

```text
cinegate-20260921T120000Z-Ab12Cd.dump
```

The script writes to a private temporary file and publishes the final filename atomically only after `pg_dump` succeeds. An interrupted/failed dump removes its partial file.

Operational guidance:

- keep more than one generation
- copy backups to storage separate from the application host
- encrypt off-host backups at rest
- test restoration periodically
- do not treat an untested backup as a recovery plan

## Restore drill

**Restore into a fresh database first. Do not practice against production.**

1. Stop or isolate any app that could write to the target test database.
2. Create a fresh target database.
3. Point `PGDATABASE` at that fresh database.
4. Set `CINEGATE_ALLOW_RESTORE=YES` explicitly.
5. Run the restore script.

Example:

```bash
export PGHOST=127.0.0.1
export PGPORT=5432
export PGDATABASE=cinegate_restore_test
export PGUSER=cinegate
export PGPASSFILE=/etc/cinegate/pgpass
export CINEGATE_RESTORE_FILE=/var/backups/cinegate/cinegate-YYYYMMDDTHHMMSSZ-XXXXXX.dump
export CINEGATE_ALLOW_RESTORE=YES

./scripts/restore_postgres.sh
```

The restore script first validates that the file is a readable PostgreSQL custom-format archive. It then uses `--single-transaction` and `--exit-on-error`, so PostgreSQL rolls back the restore transaction on error instead of committing a partial restore.

Then validate from a trusted checkout. Put the restored database's `CINEGATE_DATABASE_URL` in a separate mode-`600` environment file; do not paste a credential-bearing URL into shell history:

```bash
chmod 600 /etc/cinegate/restore-test.env
set -a
. /etc/cinegate/restore-test.env
set +a

/opt/cinegate/.venv/bin/alembic upgrade head
/opt/cinegate/.venv/bin/pytest -q
unset CINEGATE_DATABASE_URL
```

The validation environment needs the development/test extra installed for `pytest`; otherwise run the migration plus isolated `/readyz` and functional smoke checks against the restored database.

For a production recovery, smoke-test `/readyz`, owner diagnostics, search, and a controlled delivery before reopening traffic.

## Recovery caveat

A database restore returns CineGate application state to the backup timestamp. Telegram messages created/deleted after that timestamp may differ from restored references. Run:

```bash
python -m cinegate.ops archive verify
```

with an authorized operational UserBot session to detect missing indexed Archive references after recovery.
