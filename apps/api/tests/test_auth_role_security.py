from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.auth import RegisterRequest


@pytest.mark.parametrize("role", ["operator", "admin", "ops", "superuser"])
def test_public_registration_rejects_privileged_roles(role: str):
    with pytest.raises(ValidationError):
        RegisterRequest(username="attacker", password="password123", role=role)


@pytest.mark.parametrize("role", ["elder", "family"])
def test_public_registration_allows_product_roles(role: str):
    request = RegisterRequest(username="member", password="password123", role=role)
    assert request.role == role
