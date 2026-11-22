"""video clips for the reels feed

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "video_clips",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("first_idx", sa.Integer(), nullable=False),
        sa.Column("last_idx", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(length=4), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("words", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("kanji", sa.String(length=400), nullable=False, server_default=""),
    )
    op.create_index("ix_video_clips_video_id", "video_clips", ["video_id"])
    op.add_column("videos", sa.Column("clips_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("videos", "clips_version")
    op.drop_index("ix_video_clips_video_id", table_name="video_clips")
    op.drop_table("video_clips")
