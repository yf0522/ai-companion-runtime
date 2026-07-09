from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.workers.reflection_worker import _accept_reflection_proposal, _reflect


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


@pytest.mark.asyncio
async def test_reflection_creates_proposal_without_profile_mutation(monkeypatch):
    added = []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def execute(self, stmt):
            return _Result(None)

        def add(self, value):
            added.append(value)

        async def commit(self):
            return None

    monkeypatch.setattr(
        "app.storage.working_memory.get_working_memory",
        AsyncMock(return_value=[{"role": "user", "content": "我叫张三，我住在上海"}]),
        raising=False,
    )
    monkeypatch.setattr("app.db.session.async_session", lambda: _Session())

    await _reflect(
        "4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf",
        "06cb56ba-d9c8-4d8f-a9d9-6b65ec2b9a77",
    )

    assert len(added) == 1
    proposal = added[0]
    assert proposal.target_type == "user_profile"
    assert proposal.status == "proposed"
    assert proposal.proposed_json == {"name": "张三", "location": "上海"}


@pytest.mark.asyncio
async def test_accept_reflection_proposal_mutates_profile_after_acceptance(monkeypatch):
    proposal = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.UUID("4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf"),
        target_type="user_profile",
        proposed_json={"name": "张三"},
        status="proposed",
        accepted_by=None,
        accepted_at=None,
    )
    profile = SimpleNamespace(profile_json={"city": "上海"}, version=1)

    class _Session:
        def __init__(self):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def execute(self, stmt):
            self.calls += 1
            return _Result(proposal if self.calls == 1 else profile)

        async def commit(self):
            return None

    monkeypatch.setattr("app.db.session.async_session", lambda: _Session())

    accepted = await _accept_reflection_proposal(
        str(proposal.id),
        str(proposal.user_id),
    )

    assert accepted is True
    assert profile.profile_json == {"city": "上海", "name": "张三"}
    assert profile.version == 2
    assert proposal.status == "accepted"
    assert proposal.accepted_by == proposal.user_id


@pytest.mark.asyncio
async def test_accept_reflection_rejects_cross_user_proposal(monkeypatch):
    proposal = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        target_type="user_profile",
        proposed_json={"name": "不应写入"},
        status="proposed",
    )

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def execute(self, _stmt):
            return _Result(proposal)

    monkeypatch.setattr("app.db.session.async_session", lambda: _Session())

    accepted = await _accept_reflection_proposal(str(proposal.id), str(uuid.uuid4()))

    assert accepted is False
