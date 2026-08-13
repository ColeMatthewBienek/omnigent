"""Tests for suite-wide runtime data-dir isolation.

A developer machine keeps live state under ``~/.omnigent``: the
``host.pid`` / ``local_server.pid`` records of a *running* daemon and
server. Any test that resolves the runtime data dir to that directory can
read those pids, and helpers reaching ``ensure_local_omnigent_server`` will
stop the server they name — killing the developer's own server mid-run.

Covers the two halves of the defence: paths are resolved per call (so
``OMNIGENT_DATA_DIR`` exported after import still wins) and the conftest
guard fails a test whose data dir resolves to the real one.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from omnigent import cli
from omnigent.host import local_server
from tests.conftest import _REAL_USER_DATA_DIR, assert_isolated_data_dir


def test_session_fixture_redirects_the_data_dir_away_from_the_real_one() -> None:
    """The autouse session fixture is in force for every test."""
    assert os.environ.get("OMNIGENT_DATA_DIR")
    assert local_server._local_data_dir() != _REAL_USER_DATA_DIR


def test_daemon_registry_paths_follow_a_data_dir_set_after_import(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``cli``'s daemon paths honor ``OMNIGENT_DATA_DIR`` set after import.

    ``_HOST_PID_PATH`` used to be a module constant built from
    ``Path.home()`` at import, and the daemon registry hung off its parent
    — so no later export could move either, and a test process read the
    real daemon's records no matter what it set.
    """
    monkeypatch.setenv("OMNIGENT_DATA_DIR", str(tmp_path))
    assert cli._host_pid_path() == tmp_path / "host.pid"
    assert cli._daemon_registry_dir() == tmp_path / "daemons"
    assert cli._daemon_record_path("local").parent == tmp_path / "daemons"

    moved = tmp_path / "moved"
    monkeypatch.setenv("OMNIGENT_DATA_DIR", str(moved))
    assert cli._host_pid_path() == moved / "host.pid"
    assert cli._daemon_registry_dir() == moved / "daemons"


def test_daemon_record_paths_are_never_import_time_constants() -> None:
    """The record paths must stay accessors, not module constants.

    A constant is what broke isolation; this fails loudly if one comes
    back rather than waiting for the next killed daemon to reveal it.
    Config-home paths (``config.yaml``, the agents dir) are deliberately
    out of scope — they answer to ``OMNIGENT_CONFIG_HOME``, which isolates
    config only and never moves the runtime data dir.
    """
    frozen = [
        f"{module.__name__}.{name}"
        for module, name in (
            (local_server, "_LOCAL_SERVER_PID_PATH"),
            (local_server, "_LOCAL_SERVER_SIG_PATH"),
            (local_server, "_LOCAL_SERVER_LOG_REF_PATH"),
            (cli, "_HOST_PID_PATH"),
        )
        if isinstance(getattr(module, name, None), Path)
    ]
    assert frozen == [], f"data-dir paths frozen at import: {frozen}"


def test_guard_fails_when_the_data_dir_is_the_real_user_data_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard trips when resolution lands on the developer's own dir.

    Only the path is resolved here — nothing reads or writes it — so the
    check itself is safe to exercise against the real location.
    """
    monkeypatch.setenv("OMNIGENT_DATA_DIR", str(_REAL_USER_DATA_DIR))

    with pytest.raises(AssertionError, match="resolved the runtime data dir to the real"):
        assert_isolated_data_dir("tests/test_x.py::test_y", "before")


def test_guard_fails_when_the_data_dir_override_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clearing the override falls back to ``~/.omnigent`` — also a failure.

    The likelier regression is not a test naming the real dir outright but
    a fixture that deletes ``OMNIGENT_DATA_DIR`` and lets ``Path.home()``
    take over.
    """
    monkeypatch.delenv("OMNIGENT_DATA_DIR", raising=False)

    with pytest.raises(AssertionError, match="resolved the runtime data dir to the real"):
        assert_isolated_data_dir("tests/test_x.py::test_y", "after")


def test_guard_passes_for_an_isolated_data_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A tmp data dir passes — the guard flags only the real one."""
    monkeypatch.setenv("OMNIGENT_DATA_DIR", str(tmp_path))
    assert_isolated_data_dir("tests/test_x.py::test_y", "before")
