# CineGate Production Launch Checklist

## Secrets/bootstrap

- [ ] bot token configured in protected environment
- [ ] PostgreSQL URL configured
- [ ] webhook secret configured
- [ ] owner Telegram user ID configured
- [ ] AdsGram callback secret configured if production rewards are enabled
- [ ] environment file mode is restrictive
- [ ] no UserBot session/API hash is committed or logged

## PostgreSQL

- [ ] persistent storage configured
- [ ] migrations at head
- [ ] fresh backup created
- [ ] restore drill completed on a non-production database
- [ ] backup retention/off-host copy decided

## Telegram Archive

- [ ] CineGate bot has required Archive permissions
- [ ] Archive content protection is disabled for copyMessage delivery
- [ ] source/archive IDs are correct and different
- [ ] historical import completed if needed
- [ ] historical import verify is clean or exceptions understood
- [ ] read-only Archive integrity audit is clean

## Ads / Mini App

- [ ] public HTTPS base URL configured
- [ ] AdsGram Block ID configured
- [ ] Mini App domain/origin configuration matches public URL
- [ ] Reward URL points to CineGate secret callback
- [ ] client proof + provider proof tested
- [ ] failed Telegram delivery retry tested without another ad

## Application

- [ ] service runs as non-root user
- [ ] one app worker/process
- [ ] raw Uvicorn access log disabled
- [ ] structured logs visible
- [ ] sensitive callback path is redacted
- [ ] `/healthz` returns 200
- [ ] `/readyz` returns 200
- [ ] deletion worker healthy
- [ ] search/callback/reward abuse limits tested

## Webhook

- [ ] public HTTPS endpoint reachable
- [ ] webhook set through CineGate ops CLI
- [ ] webhook status reports configuration=ok
- [ ] max_connections=1
- [ ] expected allowed_updates only
- [ ] pending update count understood
- [ ] no unexpected recent webhook error

## Functional smoke test

- [ ] user searches exact movie
- [ ] typo search works
- [ ] result button opens correct poster
- [ ] available qualities are correct
- [ ] rapid double click does not duplicate UI
- [ ] ad opens
- [ ] reward verifies
- [ ] exact quality arrives
- [ ] caption/delete timer is correct
- [ ] delivered movie deletes on schedule
- [ ] poster remains
- [ ] owner panel edits apply without restart
- [ ] edited Archive caption reconciles correctly

## Operations

- [ ] owner knows `/admin`
- [ ] webhook status command documented
- [ ] archive verify command documented
- [ ] importer status/verify documented
- [ ] backup location documented
- [ ] restore procedure documented
- [ ] rollback revision identified
- [ ] launch-day logs/diagnostics monitored

Do not raise webhook concurrency above 1 until a durable global update sequencer has its own plan and tests.
