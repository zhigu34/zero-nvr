"""add camera talk permission to built-in roles

Revision ID: 0012_camera_talk_permission
Revises: 0011_live_view_layouts
Create Date: 2026-09-21
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0012_camera_talk_permission"
down_revision: str | Sequence[str] | None = (
    "0011_live_view_layouts"
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    roles = bind.execute(
        sa.text(
            "SELECT id FROM roles "
            "WHERE name IN "
            "('Administrator','Operator')"
        )
    ).all()
    for (role_id,) in roles:
        exists = bind.execute(
            sa.text(
                "SELECT 1 FROM role_permissions "
                "WHERE role_id = :role_id "
                "AND permission = :permission"
            ),
            {
                "role_id": role_id,
                "permission": "camera.talk",
            },
        ).first()
        if exists is None:
            bind.execute(
                sa.text(
                    "INSERT INTO role_permissions "
                    "(role_id, permission) "
                    "VALUES (:role_id, :permission)"
                ),
                {
                    "role_id": role_id,
                    "permission": "camera.talk",
                },
            )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions "
            "WHERE permission = 'camera.talk' "
            "AND role_id IN ("
            "SELECT id FROM roles "
            "WHERE name IN "
            "('Administrator','Operator')"
            ")"
        )
    )
