from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.observability import message_evidence


class _Begin:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _Session:
    def __init__(self, *, max_index=4, fail_flush=False):
        self.scalars = [object(), max_index]
        self.added = []
        self.fail_flush = fail_flush

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def begin(self):
        return _Begin()

    async def scalar(self, _query):
        return self.scalars.pop(0)

    def add_all(self, rows):
        self.added = list(rows)
        for row in self.added:
            row.id = uuid.uuid4()

    async def flush(self):
        if self.fail_flush:
            raise IntegrityError("insert", {}, Exception("duplicate"))


@pytest.mark.asyncio
async def test_persist_turn_allocates_max_plus_one_without_message_count(monkeypatch):
    session = _Session(max_index=4)
    monkeypatch.setattr(message_evidence, "async_session", lambda: session)
    result = await message_evidence.persist_turn_messages(
        session_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        trace_id="trace-1",
        user_content="你好",
        assistant_content="您好",
    )
    assert (result.user_message_index, result.assistant_message_index) == (5, 6)
    assert [row.message_index for row in session.added] == [5, 6]
    assert [row.role for row in session.added] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_persist_turn_retries_integrity_error_once(monkeypatch):
    sessions = iter([_Session(fail_flush=True), _Session(max_index=8)])
    monkeypatch.setattr(message_evidence, "async_session", lambda: next(sessions))
    result = await message_evidence.persist_turn_messages(
        session_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        trace_id="trace-2",
        user_content="用户",
        assistant_content="助手",
    )
    assert result.user_message_index == 9
