"""Tests for the ``session_artifacts`` migration (a7c3e1f04b28).

Verifies the migration creates the table with the expected shape, carries
no database-level foreign key (schema Rule R032 — the ``session_id`` /
``preview_artifact_id`` relationships are application-owned), indexes the
session listing, and downgrades cleanly.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import Engine

from omnigent.db.utils import (
    _build_alembic_config,
    clear_engine_cache,
    get_or_create_engine,
)

_PREVIOUS_HEAD = "d5e9f1a2b3c4"


@pytest.fixture
def db_engine(tmp_path: Path) -> Iterator[Engine]:
    """Fresh SQLite DB with the full migration chain applied; cleaned up after."""
    db_path = tmp_path / "test.db"
    uri = f"sqlite:///{db_path}"
    engine = get_or_create_engine(uri)
    try:
        yield engine
    finally:
        clear_engine_cache()


def test_migration_creates_table(db_engine: Engine) -> None:
    """``session_artifacts`` exists after migrating to head."""
    assert "session_artifacts" in set(sa.inspect(db_engine).get_table_names())


def test_session_artifacts_columns(db_engine: Engine) -> None:
    """The table has the full expected column set."""
    cols = {c["name"] for c in sa.inspect(db_engine).get_columns("session_artifacts")}
    assert cols == {
        "workspace_id",
        "id",
        "session_id",
        "created_at",
        "filename",
        "content_type",
        "bytes",
        "title",
        "description",
        "preview_artifact_id",
    }


def test_render_category_is_not_a_column(db_engine: Engine) -> None:
    """Render category is derived from ``content_type``, never persisted."""
    cols = {c["name"] for c in sa.inspect(db_engine).get_columns("session_artifacts")}
    assert "render_category" not in cols


def test_no_foreign_keys(db_engine: Engine) -> None:
    """Schema Rule R032: relationships are application-enforced, not DB FKs."""
    assert sa.inspect(db_engine).get_foreign_keys("session_artifacts") == []


def test_session_listing_index_exists(db_engine: Engine) -> None:
    """The per-session, newest-first listing is served by a composite index."""
    indexes = {
        i["name"]: i["column_names"]
        for i in sa.inspect(db_engine).get_indexes("session_artifacts")
    }
    assert indexes["ix_session_artifacts_session_id_created_at"] == [
        "workspace_id",
        "session_id",
        "created_at",
        "id",
    ]


def test_downgrade_drops_table(tmp_path: Path) -> None:
    """Downgrading one step removes the table; re-upgrade restores it."""
    db_path = tmp_path / "downgrade.db"
    uri = f"sqlite:///{db_path}"
    engine = get_or_create_engine(uri)
    assert "session_artifacts" in set(sa.inspect(engine).get_table_names())

    config = _build_alembic_config(uri)
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, _PREVIOUS_HEAD)
    assert "session_artifacts" not in set(sa.inspect(engine).get_table_names())

    # Re-upgrade restores it — proves the upgrade is replayable.
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "a7c3e1f04b28")
    assert "session_artifacts" in set(sa.inspect(engine).get_table_names())

    engine.dispose()
