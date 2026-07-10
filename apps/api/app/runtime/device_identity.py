from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import bindparam, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.db.device_models import (
    Device,
    DeviceCommandReceipt,
    DeviceEnrollmentCredential,
    DeviceOtaRelease,
)

MAX_DEVICE_MESSAGE_BYTES = 16_384
MAX_AUDIO_FRAME_BYTES = 8_192
MAX_AUDIO_TURN_BYTES = 1_000_000
SUPPORTED_SAMPLE_RATES = {8000, 16000, 24000}
SECURE_TRANSPORT_SCHEMES = ("wss://",)


@dataclass(frozen=True)
class EnrollmentSecret:
    credential_id: str
    secret: str


@dataclass(frozen=True)
class DevicePrincipal:
    device_id: str
    user_id: str
    external_id: str
    capabilities: dict[str, Any]
    firmware_version: str | None
    sequence_high_watermark: int = 0


def _digest_secret(secret: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), secret.encode(), hashlib.sha256).hexdigest()


def new_device_secret() -> str:
    return secrets.token_urlsafe(32)


def validate_secure_transport_config(uri: str, *, production: bool | None = None) -> None:
    is_prod = settings.app_env.lower() == "production" if production is None else production
    if is_prod and not uri.startswith(SECURE_TRANSPORT_SCHEMES):
        raise ValueError("production device transport must use wss://")


def validate_ota_release_state(
    *, signature: str | None, signing_key_id: str | None, verification_state: str
) -> None:
    allowed = {"pending_evidence", "rejected"}
    if verification_state == "verified":
        if not signature or not signing_key_id:
            raise ValueError("verified OTA releases require signature and signing key evidence")
        raise ValueError("physical board evidence is required before marking OTA verified")
    if verification_state not in allowed:
        raise ValueError("OTA verification_state must be pending_evidence or rejected")


def require_next_sequence(sequence: Any, high_watermark: int) -> int:
    if not isinstance(sequence, int) or sequence <= 0:
        raise ValueError("sequence_required")
    if sequence <= high_watermark:
        raise ValueError("sequence_replay")
    if sequence != high_watermark + 1:
        raise ValueError("sequence_gap")
    return sequence


async def issue_enrollment_credential(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    ttl_minutes: int = 30,
) -> EnrollmentSecret:
    secret = new_device_secret()
    credential = DeviceEnrollmentCredential(
        user_id=user_id,
        secret_hash=_digest_secret(secret),
        state="issued",
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).replace(
            tzinfo=None
        ),
    )
    db.add(credential)
    await db.commit()
    await db.refresh(credential)
    return EnrollmentSecret(credential_id=str(credential.id), secret=secret)


async def enroll_device(
    db: AsyncSession,
    *,
    credential_id: uuid.UUID,
    secret: str,
    external_id: str,
    display_name: str | None,
    capabilities: dict[str, Any],
    firmware_version: str | None,
) -> tuple[Device, str]:
    now = datetime.now(timezone.utc)
    now_naive = now.replace(tzinfo=None)

    async def _consume_locked() -> tuple[Device, str]:
        result = await db.execute(
            select(DeviceEnrollmentCredential)
            .where(DeviceEnrollmentCredential.id == credential_id)
            .with_for_update()
        )
        credential = result.scalar_one_or_none()
        if (
            credential is None
            or credential.state != "issued"
            or credential.expires_at < now_naive
            or not hmac.compare_digest(credential.secret_hash, _digest_secret(secret))
        ):
            raise HTTPException(status_code=401, detail="Invalid or expired enrollment credential")

        device_secret = new_device_secret()
        device = Device(
            user_id=credential.user_id,
            external_id=external_id,
            display_name=display_name,
            credential_hash=_digest_secret(device_secret),
            capabilities_json=capabilities,
            firmware_version=firmware_version,
        )
        db.add(device)
        await db.flush()
        credential.state = "used"
        credential.used_by_device_id = device.id
        credential.used_at = now_naive
        return device, device_secret

    if getattr(db, "in_transaction", lambda: False)():
        device, device_secret = await _consume_locked()
        await db.commit()
    else:
        async with db.begin():
            device, device_secret = await _consume_locked()
    await db.refresh(device)
    return device, device_secret


async def _load_sequence_conflict(db: AsyncSession, *, device_id: uuid.UUID) -> tuple[int, str, str, datetime | None] | None:
    result = await db.execute(
        select(
            Device.sequence_high_watermark,
            Device.status,
            Device.credential_state,
            Device.revoked_at,
        ).where(Device.id == device_id)
    )
    row = result.one_or_none()
    if row is None:
        return None
    return row[0], row[1], row[2], row[3]


def _raise_sequence_conflict(
    *,
    sequence: int,
    current_high_watermark: int,
    status: str,
    credential_state: str,
    revoked_at: datetime | None,
) -> None:
    if status != "enrolled" or credential_state != "active" or revoked_at is not None:
        raise ValueError("device_not_active")
    if sequence <= current_high_watermark:
        raise ValueError("sequence_replay")
    raise ValueError("sequence_gap")


async def _advance_sequence_watermark(
    db: AsyncSession,
    *,
    device_id: uuid.UUID,
    sequence: int,
    values: dict[str, Any] | None = None,
) -> None:
    if not isinstance(sequence, int) or sequence <= 0:
        raise ValueError("sequence_required")
    update_values: dict[str, Any] = {
        "sequence_high_watermark": bindparam("p_sequence"),
        "updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
    }
    if values:
        update_values.update(values)
    result = await db.execute(
        update(Device)
        .where(
            Device.id == bindparam("p_device_id"),
            Device.status == "enrolled",
            Device.credential_state == "active",
            Device.revoked_at.is_(None),
            Device.sequence_high_watermark == bindparam("p_previous_sequence"),
        )
        .values(**update_values)
        .returning(Device.sequence_high_watermark),
        {
            "p_device_id": device_id,
            "p_previous_sequence": sequence - 1,
            "p_sequence": sequence,
        },
    )
    if result.scalar_one_or_none() == sequence:
        return

    conflict = await _load_sequence_conflict(db, device_id=device_id)
    if conflict is None:
        raise HTTPException(status_code=404, detail="Device not found")
    current_high_watermark, status, credential_state, revoked_at = conflict
    _raise_sequence_conflict(
        sequence=sequence,
        current_high_watermark=current_high_watermark,
        status=status,
        credential_state=credential_state,
        revoked_at=revoked_at,
    )


async def authenticate_device(
    db: AsyncSession,
    *,
    device_id: str,
    device_secret: str,
) -> DevicePrincipal | None:
    try:
        db_device_id = uuid.UUID(device_id)
    except (TypeError, ValueError):
        return None
    device = await db.get(Device, db_device_id)
    if (
        device is None
        or device.status != "enrolled"
        or device.credential_state != "active"
        or device.revoked_at is not None
        or not hmac.compare_digest(device.credential_hash, _digest_secret(device_secret))
    ):
        return None
    return DevicePrincipal(
        device_id=str(device.id),
        user_id=str(device.user_id),
        external_id=device.external_id,
        capabilities=device.capabilities_json or {},
        firmware_version=device.firmware_version,
        sequence_high_watermark=device.sequence_high_watermark,
    )


async def authenticate_device_from_message(data: dict[str, Any]) -> DevicePrincipal | None:
    from app.db.session import async_session

    if data.get("type") != "auth" or data.get("auth_type") != "device":
        return None
    device_id = data.get("device_id")
    secret = data.get("credential")
    if not isinstance(device_id, str) or not isinstance(secret, str):
        return None
    async with async_session() as db:
        principal = await authenticate_device(db, device_id=device_id, device_secret=secret)
        if principal is not None:
            device = await db.get(Device, uuid.UUID(principal.device_id))
            if device is not None:
                device.firmware_version = data.get("firmware_version") or device.firmware_version
                if isinstance(data.get("capabilities"), dict):
                    device.capabilities_json = data["capabilities"]
                await db.commit()
        return principal


async def revoke_device(db: AsyncSession, *, device_id: uuid.UUID, reason: str | None) -> None:
    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    device.status = "revoked"
    device.credential_state = "revoked"
    device.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    device.revoke_reason = reason
    await db.commit()


async def record_heartbeat(
    db: AsyncSession,
    *,
    device_id: uuid.UUID,
    sequence: int,
    health: dict[str, Any],
    firmware_version: str | None = None,
) -> None:
    values: dict[str, Any] = {
        "last_heartbeat_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "last_health_json": health,
    }
    if firmware_version:
        values["firmware_version"] = firmware_version
    await _advance_sequence_watermark(
        db,
        device_id=device_id,
        sequence=sequence,
        values=values,
    )
    await db.commit()


async def record_receipt(
    db: AsyncSession,
    *,
    device_id: uuid.UUID,
    command_id: str,
    receipt_type: str,
    sequence: int,
    metadata: dict[str, Any],
) -> None:
    await _advance_sequence_watermark(db, device_id=device_id, sequence=sequence)
    db.add(
        DeviceCommandReceipt(
            device_id=device_id,
            command_id=command_id,
            receipt_type=receipt_type,
            sequence=sequence,
            metadata_json=metadata,
        )
    )
    await db.commit()


async def advance_device_sequence(
    db: AsyncSession,
    *,
    device_id: uuid.UUID,
    sequence: int,
    health: dict[str, Any] | None = None,
    firmware_version: str | None = None,
    command_id: str | None = None,
    receipt_type: str | None = None,
    receipt_metadata: dict[str, Any] | None = None,
) -> None:
    values: dict[str, Any] = {}
    if health is not None:
        values["last_heartbeat_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
        values["last_health_json"] = health
    if firmware_version:
        values["firmware_version"] = firmware_version
    await _advance_sequence_watermark(
        db,
        device_id=device_id,
        sequence=sequence,
        values=values,
    )
    if command_id is not None and receipt_type is not None:
        db.add(
            DeviceCommandReceipt(
                device_id=device_id,
                command_id=command_id,
                receipt_type=receipt_type,
                sequence=sequence,
                metadata_json=receipt_metadata or {},
            )
        )
    await db.commit()


async def create_ota_release(
    db: AsyncSession,
    *,
    version: str,
    artifact_url: str,
    artifact_sha256: str,
    signature: str | None = None,
    signing_key_id: str | None = None,
    verification_state: str = "pending_evidence",
    pending_evidence: dict[str, Any] | None = None,
) -> DeviceOtaRelease:
    validate_ota_release_state(
        signature=signature,
        signing_key_id=signing_key_id,
        verification_state=verification_state,
    )
    release = DeviceOtaRelease(
        version=version,
        artifact_url=artifact_url,
        artifact_sha256=artifact_sha256,
        signature=signature,
        signing_key_id=signing_key_id,
        verification_state=verification_state,
        pending_evidence=pending_evidence
        or {"required": ["real_signing_key", "board_flash_log", "boot_verification_log"]},
    )
    db.add(release)
    await db.commit()
    await db.refresh(release)
    return release


async def list_devices_for_user(db: AsyncSession, *, user_id: uuid.UUID) -> list[Device]:
    result = await db.execute(select(Device).where(Device.user_id == user_id).order_by(Device.created_at.desc()))
    return list(result.scalars().all())
