import os
import stat
import subprocess
from pathlib import Path


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _postgres_env(
    *,
    tmp_path: Path,
    fake_bin: Path,
) -> dict[str, str]:
    passfile = tmp_path / "pgpass"
    passfile.write_text(
        "127.0.0.1:5432:cinegate:cinegate:test-password\n",
        encoding="utf-8",
    )
    passfile.chmod(0o600)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "PGHOST": "127.0.0.1",
            "PGPORT": "5432",
            "PGDATABASE": "cinegate",
            "PGUSER": "cinegate",
            "PGPASSFILE": str(passfile),
        }
    )
    return env


def test_backup_script_uses_pgpassfile_and_restrictive_output() -> None:
    path = Path("scripts/backup_postgres.sh")
    script = path.read_text(encoding="utf-8")

    assert path.stat().st_mode & stat.S_IXUSR
    assert "PGPASSFILE" in script
    assert "PGPASSWORD" not in script
    assert "umask 077" in script
    assert "chmod 700" in script
    assert "chmod 600" in script
    assert "--format=custom" in script
    assert "mktemp" in script
    assert "trap cleanup" in script
    assert 'mv -- "${temporary}" "${output}"' in script


def test_restore_script_is_guarded_and_atomic() -> None:
    path = Path("scripts/restore_postgres.sh")
    script = path.read_text(encoding="utf-8")

    assert path.stat().st_mode & stat.S_IXUSR
    assert 'CINEGATE_ALLOW_RESTORE:-' in script
    assert 'CINEGATE_ALLOW_RESTORE=YES' in script
    assert "PGPASSFILE" in script
    assert "PGPASSWORD" not in script
    assert "pg_restore --list" in script
    assert "--single-transaction" in script
    assert "--exit-on-error" in script


def test_backup_script_publishes_only_a_completed_archive(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "pg_dump",
        """#!/usr/bin/env bash
set -eu
for argument in "$@"; do
  case "${argument}" in
    --file=*) output="${argument#--file=}" ;;
  esac
done
: "${output:?missing output}"
printf 'complete-backup' > "${output}"
""",
    )
    backup_dir = tmp_path / "backups"
    env = _postgres_env(tmp_path=tmp_path, fake_bin=fake_bin)
    env["CINEGATE_BACKUP_DIR"] = str(backup_dir)

    completed = subprocess.run(
        [str(Path("scripts/backup_postgres.sh").resolve())],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    output = Path(completed.stdout.strip())
    assert output.parent == backup_dir
    assert output.name.startswith("cinegate-")
    assert output.suffix == ".dump"
    assert output.read_text(encoding="utf-8") == "complete-backup"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup_dir.stat().st_mode) == 0o700
    assert not tuple(backup_dir.glob(".cinegate-*"))


def test_backup_script_removes_partial_file_on_failure(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "pg_dump",
        """#!/usr/bin/env bash
set -eu
for argument in "$@"; do
  case "${argument}" in
    --file=*) output="${argument#--file=}" ;;
  esac
done
: "${output:?missing output}"
printf 'partial-backup' > "${output}"
exit 7
""",
    )
    backup_dir = tmp_path / "backups"
    env = _postgres_env(tmp_path=tmp_path, fake_bin=fake_bin)
    env["CINEGATE_BACKUP_DIR"] = str(backup_dir)

    completed = subprocess.run(
        [str(Path("scripts/backup_postgres.sh").resolve())],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 7
    assert tuple(backup_dir.iterdir()) == ()


def test_restore_script_validates_then_uses_one_transaction(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_path = tmp_path / "pg_restore.log"
    _write_executable(
        fake_bin / "pg_restore",
        """#!/usr/bin/env bash
set -eu
printf 'CALL\\n' >> "${FAKE_LOG}"
printf '%s\\n' "$@" >> "${FAKE_LOG}"
""",
    )
    restore_file = tmp_path / "backup.dump"
    restore_file.write_text("fake-custom-archive", encoding="utf-8")
    restore_file.chmod(0o600)
    env = _postgres_env(tmp_path=tmp_path, fake_bin=fake_bin)
    env.update(
        {
            "CINEGATE_ALLOW_RESTORE": "YES",
            "CINEGATE_RESTORE_FILE": str(restore_file),
            "FAKE_LOG": str(log_path),
        }
    )

    completed = subprocess.run(
        [str(Path("scripts/restore_postgres.sh").resolve())],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    calls = log_path.read_text(encoding="utf-8")
    assert calls.count("CALL\n") == 2
    assert "--list" in calls
    assert "--single-transaction" in calls
    assert "--exit-on-error" in calls


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
