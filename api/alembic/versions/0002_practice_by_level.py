"""practice by level, attempts survive regeneration, repair romaji "no"

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- where each review card's content was taught -----------------------
    op.add_column("srs_cards", sa.Column("level", sa.String(length=8), nullable=True))
    op.add_column("srs_cards", sa.Column("unit_id", sa.Integer(), nullable=True))
    op.create_foreign_key("srs_cards_unit_id_fkey", "srs_cards", "units", ["unit_id"], ["id"], ondelete="SET NULL")
    op.create_index(op.f("ix_srs_cards_unit_id"), "srs_cards", ["unit_id"], unique=False)
    op.create_index("ix_srs_level", "srs_cards", ["user_id", "language_code", "level"], unique=False)
    op.execute("""
        UPDATE srs_cards c SET level = v.level, unit_id = v.unit_id
        FROM vocab_items v WHERE c.vocab_item_id = v.id
    """)
    op.execute("""
        UPDATE srs_cards c SET level = lv.cefr, unit_id = u.id
        FROM exercises e
        JOIN lessons l ON l.id = e.lesson_id
        JOIN units u ON u.id = l.unit_id
        JOIN levels lv ON lv.id = u.level_id
        WHERE c.card_type = 'mistake' AND c.source_ref = 'exercise:' || e.id::text
    """)

    # --- answer history survives a lesson being regenerated -----------------
    op.alter_column("exercise_attempts", "exercise_id", existing_type=sa.Integer(), nullable=True)
    op.drop_constraint("exercise_attempts_exercise_id_fkey", "exercise_attempts", type_="foreignkey")
    op.create_foreign_key("exercise_attempts_exercise_id_fkey", "exercise_attempts", "exercises",
                          ["exercise_id"], ["id"], ondelete="SET NULL")

    # --- YAML read the romaji "no" (の / ノ) as the boolean False -------------
    # Kana lessons rebuild themselves (their skeleton changed); mistake cards
    # copied the bad value, so repair those in place.
    op.execute("""
        UPDATE srs_cards SET
          front_json = replace(replace(front_json::text, '“False”', '“no”'), '"wrong": "False"', '"wrong": "no"')::jsonb,
          back_json = replace(replace(back_json::text, '“False”', '“no”'), '"answer": "False"', '"answer": "no"')::jsonb
        WHERE card_type = 'mistake' AND (front_json::text LIKE '%False%' OR back_json::text LIKE '%False%')
    """)
    # Mistake cards with nothing to answer (from early builds) can't be reviewed.
    op.execute("DELETE FROM srs_cards WHERE card_type = 'mistake' AND coalesce(back_json->>'answer', '') = ''")


def downgrade() -> None:
    op.drop_constraint("exercise_attempts_exercise_id_fkey", "exercise_attempts", type_="foreignkey")
    op.execute("DELETE FROM exercise_attempts WHERE exercise_id IS NULL")
    op.create_foreign_key("exercise_attempts_exercise_id_fkey", "exercise_attempts", "exercises",
                          ["exercise_id"], ["id"], ondelete="CASCADE")
    op.alter_column("exercise_attempts", "exercise_id", existing_type=sa.Integer(), nullable=False)
    op.drop_index("ix_srs_level", table_name="srs_cards")
    op.drop_index(op.f("ix_srs_cards_unit_id"), table_name="srs_cards")
    op.drop_constraint("srs_cards_unit_id_fkey", "srs_cards", type_="foreignkey")
    op.drop_column("srs_cards", "unit_id")
    op.drop_column("srs_cards", "level")
