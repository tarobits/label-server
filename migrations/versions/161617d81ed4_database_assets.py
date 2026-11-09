"""Database-backed assets; legacy files are imported under startup ownership."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGBLOB

revision = "161617d81ed4"
down_revision = "151516c70dc3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    blob = sa.LargeBinary().with_variant(LONGBLOB(), "mysql", "mariadb")
    op.create_table(
        "stored_assets",
        sa.Column("kind", sa.String(16), primary_key=True),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("content", blob, nullable=False),
        sa.Column("source", blob, nullable=True),
        sa.Column("checksum", sa.String(64), nullable=False),
    )
    op.create_table(
        "asset_imports",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("completed_at", sa.Double(), nullable=False),
    )


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM stored_assets LIMIT 1")).first():
        raise RuntimeError(
            "Database assets must be retained; restore a coordinated backup to downgrade"
        )
    op.drop_table("asset_imports")
    op.drop_table("stored_assets")
