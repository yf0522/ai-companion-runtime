"""merge production care, device, and memory migration heads

Revision ID: c9d0e1f2a3b4
Revises: a7b8c9d0e1f2, b8c9d0e1f2a3, f6a7b8c9d0e1
"""

from collections.abc import Sequence

revision: str = "c9d0e1f2a3b4"
down_revision: tuple[str, str, str] = (
    "a7b8c9d0e1f2",
    "b8c9d0e1f2a3",
    "f6a7b8c9d0e1",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
