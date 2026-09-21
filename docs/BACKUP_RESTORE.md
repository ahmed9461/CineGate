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

The output is a timestamped custom-format `pg_dump` file with restrictive permissions.

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
export CINEGATE_RESTORE_FILE=/var/backups/cinegate/cinegate-YYYYMMDDTHHMMSSZ.dump
export CINEGATE_ALLOW_RESTORE=YES

./scripts/restore_postgres.sh
```

Then validate:

```bash
CINEGATE_DATABASE_URL='postgresql+asyncpg://...' alembic upgrade head
CINEGATE_DATABASE_URL='postgresql+asyncpg://...' pytest -q
```

For a production recovery, smoke-test `/readyz`, owner diagnostics, search, and a controlled delivery before reopening traffic.

## Recovery caveat

A database restore returns CineGate application state to the backup timestamp. Telegram messages created/deleted after that timestamp may differ from restored references. Run:

```bash
python -m cinegate.ops archive verify
```

with an authorized operational UserBot session to detect missing indexed Archive references after recovery.
