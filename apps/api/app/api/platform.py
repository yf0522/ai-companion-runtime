from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.auth import get_current_user
from app.config.settings import settings
from app.runtime.readiness import assess_platform_readiness, operator_readiness_payload

router = APIRouter(prefix="/operator/platform", tags=["platform"])


def _require_operator(user: dict) -> None:
    if user.get("role") != "operator":
        raise HTTPException(status_code=403, detail="Operator role required")


@router.get("/readiness")
async def get_operator_platform_readiness(
    response: Response,
    user: dict = Depends(get_current_user),
):
    _require_operator(user)
    readiness = await assess_platform_readiness()
    response.headers["Cache-Control"] = "no-store"
    return operator_readiness_payload(readiness, settings)
