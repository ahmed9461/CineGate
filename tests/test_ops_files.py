from pathlib import Path


def test_backup_script_uses_pgpassfile_and_restrictive_output() -> None:
    script = Path("scripts/backup_postgres.sh").read_text(encoding="utf-8")

    assert "PGPASSFILE" in script
    assert "PGPASSWORD" not in script
    assert "umask 077" in script
    assert "chmod 700" in script
    assert "chmod 600" in script
    assert "--format=custom" in script


def test_restore_script_is_guarded_and_atomic() -> None:
    script = Path("scripts/restore_postgres.sh").read_text(encoding="utf-8")

    assert 'CINEGATE_ALLOW_RESTORE:-' in script
    assert 'CINEGATE_ALLOW_RESTORE=YES' in script
    assert "PGPASSFILE" in script
    assert "PGPASSWORD" not in script
    assert "--single-transaction" in script
    assert "--exit-on-error" in script


def test_systemd_template_is_single_process_private_and_no_access_log() -> None:
    service = Path("deploy/cinegate.service.example").read_text(
        encoding="utf-8"
    )

    assert "--host 127.0.0.1" in service
    assert "--workers 1" in service
    assert "--no-access-log" in service
    assert "EnvironmentFile=/etc/cinegate/cinegate.env" in service
    assert "ExecStartPre=" in service
    assert "alembic upgrade head" in service
    assert "User=cinegate" in service
    assert "NoNewPrivileges=true" in service


def test_launch_runbook_keeps_webhook_concurrency_at_one() -> None:
    deployment = Path("docs/DEPLOYMENT.md").read_text(encoding="utf-8")
    checklist = Path("docs/LAUNCH_CHECKLIST.md").read_text(encoding="utf-8")

    assert "max_connections=1" in deployment
    assert "max_connections=1" in checklist
    assert "raw Uvicorn access log disabled" in checklist
