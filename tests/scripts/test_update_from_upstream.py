"""Regression checks for the upstream-update helper's basic interface."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts" / "update-from-upstream.sh"


def test_update_from_upstream_help_and_syntax() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)

    result = subprocess.run([str(SCRIPT), "--help"], check=True, capture_output=True, text=True)

    assert "--check-only" in result.stdout
    assert "--allow-dirty" in result.stdout


@pytest.mark.parametrize(
    (
        "database_exists",
        "current_output",
        "expected_output",
        "expects_warning",
        "expects_current_check",
    ),
    [
        (
            True,
            "e2b9c5f18a3d (head)\n",
            "PASS: database revision matches the Alembic head.",
            False,
            True,
        ),
        (
            True,
            "a1b2c3d4e5f6\n",
            "Database current revision: a1b2c3d4e5f6",
            True,
            True,
        ),
        (True, "", "Database current revision: <none>", True, True),
        (False, "", "skipping database migration drift check.", False, False),
    ],
)
def test_update_from_upstream_reports_database_migration_drift(
    tmp_path: Path,
    database_exists: bool,
    current_output: str,
    expected_output: str,
    expects_warning: bool,
    expects_current_check: bool,
) -> None:
    database_path = tmp_path / "chat.db"
    if database_exists:
        database_path.touch()
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    environment_log = tmp_path / "uv-environment.log"
    command_log = tmp_path / "uv-commands.log"
    (shim_dir / "git").write_text("#!/usr/bin/env bash\nprintf 'true\\n'\n")
    (shim_dir / "uv").write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$OMNIGENT_DB_URL" >> "$UV_ENVIRONMENT_LOG"\n'
        'printf \'%s\\n\' "$*" >> "$UV_COMMAND_LOG"\n'
        'case "$*" in\n'
        "  *' alembic '*' heads') printf 'e2b9c5f18a3d (head)\\n' ;;\n"
        "  *' alembic '*' current') printf '%s' \"$ALEMBIC_CURRENT_OUTPUT\" ;;\n"
        "esac\n"
    )
    for shim in shim_dir.iterdir():
        shim.chmod(0o755)

    environment = {
        **os.environ,
        "ALEMBIC_CURRENT_OUTPUT": current_output,
        "HOME": str(tmp_path),
        "OMNIGENT_DB_URL": f"sqlite:///{database_path}",
        "PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}",
        "UV_ENVIRONMENT_LOG": str(environment_log),
        "UV_COMMAND_LOG": str(command_log),
    }
    result = subprocess.run(
        [str(SCRIPT), "--check-only"],
        check=True,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert expected_output in result.stdout
    assert ("WARNING: DATABASE MIGRATION DRIFT DETECTED" in result.stderr) is expects_warning
    assert set(environment_log.read_text().splitlines()) == {environment["OMNIGENT_DB_URL"]}
    assert (
        "alembic -c omnigent/db/alembic.ini current" in command_log.read_text()
    ) is expects_current_check
