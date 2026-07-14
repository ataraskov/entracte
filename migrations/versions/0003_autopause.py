"""add autopause_enabled to settings and paused_at to session_state

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "autopause_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
    with op.batch_alter_table("session_state") as batch_op:
        batch_op.add_column(sa.Column("paused_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("session_state") as batch_op:
        batch_op.drop_column("paused_at")
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("autopause_enabled")
