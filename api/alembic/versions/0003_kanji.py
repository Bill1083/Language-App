"""kanji: per-character data (KANJIDIC2) and memory hooks

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-22
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kanji",
        sa.Column("char", sa.String(length=4), primary_key=True),
        sa.Column("meanings", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("on_readings", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("kun_readings", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("strokes", sa.Integer(), nullable=True),
        sa.Column("grade", sa.Integer(), nullable=True),
        sa.Column("jlpt", sa.Integer(), nullable=True),
        sa.Column("freq", sa.Integer(), nullable=True),
        sa.Column("parts", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("hook", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("kanji")
