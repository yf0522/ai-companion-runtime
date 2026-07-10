import secrets
import uuid
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from jose import jwt, JWTError
from passlib.context import CryptContext

from app.config.settings import settings

router = APIRouter(tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer_scheme = HTTPBearer(auto_error=False)


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    role: Literal["elder", "family"] = "elder"
    invite_token: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str


def create_token(user_id: str, username: str, role: str = "elder") -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> dict:
    """FastAPI dependency: extract and validate JWT from Authorization header.

    Returns the decoded payload dict with at least {"sub": "<user_id>", "username": "..."}.
    Raises 401 if missing or invalid.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing authorization token")
    payload = decode_token(credentials.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


async def get_current_user_uuid(
    user: dict = Depends(get_current_user),
) -> uuid.UUID:
    """FastAPI dependency: returns the authenticated user's ID as a validated uuid.UUID.

    Raises 401 if the sub claim is not a valid UUID.
    """
    try:
        return uuid.UUID(user["sub"])
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid user identity in token")


@router.post("/auth/register", response_model=TokenResponse)
async def register(req: RegisterRequest):
    from app.db.session import async_session
    from app.db.models import (
        BindingAuditEvent,
        CareCircleMember,
        FamilyBinding,
        HouseholdInvite,
        User,
    )
    from sqlalchemy import select

    requested_role = req.role
    if (
        requested_role == "elder"
        and settings.app_env.lower() == "production"
        and settings.controlled_elder_enrollment
    ):
        raise HTTPException(status_code=403, detail="Elder enrollment is managed by pilot operations")
    if requested_role == "family" and settings.app_env.lower() == "production" and not req.invite_token:
        raise HTTPException(
            status_code=403,
            detail="Family pilot registration requires a household invite",
        )
    async with async_session() as db:
        invite = None
        if requested_role == "family" and req.invite_token:
            from app.api.households import _hash_token

            invite = (
                await db.execute(
                    select(HouseholdInvite).where(
                        HouseholdInvite.token_hash == _hash_token(req.invite_token),
                        HouseholdInvite.status == "pending",
                        HouseholdInvite.expires_at > datetime.utcnow(),
                    ).with_for_update()
                )
            ).scalar_one_or_none()
            if invite is None:
                raise HTTPException(status_code=403, detail="Valid household invite required")
            if invite.invitee_email and req.email != invite.invitee_email:
                raise HTTPException(status_code=403, detail="Registration email must match the household invite")
        # Check if username exists
        existing = await db.execute(
            select(User).where(User.username == req.username)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Username already exists")

        user = User(
            username=req.username,
            email=req.email,
            password_hash=pwd_context.hash(req.password),
            role=requested_role,
        )
        db.add(user)
        await db.flush()

        if invite is not None:
            now = datetime.utcnow()
            invite.status = "accepted"
            invite.accepted_by_user_id = user.id
            invite.accepted_at = now
            invite.replay_nonce = f"registration:{user.id}"
            invite.updated_at = now
            binding = FamilyBinding(
                household_id=invite.household_id,
                family_user_id=user.id,
                elder_user_id=invite.elder_user_id,
                permissions=invite.permissions,
                status="active",
                consent_status="active",
                version=1,
            )
            db.add(binding)
            await db.flush()
            db.add(
                CareCircleMember(
                    household_id=invite.household_id,
                    user_id=user.id,
                    role="family",
                    status="active",
                    permissions=invite.permissions,
                )
            )
            db.add(
                BindingAuditEvent(
                    binding_id=binding.id,
                    household_id=invite.household_id,
                    actor_user_id=user.id,
                    event_type="binding.accepted_during_registration",
                    payload_json={"invite_id": str(invite.id)},
                )
            )
        await db.commit()
        await db.refresh(user)

        token = create_token(str(user.id), user.username, user.role)
        return TokenResponse(
            access_token=token,
            user_id=str(user.id),
            username=user.username,
        )


@router.post("/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    from app.db.session import async_session
    from app.db.models import User
    from sqlalchemy import select

    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.username == req.username)
        )
        user = result.scalar_one_or_none()

        if not user or not pwd_context.verify(req.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        token = create_token(str(user.id), user.username, user.role)
        return TokenResponse(
            access_token=token,
            user_id=str(user.id),
            username=user.username,
        )


_bind_codes: dict[str, tuple[str, datetime]] = {}


@router.post("/auth/generate-bind-code")
async def generate_bind_code(user: dict = Depends(get_current_user)):
    if settings.app_env.lower() == "production":
        raise HTTPException(status_code=410, detail="Legacy bind codes are disabled in production")
    if user.get("role") != "elder":
        raise HTTPException(status_code=403, detail="Only elder users can generate bind codes")
    code = f"{secrets.randbelow(1000000):06d}"
    _bind_codes[code] = (user["sub"], datetime.utcnow() + timedelta(minutes=10))
    return {"code": code, "expires_in_seconds": 600}


@router.post("/auth/bind-family")
async def bind_family(code: str, user: dict = Depends(get_current_user)):
    if settings.app_env.lower() == "production":
        raise HTTPException(status_code=410, detail="Legacy bind codes are disabled in production")
    if user.get("role") != "family":
        raise HTTPException(status_code=403, detail="Only family users can bind")
    entry = _bind_codes.get(code)
    if not entry:
        raise HTTPException(status_code=404, detail="Invalid or expired code")
    elder_user_id, expires_at = entry
    if datetime.utcnow() > expires_at:
        del _bind_codes[code]
        raise HTTPException(status_code=410, detail="Code expired")
    del _bind_codes[code]

    from app.db.models import BindingAuditEvent, FamilyBinding, Household
    from app.db.session import async_session

    async with async_session() as db:
        elder_uuid = uuid.UUID(elder_user_id)
        household = (
            await db.execute(select(Household).where(Household.elder_user_id == elder_uuid))
        ).scalar_one_or_none()
        if household is None:
            household = Household(elder_user_id=elder_uuid, name="Household")
            db.add(household)
            await db.flush()
        binding = FamilyBinding(
            household_id=household.id,
            family_user_id=uuid.UUID(user["sub"]),
            elder_user_id=elder_uuid,
            status="active",
            consent_status="active",
            version=1,
        )
        db.add(binding)
        await db.flush()
        db.add(
            BindingAuditEvent(
                binding_id=binding.id,
                household_id=household.id,
                actor_user_id=uuid.UUID(user["sub"]),
                event_type="binding.dev_code_accepted",
                payload_json={"dev_compatibility": True},
            )
        )
        await db.commit()
    return {"bound_to": elder_user_id}
