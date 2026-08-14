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
from tests.conftest import (
    _REAL_USER_DATA_DIR,
    _reject_real_data_dir,
    assert_isolated_data_dir,
)


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


def test_guard_rejects_the_real_data_dir() -> None:
    """The canonical check rejects the developer's own dir.

    Called directly with a crafted path: nothing here reads, writes, or
    even resolves through the environment, so exercising it against the
    real location is safe.
    """
    with pytest.raises(AssertionError, match="developer's real"):
        _reject_real_data_dir(_REAL_USER_DATA_DIR, "a test")


def test_guard_rejects_a_noncanonical_path_to_the_real_data_dir() -> None:
    """``~/.omnigent/../.omnigent`` is the real dir wearing a disguise.

    A string comparison passes it straight through, which is why both sides
    are canonicalized before they are compared.
    """
    with pytest.raises(AssertionError, match="developer's real"):
        _reject_real_data_dir(_REAL_USER_DATA_DIR / ".." / ".omnigent", "a test")


def test_guard_rejects_a_path_inside_the_real_data_dir() -> None:
    """Writing under ``~/.omnigent`` is the same hazard as writing to it."""
    with pytest.raises(AssertionError, match="developer's real"):
        _reject_real_data_dir(_REAL_USER_DATA_DIR / "scratch" / "db", "a test")


def test_guard_rejects_a_symlink_to_the_real_data_dir(tmp_path: Path) -> None:
    """A symlink is a second name for the same directory, and is caught."""
    link = tmp_path / "sneaky"
    link.symlink_to(_REAL_USER_DATA_DIR, target_is_directory=True)

    with pytest.raises(AssertionError, match="developer's real"):
        _reject_real_data_dir(link, "a test")


def test_guard_accepts_a_lookalike_outside_the_real_data_dir(tmp_path: Path) -> None:
    """A path that merely *starts* like the real one is not the real one.

    Containment is checked on path components, so ``~/.omnigent-backup``
    must not be swept up by a prefix comparison.
    """
    _reject_real_data_dir(Path(f"{_REAL_USER_DATA_DIR}-backup"), "a test")
    _reject_real_data_dir(tmp_path / "data", "a test")


def test_guard_rejects_the_home_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clearing the override falls back to ``~/.omnigent`` — also a failure.

    The likelier regression is not a test naming the real dir outright but
    a fixture that deletes ``OMNIGENT_DATA_DIR`` and lets ``Path.home()``
    take over. The hook catches it at the resolution itself.
    """
    monkeypatch.delenv("OMNIGENT_DATA_DIR", raising=False)

    with pytest.raises(AssertionError, match="developer's real"):
        local_server._local_data_dir()


def test_guard_fires_mid_test_at_the_moment_of_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Isolation is enforced during the test, not only at its boundaries.

    A test that repoints ``OMNIGENT_DATA_DIR`` at the real dir inside its
    own body and restores it before teardown would slip past a check that
    only runs before and after. The session installs a hook inside
    :func:`_local_data_dir`, so the very call that would hand out the real
    path raises instead.
    """
    monkeypatch.setenv("OMNIGENT_DATA_DIR", str(_REAL_USER_DATA_DIR))

    with pytest.raises(AssertionError, match="developer's real"):
        local_server._local_data_dir()


def test_the_guard_cannot_be_disarmed_by_a_test(monkeypatch: pytest.MonkeyPatch) -> None:
    """Switching the hook off is itself an error, not an escape hatch.

    Without this, the mid-test protection is one ``monkeypatch.setattr``
    away from gone: disarm, resolve the real dir, restore, and the boundary
    check at teardown sees nothing wrong. The module refuses the assignment
    instead, so the bypass fails at the attempt.
    """
    with pytest.raises(AssertionError, match="Refusing to disarm"):
        monkeypatch.setattr(local_server, "_data_dir_guard", None)

    # Still armed afterwards.
    assert local_server._data_dir_guard is not None
    monkeypatch.setenv("OMNIGENT_DATA_DIR", str(_REAL_USER_DATA_DIR))
    with pytest.raises(AssertionError, match="developer's real"):
        local_server._local_data_dir()


def test_the_guard_cannot_be_replaced_with_a_permissive_one() -> None:
    """Nor swapped for a hook that waves everything through."""
    with pytest.raises(AssertionError, match="Refusing to disarm"):
        local_server._data_dir_guard = lambda resolved: None


def test_guard_hook_is_installed_for_every_test() -> None:
    """The hook must be live, or the mid-test window silently reopens."""
    assert local_server._data_dir_guard is not None


def test_guard_passes_for_an_isolated_data_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A tmp data dir passes — the guard flags only the real one."""
    monkeypatch.setenv("OMNIGENT_DATA_DIR", str(tmp_path))
    assert_isolated_data_dir("tests/test_x.py::test_y", "before")
    assert local_server._local_data_dir() == tmp_path
