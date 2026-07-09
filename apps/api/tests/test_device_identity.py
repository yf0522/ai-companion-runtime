from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from app.runtime.device_identity import (
    _digest_secret,
    advance_device_sequence,
    enroll_device,
    require_next_sequence,
    validate_ota_release_state,
    validate_secure_transport_config,
)


def test_device_secure_transport_rejects_ws_in_production():
    with pytest.raises(ValueError, match="wss://"):
        validate_secure_transport_config("ws://device.example/ws/device/realtime", production=True)


def test_device_secure_transport_accepts_wss_in_production():
    validate_secure_transport_config("wss://device.example/ws/device/realtime", production=True)


def test_device_sequence_rejects_replay_and_gaps():
    assert require_next_sequence(1, 0) == 1
    with pytest.raises(ValueError, match="sequence_replay"):
        require_next_sequence(1, 1)
    with pytest.raises(ValueError, match="sequence_gap"):
        require_next_sequence(3, 1)
    with pytest.raises(ValueError, match="sequence_required"):
        require_next_sequence(None, 1)


def test_ota_release_defaults_to_pending_evidence_boundary():
    validate_ota_release_state(
        signature=None,
        signing_key_id=None,
        verification_state="pending_evidence",
    )


def test_ota_release_cannot_be_marked_verified_without_board_evidence():
    with pytest.raises(ValueError, match="physical board evidence"):
        validate_ota_release_state(
            signature="sig",
            signing_key_id="key-1",
            verification_state="verified",
        )


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _RowResult:
    def __init__(self, value):
        self._value = value

    def one_or_none(self):
        return self._value


class _LockedBegin:
    def __init__(self, lock: asyncio.Lock):
        self._lock = lock

    async def __aenter__(self):
        await self._lock.acquire()

    async def __aexit__(self, exc_type, exc, tb):
        self._lock.release()


class _EnrollmentSession:
    def __init__(self, store: SimpleNamespace):
        self.store = store
        self.added = []

    def in_transaction(self):
        return False

    def begin(self):
        return _LockedBegin(self.store.lock)

    async def execute(self, statement):
        assert statement._for_update_arg is not None
        return _ScalarResult(self.store.credential)

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        self.added[-1].id = uuid.uuid4()

    async def refresh(self, item):
        return None


@pytest.mark.asyncio
async def test_enrollment_credential_concurrent_consume_only_allows_one_device():
    secret = "enroll-secret"
    credential = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        secret_hash=_digest_secret(secret),
        state="issued",
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5),
        used_by_device_id=None,
        used_at=None,
    )
    store = SimpleNamespace(lock=asyncio.Lock(), credential=credential)

    async def run_enroll(index: int):
        return await enroll_device(
            _EnrollmentSession(store),
            credential_id=credential.id,
            secret=secret,
            external_id=f"device-{index}",
            display_name=None,
            capabilities={},
            firmware_version=None,
        )

    results = await asyncio.gather(run_enroll(1), run_enroll(2), return_exceptions=True)

    successes = [result for result in results if not isinstance(result, Exception)]
    failures = [result for result in results if isinstance(result, HTTPException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].status_code == 401
    assert credential.state == "used"
    assert credential.used_by_device_id == successes[0][0].id


class _SequenceSession:
    def __init__(self, store: SimpleNamespace):
        self.store = store
        self.committed = False

    async def execute(self, statement, params=None):
        if getattr(statement, "is_update", False):
            assert params is not None
            async with self.store.lock:
                if (
                    params["p_device_id"] == self.store.device_id
                    and params["p_previous_sequence"] == self.store.high_watermark
                    and self.store.status == "enrolled"
                    and self.store.credential_state == "active"
                    and self.store.revoked_at is None
                ):
                    self.store.high_watermark = params["p_sequence"]
                    return _ScalarResult(self.store.high_watermark)
                return _ScalarResult(None)
        if getattr(statement, "is_select", False):
            return _RowResult(
                (
                    self.store.high_watermark,
                    self.store.status,
                    self.store.credential_state,
                    self.store.revoked_at,
                )
            )
        raise AssertionError("unexpected statement")

    def add(self, item):
        raise AssertionError("receipt insert not expected")

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_sequence_high_watermark_concurrent_same_seq_allows_one_success():
    store = SimpleNamespace(
        lock=asyncio.Lock(),
        device_id=uuid.uuid4(),
        high_watermark=0,
        status="enrolled",
        credential_state="active",
        revoked_at=None,
    )

    async def advance_once():
        await advance_device_sequence(
            _SequenceSession(store),
            device_id=store.device_id,
            sequence=1,
        )

    results = await asyncio.gather(advance_once(), advance_once(), return_exceptions=True)

    assert sum(result is None for result in results) == 1
    failures = [result for result in results if isinstance(result, ValueError)]
    assert len(failures) == 1
    assert str(failures[0]) == "sequence_replay"
    assert store.high_watermark == 1
