"""videos: Watch library, subtitle lines, per-user position

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-22
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("language_code", sa.String(), sa.ForeignKey("languages.code"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("youtube_id", sa.String(length=32), nullable=True),
        sa.Column("file_key", sa.String(length=120), nullable=True),
        sa.Column("duration_s", sa.Integer(), nullable=True),
        sa.Column("level", sa.String(length=4), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("line_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("added_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_videos_language_code", "videos", ["language_code"])
    op.create_table(
        "video_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("raw", sa.Text(), nullable=False),
        sa.Column("ja", sa.Text(), nullable=True),
        sa.Column("kana", sa.Text(), nullable=True),
        sa.Column("en", sa.Text(), nullable=True),
        sa.Column("words", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.UniqueConstraint("video_id", "idx"),
    )
    op.create_index("ix_video_lines_video_id", "video_lines", ["video_id"])
    op.create_table(
        "video_progress",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("position_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("video_progress")
    op.drop_table("video_lines")
    op.drop_table("videos")
