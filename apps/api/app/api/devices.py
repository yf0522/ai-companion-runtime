from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.db.session import get_db
from app.runtime.device_identity import (
    create_ota_release,
    enroll_device,
    issue_enrollment_credential,
    list_devices_for_user,
    revoke_device,
    validate_secure_transport_config,
)

router = APIRouter(prefix="/devices", tags=["devices"])


class EnrollmentCredentialResponse(BaseModel):
    credential_id: str
    secret: str
    state: str = "issued"


class DeviceEnrollRequest(BaseModel):
    credential_id: uuid.UUID
    secret: str
    external_id: str = Field(min_length=3, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    firmware_version: str | None = Field(default=None, max_length=64)
    ws_server_uri: str


class DeviceEnrollResponse(BaseModel):
    device_id: str
    credential: str
    credential_state: str
    status: str


class DeviceResponse(BaseModel):
    device_id: str
    external_id: str
    display_name: str | None
    status: str
    credential_state: str
    capabilities: dict[str, Any]
    firmware_version: str | None
    last_heartbeat_at: str | None
    last_health: dict[str, Any]


class RevokeDeviceRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=512)


class OtaReleaseRequest(BaseModel):
    version: str = Field(min_length=1, max_length=64)
    artifact_url: str
    artifact_sha256: str = Field(min_length=64, max_length=64)
    signature: str | None = None
    signing_key_id: str | None = None
    verification_state: str = "pending_evidence"
    pending_evidence: dict[str, Any] | None = None


def _device_response(device: Any) -> DeviceResponse:
    return DeviceResponse(
        device_id=str(device.id),
        external_id=device.external_id,
        display_name=device.display_name,
        status=device.status,
        credential_state=device.credential_state,
        capabilities=device.capabilities_json or {},
        firmware_version=device.firmware_version,
        last_heartbeat_at=device.last_heartbeat_at.isoformat() if device.last_heartbeat_at else None,
        last_health=device.last_health_json or {},
    )


@router.post("/enrollment-credentials", response_model=EnrollmentCredentialResponse)
async def create_enrollment_credential(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    credential = await issue_enrollment_credential(db, user_id=uuid.UUID(user["sub"]))
    return EnrollmentCredentialResponse(
        credential_id=credential.credential_id,
        secret=credential.secret,
    )


@router.post("/enroll", response_model=DeviceEnrollResponse)
async def enroll_device_route(req: DeviceEnrollRequest, db: AsyncSession = Depends(get_db)):
    try:
        validate_secure_transport_config(req.ws_server_uri)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    device, credential = await enroll_device(
        db,
        credential_id=req.credential_id,
        secret=req.secret,
        external_id=req.external_id,
        display_name=req.display_name,
        capabilities=req.capabilities,
        firmware_version=req.firmware_version,
    )
    return DeviceEnrollResponse(
        device_id=str(device.id),
        credential=credential,
        credential_state=device.credential_state,
        status=device.status,
    )


@router.get("", response_model=list[DeviceResponse])
async def list_devices(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return [_device_response(device) for device in await list_devices_for_user(db, user_id=uuid.UUID(user["sub"]))]


@router.post("/{device_id}/revoke")
async def revoke_device_route(
    device_id: uuid.UUID,
    req: RevokeDeviceRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    devices = await list_devices_for_user(db, user_id=uuid.UUID(user["sub"]))
    if str(device_id) not in {str(device.id) for device in devices}:
        raise HTTPException(status_code=404, detail="Device not found")
    await revoke_device(db, device_id=device_id, reason=req.reason)
    return {"status": "revoked"}


@router.post("/ota/releases")
async def create_ota_release_route(
    req: OtaReleaseRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.get("role") not in {"operator", "admin"}:
        raise HTTPException(status_code=403, detail="Operator role required")
    release = await create_ota_release(
        db,
        version=req.version,
        artifact_url=req.artifact_url,
        artifact_sha256=req.artifact_sha256,
        signature=req.signature,
        signing_key_id=req.signing_key_id,
        verification_state=req.verification_state,
        pending_evidence=req.pending_evidence,
    )
    return {
        "release_id": str(release.id),
        "verification_state": release.verification_state,
        "pending_evidence": release.pending_evidence,
    }
