from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
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


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str


def create_token(user_id: str, username: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": user_id,
        "username": username,
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


import uuid as _uuid

async def get_current_user_uuid(
    user: dict = Depends(get_current_user),
) -> _uuid.UUID:
    """FastAPI dependency: returns the authenticated user's ID as a validated uuid.UUID.

    Raises 401 if the sub claim is not a valid UUID.
    """
    try:
        return _uuid.UUID(user["sub"])
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid user identity in token")


@router.post("/auth/register", response_model=TokenResponse)
async def register(req: RegisterRequest):
    from app.db.session import async_session
    from app.db.models import User
    from sqlalchemy import select

    async with async_session() as db:
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
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        token = create_token(str(user.id), user.username)
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

        token = create_token(str(user.id), user.username)
        return TokenResponse(
            access_token=token,
            user_id=str(user.id),
            username=user.username,
        )
