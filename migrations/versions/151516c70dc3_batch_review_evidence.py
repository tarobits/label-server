"""Human misprint reports and administrator-controlled review evidence."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGTEXT

revision = "151516c70dc3"
down_revision = "141415b69cb2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "auth_settings",
        sa.Column(
            "batch_review_evidence", sa.String(16), nullable=False, server_default="optional"
        ),
    )
    text = sa.String().with_variant(LONGTEXT(), "mysql", "mariadb")
    op.create_table(
        "batch_reviews",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("batch_id", sa.String(128), sa.ForeignKey("batches.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("actor_name", text, nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.Column("reason", text, nullable=False),
        sa.Column("decisions", sa.JSON(), nullable=False),
        sa.Column("previous_outcomes", sa.JSON(), nullable=False),
        sa.Column("has_photo", sa.Boolean(), nullable=False),
        sa.Column("photo", text, nullable=True),
    )
    op.create_index("ix_batch_reviews_batch_id", "batch_reviews", ["batch_id"])


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM batch_reviews LIMIT 1")).first():
        raise RuntimeError(
            "Batch reviews contain audit evidence; restore a coordinated backup to downgrade"
        )
    op.drop_table("batch_reviews")
    op.drop_column("auth_settings", "batch_review_evidence")
