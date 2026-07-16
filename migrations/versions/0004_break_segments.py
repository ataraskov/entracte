"""add break_resume_gap_min to settings and segment-tracking columns to session_state

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(
            sa.Column("break_resume_gap_min", sa.Integer(), nullable=False, server_default="15")
        )
    with op.batch_alter_table("session_state") as batch_op:
        batch_op.add_column(
            sa.Column("segment_start_ms", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column(
                "last_seen_view_offset_ms", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch_op.add_column(sa.Column("last_progress_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("notified_for_offset_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("session_state") as batch_op:
        batch_op.drop_column("notified_for_offset_ms")
        batch_op.drop_column("last_progress_at")
        batch_op.drop_column("last_seen_view_offset_ms")
        batch_op.drop_column("segment_start_ms")
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("break_resume_gap_min")
