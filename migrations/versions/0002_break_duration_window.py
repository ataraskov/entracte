"""replace break_target_pct/skip_start_pct/skip_end_pct with a min/max duration window

The old heuristic picked a chapter boundary near a fixed percentage of
runtime; the new one picks a boundary inside an absolute minute window.
There's no formula that maps one to the other (the old settings were
runtime-relative, the new ones aren't), so this drops the old columns and
adds the new ones at their model defaults rather than attempting a
numeric conversion. Existing users' break-duration settings reset to
default (20-60 min) and need to be re-saved from /settings.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("break_target_pct")
        batch_op.drop_column("break_skip_start_pct")
        batch_op.drop_column("break_skip_end_pct")
        batch_op.add_column(
            sa.Column(
                "break_min_duration_min", sa.Integer(), nullable=False, server_default="20"
            )
        )
        batch_op.add_column(
            sa.Column(
                "break_max_duration_min", sa.Integer(), nullable=False, server_default="60"
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("break_max_duration_min")
        batch_op.drop_column("break_min_duration_min")
        batch_op.add_column(
            sa.Column("break_target_pct", sa.Float(), nullable=False, server_default="0.5")
        )
        batch_op.add_column(
            sa.Column(
                "break_skip_start_pct", sa.Float(), nullable=False, server_default="0.15"
            )
        )
        batch_op.add_column(
            sa.Column("break_skip_end_pct", sa.Float(), nullable=False, server_default="0.10")
        )


