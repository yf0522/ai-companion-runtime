from __future__ import annotations

import importlib
from contextlib import AbstractContextManager
from unittest.mock import MagicMock

import pytest


MIGRATION = "app.db.migrations.versions.a1b2c3d4e5f6_add_pgvector_embedding"
ENFORCEMENT_MIGRATION = (
    "app.db.migrations.versions.c1d2e3f4a5b6_enforce_pgvector_schema"
)


class _Savepoint(AbstractContextManager):
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.in_savepoint = True
        return self

    def __exit__(self, exc_type, _exc, _tb):
        self.connection.in_savepoint = False
        if exc_type is not None:
            self.connection.savepoint_rolled_back = True
        return False


class _Connection:
    def __init__(self, *, extension_available: bool):
        self.extension_available = extension_available
        self.in_savepoint = False
        self.savepoint_rolled_back = False
        self.outer_transaction_usable = True

    def begin_nested(self):
        return _Savepoint(self)

    def execute(self, _statement):
        if not self.extension_available:
            if not self.in_savepoint:
                self.outer_transaction_usable = False
            raise RuntimeError("provider secret SQL extension failure")


def test_pgvector_unavailable_rolls_back_savepoint_without_poisoning_outer_transaction(monkeypatch):
    migration = importlib.import_module(MIGRATION)
    connection = _Connection(extension_available=False)
    execute = MagicMock()
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
    monkeypatch.setattr(migration.op, "execute", execute)

    with pytest.raises(RuntimeError, match="install the vector extension"):
        migration.upgrade()

    assert connection.savepoint_rolled_back is True
    assert connection.outer_transaction_usable is True
    execute.assert_not_called()


def test_pgvector_available_applies_vector_column_and_index(monkeypatch):
    migration = importlib.import_module(MIGRATION)
    connection = _Connection(extension_available=True)
    execute = MagicMock()
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
    monkeypatch.setattr(migration.op, "execute", execute)

    migration.upgrade()

    assert connection.savepoint_rolled_back is False
    assert execute.call_count == 2
    statements = [call.args[0] for call in execute.call_args_list]
    assert "ALTER COLUMN embedding TYPE vector(1536)" in statements[0]
    assert "USING CASE" in statements[0]
    assert "valid 1536-dimensional pgvector literal" in statements[0]
    assert "DROP COLUMN" not in "\n".join(statements)
    assert "ADD COLUMN embedding" not in "\n".join(statements)
    assert "USING hnsw (embedding vector_cosine_ops)" in statements[1]


def test_legacy_pgvector_downgrade_preserves_embedding_text(monkeypatch):
    migration = importlib.import_module(MIGRATION)
    execute = MagicMock()
    monkeypatch.setattr(migration.op, "execute", execute)

    migration.downgrade()

    statements = [call.args[0] for call in execute.call_args_list]
    assert statements == [
        "DROP INDEX IF EXISTS idx_memory_embeddings_vector",
        "ALTER TABLE memory_embeddings "
        "ALTER COLUMN embedding TYPE text USING embedding::text",
    ]


def test_production_workflow_covers_populated_legacy_upgrade_and_fresh_bootstrap():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    workflow = (root / ".github/workflows/production-contracts.yml").read_text(encoding="utf-8")
    assert 'command.upgrade(config, "392b03f56f9f")' in workflow
    assert "INSERT INTO memory_embeddings" in workflow
    assert 'command.upgrade(config, "head")' in workflow
    assert "assert preserved_embedding == seeded_embedding" in workflow
    assert "assert_c1_downgrade_fidelity" in workflow
    assert 'command.downgrade(config, "b0c1d2e3f4a5")' in workflow
    downgrade_contract = workflow.split(
        "async def assert_c1_downgrade_fidelity() -> None:", 1
    )[1].split("script_heads =", 1)[0]
    assert 'assert embedding_type == "vector(1536)"' in downgrade_contract
    assert "USING hnsw (embedding vector_cosine_ops)" in downgrade_contract
    assert "assert preserved_embedding == seeded_embedding" in downgrade_contract
    downgrade_step = workflow.index('command.downgrade(config, "b0c1d2e3f4a5")')
    assert workflow.index('command.upgrade(config, "head")', downgrade_step) > downgrade_step
    assert 'command.downgrade(config, "base")' in workflow


def test_additive_head_requires_extension_vector_dimension_and_hnsw_index(monkeypatch):
    migration = importlib.import_module(ENFORCEMENT_MIGRATION)
    execute = MagicMock()
    bind = MagicMock()
    bind.execute.return_value.scalar_one_or_none.side_effect = ["vector(1536)", None]
    context = MagicMock()
    monkeypatch.setattr(migration.op, "execute", execute)
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
    monkeypatch.setattr(migration.op, "get_context", lambda: context)

    migration.upgrade()

    statements = [call.args[0] for call in execute.call_args_list]
    assert migration.down_revision == "b0c1d2e3f4a5"
    assert len(statements) == 5
    assert "CREATE EXTENSION IF NOT EXISTS vector" in statements[0]
    assert "DROP INDEX CONCURRENTLY IF EXISTS" in statements[1]
    assert "CREATE INDEX CONCURRENTLY" in statements[2]
    assert "DROP INDEX CONCURRENTLY IF EXISTS idx_memory_embeddings_vector" in statements[3]
    assert "RENAME TO idx_memory_embeddings_vector" in statements[4]
    context.autocommit_block.assert_called_once()


def test_additive_head_skips_correct_vector_index(monkeypatch):
    migration = importlib.import_module(ENFORCEMENT_MIGRATION)
    execute = MagicMock()
    bind = MagicMock()
    bind.execute.return_value.scalar_one_or_none.side_effect = [
        "vector(1536)",
        "CREATE INDEX idx_memory_embeddings_vector ON public.memory_embeddings USING hnsw (embedding vector_cosine_ops)",
    ]
    monkeypatch.setattr(migration.op, "execute", execute)
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)

    migration.upgrade()

    assert execute.call_count == 1


def test_additive_head_fails_closed_for_incompatible_embedding_column(monkeypatch):
    migration = importlib.import_module(ENFORCEMENT_MIGRATION)
    bind = MagicMock()
    bind.execute.return_value.scalar_one_or_none.return_value = "text"
    monkeypatch.setattr(migration.op, "execute", MagicMock())
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)

    with pytest.raises(RuntimeError, match="maintenance migration"):
        migration.upgrade()


def test_additive_head_fails_closed_when_extension_cannot_be_ensured(monkeypatch):
    migration = importlib.import_module(ENFORCEMENT_MIGRATION)
    execute = MagicMock(side_effect=RuntimeError("extension denied"))
    monkeypatch.setattr(migration.op, "execute", execute)

    with pytest.raises(RuntimeError, match="extension denied"):
        migration.upgrade()

    execute.assert_called_once()


def test_additive_head_downgrade_preserves_b0_vector_schema(monkeypatch):
    migration = importlib.import_module(ENFORCEMENT_MIGRATION)
    execute = MagicMock()
    monkeypatch.setattr(migration.op, "execute", execute)

    migration.downgrade()

    execute.assert_not_called()
