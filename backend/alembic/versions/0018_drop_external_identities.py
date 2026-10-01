"""drop external_identities (OIDC removal)

Revision ID: 0018_drop_external_identities
Revises: 0017_camera_maintenance
Create Date: 2026-10-02
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


revision: str = "0018_drop_external_identities"
down_revision: str | Sequence[str] | None = (
    "0017_camera_maintenance"
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE = "external_identities"


def _table_exists() -> bool:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    return _TABLE in inspector.get_table_names()


def upgrade() -> None:
    if not _table_exists():
        return
    op.drop_table(_TABLE)


def downgrade() -> None:
    if _table_exists():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("issuer", sa.String(length=512), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "issuer",
            "subject",
            name="uq_external_identities_issuer_subject",
        ),
    )
    op.create_index(
        "ix_external_identities_user_id",
        _TABLE,
        ["user_id"],
    )
