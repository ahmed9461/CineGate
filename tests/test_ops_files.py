import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest


def _bash() -> str:
    # Prefer Git Bash to Windows' optional WSL launcher.
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            candidate = Path(git).resolve().parents[1] / "bin" / "bash.exe"
            if candidate.is_file():
                return str(candidate)
    bash = shutil.which("bash")
    assert bash is not None, "Bash is required to exercise the operational shell scripts"
    return bash


def _bash_path(path: Path) -> str:
    if os.name != "nt":
        return str(path.resolve())
    return subprocess.check_output(
        [_bash(), "-c", 'cygpath -u "$1"', "--", str(path.resolve())],
        text=True, encoding="utf-8",
    ).strip()


def _chmod(path: Path, mode: int) -> None:
    if os.name == "nt":
        subprocess.run(
            [_bash(), "-c", 'chmod "$1" "$2"', "--", f"{mode:o}", _bash_path(path)],
            check=True, capture_output=True, text=True, encoding="utf-8",
        )
    else:
        path.chmod(mode)


def _mode(path: Path) -> int:
    if os.name != "nt":
        return stat.S_IMODE(path.stat().st_mode)
    # Use the script's actual permission view, never fabricate POSIX modes on NTFS.
    return int(subprocess.check_output(
        [_bash(), "-c", 'stat -c "%a" "$1"', "--", _bash_path(path)],
        text=True, encoding="utf-8",
    ).strip(), 8)


def _assert_executable(path: Path) -> None:
    if os.name != "nt":
        assert path.stat().st_mode & stat.S_IXUSR
        return
    # Native Windows stat has no executable bit; enforce Git's distributed mode.
    records = subprocess.check_output(
        ["git", "ls-files", "--stage", "--error-unmatch", "--", path.as_posix()],
        text=True, encoding="utf-8",
    ).splitlines()
    assert len(records) == 1 and records[0].split()[0] == "100755"


def _run_script(path: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    shell_env = env.copy()
    if os.name == "nt":
        for key in ("PGPASSFILE", "CINEGATE_BACKUP_DIR", "CINEGATE_RESTORE_FILE", "FAKE_LOG"):
            if key in shell_env:
                shell_env[key] = _bash_path(Path(shell_env[key]))
    return subprocess.run(
        [_bash(), _bash_path(path)], check=False, capture_output=True,
        text=True, encoding="utf-8", env=shell_env,
    )


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8", newline="\n")
    _chmod(path, 0o755)


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
    _chmod(passfile, 0o600)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
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

    _assert_executable(path)
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

    _assert_executable(path)
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

    completed = _run_script(Path("scripts/backup_postgres.sh"), env)

    assert completed.returncode == 0, completed.stderr
    output_text = completed.stdout.strip()
    if os.name == "nt":
        output_text = subprocess.check_output(
            [_bash(), "-c", 'cygpath -w "$1"', "--", output_text],
            text=True, encoding="utf-8",
        ).strip()
    output = Path(output_text)
    assert output.parent == backup_dir
    assert output.name.startswith("cinegate-")
    assert output.suffix == ".dump"
    assert output.read_text(encoding="utf-8") == "complete-backup"
    assert _mode(output) == 0o600
    assert _mode(backup_dir) == 0o700
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

    completed = _run_script(Path("scripts/backup_postgres.sh"), env)

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
    _chmod(restore_file, 0o600)
    env = _postgres_env(tmp_path=tmp_path, fake_bin=fake_bin)
    env.update(
        {
            "CINEGATE_ALLOW_RESTORE": "YES",
            "CINEGATE_RESTORE_FILE": str(restore_file),
            "FAKE_LOG": str(log_path),
        }
    )

    completed = _run_script(Path("scripts/restore_postgres.sh"), env)

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


@pytest.mark.parametrize("script_name", ["backup_postgres.sh", "restore_postgres.sh"])
def test_scripts_reject_readable_passfile(tmp_path: Path, script_name: str) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    invoked = tmp_path / "postgres-was-invoked"
    for command in ("pg_dump", "pg_restore"):
        _write_executable(
            fake_bin / command,
            '#!/usr/bin/env bash\nset -eu\nprintf invoked > "${FAKE_LOG}"\n',
        )
    env = _postgres_env(tmp_path=tmp_path, fake_bin=fake_bin)
    passfile = Path(env["PGPASSFILE"])
    _chmod(passfile, 0o644)
    assert _mode(passfile) == 0o644
    restore_file = tmp_path / "backup.dump"
    restore_file.write_text("fake-custom-archive", encoding="utf-8")
    env.update({
        "CINEGATE_BACKUP_DIR": str(tmp_path / "backups"),
        "CINEGATE_RESTORE_FILE": str(restore_file),
        "CINEGATE_ALLOW_RESTORE": "YES",
        "FAKE_LOG": str(invoked),
    })
    completed = _run_script(Path("scripts") / script_name, env)
    assert completed.returncode == 2, completed.stderr
    assert "PGPASSFILE must have mode 600" in completed.stderr
    assert not invoked.exists()
    assert not (tmp_path / "backups").exists()
