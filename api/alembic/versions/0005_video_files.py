"""video files: size, type, processing stage, subtitle source

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("videos", sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("videos", sa.Column("mime", sa.String(length=40), nullable=True))
    op.add_column("videos", sa.Column("stage", sa.String(length=24), nullable=True))
    op.add_column("videos", sa.Column("subtitle_source", sa.String(length=16), nullable=True))
    op.execute("UPDATE videos SET subtitle_source = 'file' WHERE source = 'youtube'")


def downgrade() -> None:
    for col in ("subtitle_source", "stage", "mime", "size_bytes"):
        op.drop_column("videos", col)
