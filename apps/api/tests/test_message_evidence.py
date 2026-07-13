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


class _Parent:
    def __init__(self, user_id):
        self.user_id = user_id

    @property
    def message_count(self):
        raise AssertionError("Session.message_count must not participate in allocation")


class _Session:
    def __init__(self, *, user_id=None, max_index=4, fail_flush=False):
        self.user_id = user_id or uuid.uuid4()
        self.scalars = [_Parent(self.user_id), max_index]
        self.added = []
        self.fail_flush = fail_flush
        self.queries = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def begin(self):
        return _Begin()

    async def scalar(self, query):
        self.queries.append(query)
        return self.scalars.pop(0)

    def add_all(self, rows):
        self.added = list(rows)
        for row in self.added:
            if row.id is None:
                row.id = uuid.uuid4()

    async def flush(self):
        if self.fail_flush:
            raise IntegrityError("insert", {}, Exception("duplicate"))


@pytest.mark.asyncio
async def test_persist_turn_allocates_max_plus_one_without_message_count(monkeypatch):
    user_id = uuid.uuid4()
    session = _Session(user_id=user_id, max_index=4)
    monkeypatch.setattr(message_evidence, "async_session", lambda: session)
    result = await message_evidence.persist_turn_messages(
        session_id=str(uuid.uuid4()),
        user_id=str(user_id),
        trace_id="trace-1",
        user_content="你好",
        assistant_content="您好",
    )
    assert (result.user_message_index, result.assistant_message_index) == (5, 6)
    assert [row.message_index for row in session.added] == [5, 6]
    assert [row.role for row in session.added] == ["user", "assistant"]
    queries = [str(query) for query in session.queries]
    assert session.queries[0]._for_update_arg is not None
    assert "FOR UPDATE" in queries[0]


@pytest.mark.asyncio
async def test_persist_turn_retries_integrity_error_once(monkeypatch):
    user_id = uuid.uuid4()
    sessions = iter([
        _Session(user_id=user_id, fail_flush=True),
        _Session(user_id=user_id, max_index=8),
    ])
    monkeypatch.setattr(message_evidence, "async_session", lambda: next(sessions))
    result = await message_evidence.persist_turn_messages(
        session_id=str(uuid.uuid4()),
        user_id=str(user_id),
        trace_id="trace-2",
        user_content="用户",
        assistant_content="助手",
    )
    assert result.user_message_index == 9


@pytest.mark.asyncio
async def test_persist_turn_stops_after_exactly_two_integrity_attempts(monkeypatch):
    created = []
    user_id = uuid.uuid4()

    def make_session():
        session = _Session(user_id=user_id, fail_flush=True)
        created.append(session)
        return session

    monkeypatch.setattr(message_evidence, "async_session", make_session)
    with pytest.raises(IntegrityError):
        await message_evidence.persist_turn_messages(
            session_id=str(uuid.uuid4()),
            user_id=str(user_id),
            trace_id="trace-two-attempts",
            user_content="用户",
            assistant_content="助手",
        )

    assert len(created) == 2
    assert all(len(session.added) == 2 for session in created)


@pytest.mark.asyncio
async def test_persist_turn_uses_explicit_assistant_uuid_and_rejects_wrong_owner(monkeypatch):
    owner_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    session = _Session(user_id=owner_id)
    monkeypatch.setattr(message_evidence, "async_session", lambda: session)

    result = await message_evidence.persist_turn_messages(
        session_id=str(uuid.uuid4()),
        user_id=str(owner_id),
        trace_id="trace-explicit",
        user_content="用户",
        assistant_content="助手",
        assistant_message_id=str(assistant_id),
    )

    assert result.assistant_message_id == str(assistant_id)
    assert session.added[1].id == assistant_id

    wrong_owner = _Session(user_id=owner_id)
    monkeypatch.setattr(message_evidence, "async_session", lambda: wrong_owner)
    with pytest.raises(PermissionError):
        await message_evidence.persist_turn_messages(
            session_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
            trace_id="trace-forbidden",
            user_content="用户",
            assistant_content="助手",
        )
