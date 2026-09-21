# CineGate Production Deployment Runbook

## Intended launch topology

Initial production launch is intentionally single-process:

- PostgreSQL with persistent storage
- one CineGate application process
- CineGate bound to `127.0.0.1` / private interface
- trusted HTTPS reverse proxy or tunnel in front
- Telegram webhook `max_connections=1`

Do not start multiple app workers/processes at launch. Public-user rate limiting is intentionally in-process, while durable correctness remains in PostgreSQL.

## Files and permissions

Recommended:

- application: `/opt/cinegate`
- environment file: `/etc/cinegate/cinegate.env`
- environment file mode: `600`
- service user: `cinegate`
- backups: `/var/backups/cinegate` mode `700`

Never store UserBot session files in the public web root or repository.

## Install

```bash
python3.12 -m venv /opt/cinegate/.venv
/opt/cinegate/.venv/bin/pip install --upgrade pip
/opt/cinegate/.venv/bin/pip install -e /opt/cinegate
```

Install importer tooling only on the trusted host/account that needs it:

```bash
/opt/cinegate/.venv/bin/pip install -e '/opt/cinegate[import]'
```

## Database

Before first app start:

```bash
cd /opt/cinegate
/opt/cinegate/.venv/bin/alembic upgrade head
```

Create and verify a backup before every destructive migration/recovery operation.

## Service manager

Use `deploy/cinegate.service.example` as a template.

Important launch properties:

- one worker
- localhost binding
- automatic restart
- migration before start
- raw Uvicorn access logging disabled

Why `--no-access-log`: the AdsGram Reward callback includes a secret path segment. CineGate emits its own structured request logs with that segment redacted.

## HTTPS edge

The reverse proxy/tunnel must:

- terminate trusted HTTPS
- forward only to the private/local CineGate port
- preserve normal HTTP semantics
- avoid logging the raw AdsGram secret callback path
- not expose FastAPI docs/debug endpoints

Do not expose PostgreSQL publicly.

## Runtime configuration

After the service is up, configure non-secret values through `/admin`:

- Archive Channel ID
- source channel ID if historical import is needed
- owner notification chat ID
- public Mini App/base URL
- AdsGram Block ID
- deletion/search/reward timing

Secrets remain in the protected environment file.

## Health checks

Liveness:

```text
GET /healthz
```

Readiness:

```text
GET /readyz
```

Readiness requires PostgreSQL and the deletion worker, but intentionally does not depend on Telegram/AdsGram availability.

## Webhook

Once public HTTPS is live:

```bash
python -m cinegate.ops webhook set
python -m cinegate.ops webhook status
```

Expected:

- configuration=ok
- max_connections=1
- allowed updates include message, callback_query, channel_post, edited_channel_post

Do not use `--drop-pending` during routine deploys.

## Historical migration

Historical UserBot import is separate from the service:

```bash
python -m cinegate.importer auth
python -m cinegate.importer run
python -m cinegate.importer status
python -m cinegate.importer verify
```

The authorized owner must temporarily disable source forwarding protection. Archive protection must remain disabled for CineGate delivery.

## Archive integrity

Bot API supplies edited channel posts but not channel-message deletion updates.

Run the read-only integrity audit after:

- historical migration
- database restore
- manual Archive cleanup
- suspicious missing-file reports

```bash
python -m cinegate.ops archive verify
```

It reports missing references and performs no destructive repair.

## Restart procedure

1. Confirm current backup.
2. Pull/update code.
3. Install dependencies.
4. Run test/smoke checks when practical.
5. Restart service manager.
6. Check `/readyz`.
7. Run `webhook status`.
8. Inspect structured CineGate logs.
9. Perform one controlled search/poster flow.

## Rollback

If a deployment fails:

- stop the new application process
- restore prior code artifact/revision
- run only migrations compatible with that revision
- if database state must be restored, restore into a fresh database first and validate
- confirm `/readyz` before reopening webhook traffic

Never “fix” a failed deploy by deleting CineGate tables or Telegram Archive posts ad hoc.
