"""baseline schema

Snapshot of the schema as it existed under Base.metadata.create_all(),
before Alembic was introduced. Deployed DBs are adopted at this revision
(see app/db.py) rather than having these CREATE TABLEs re-run against them.

Revision ID: 0001
Revises:
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plex_base_url", sa.String(), nullable=False, server_default=""),
        sa.Column("plex_token", sa.String(), nullable=False, server_default=""),
        sa.Column("break_target_pct", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("break_skip_start_pct", sa.Float(), nullable=False, server_default="0.15"),
        sa.Column("break_skip_end_pct", sa.Float(), nullable=False, server_default="0.10"),
        sa.Column("break_lead_time_s", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("webpush_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("vapid_public_key", sa.String(), nullable=False, server_default=""),
        sa.Column("vapid_private_key", sa.String(), nullable=False, server_default=""),
        sa.Column("gotify_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("gotify_url", sa.String(), nullable=False, server_default=""),
        sa.Column("gotify_token", sa.String(), nullable=False, server_default=""),
        sa.Column("telegram_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("telegram_bot_token", sa.String(), nullable=False, server_default=""),
        sa.Column("telegram_chat_id", sa.String(), nullable=False, server_default=""),
    )

    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("endpoint", sa.String(), nullable=False),
        sa.Column("p256dh", sa.String(), nullable=False),
        sa.Column("auth", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("endpoint"),
    )

    op.create_table(
        "session_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_key", sa.String(), nullable=False),
        sa.Column("rating_key", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False, server_default=""),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("suggested_break_offset_ms", sa.Integer(), nullable=True),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("session_key"),
    )


def downgrade() -> None:
    op.drop_table("session_state")
    op.drop_table("push_subscriptions")
    op.drop_table("settings")
