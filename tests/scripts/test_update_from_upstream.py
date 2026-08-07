"""Regression checks for the upstream-update helper's basic interface."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts" / "update-from-upstream.sh"


def test_update_from_upstream_help_and_syntax() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)

    result = subprocess.run([str(SCRIPT), "--help"], check=True, capture_output=True, text=True)

    assert "--check-only" in result.stdout
    assert "--allow-dirty" in result.stdout


def test_update_from_upstream_backs_up_the_real_database_and_checks_drift() -> None:
    script = SCRIPT.read_text()

    assert 'OMNIGENT_DB_URL="${OMNIGENT_DB_URL:-sqlite:///$HOME/.omnigent/chat.db}"' in script
    assert "export OMNIGENT_DB_URL" in script
    assert "chat.db.bak-update-$(date -u +%Y%m%dT%H%M%SZ)" in script
    assert 'cp "$database_path" "$database_backup_path"' in script
    assert 'cp "$database_path-wal" "$database_backup_path-wal"' in script
    assert 'cp "$database_path-shm" "$database_backup_path-shm"' in script
    assert "uv run alembic -c omnigent/db/alembic.ini current" in script
    assert "WARNING: DATABASE MIGRATION DRIFT DETECTED" in script
