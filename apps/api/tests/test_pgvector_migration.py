from __future__ import annotations

import importlib
from contextlib import AbstractContextManager
from unittest.mock import MagicMock


MIGRATION = "app.db.migrations.versions.a1b2c3d4e5f6_add_pgvector_embedding"


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
    assert execute.call_count == 3
    assert "vector(1536)" in execute.call_args_list[1].args[0]
