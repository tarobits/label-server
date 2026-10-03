"""Durable integration retry keys for single-job submission."""

import sqlalchemy as sa
from alembic import op

revision = "d804a91c3044"
down_revision = "c52d171ca013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_submissions",
        sa.Column("owner_id", sa.String(), primary_key=True),
        sa.Column("request_key", sa.String(), primary_key=True),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), sa.ForeignKey("print_jobs.id"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("job_submissions")
