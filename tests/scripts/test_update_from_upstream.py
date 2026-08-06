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
