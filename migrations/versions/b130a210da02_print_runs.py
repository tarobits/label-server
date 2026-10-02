"""Durable previewed CSV runs and ordered job membership."""

import sqlalchemy as sa
from alembic import op

revision = "b130a210da02"
down_revision = "9c421df5a901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "print_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("request_key", sa.String(), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), sa.ForeignKey("tape_profiles.id"), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.Column("submitted_at", sa.Double(), nullable=True),
    )
    # SQLite can add a nullable REFERENCES column without rebuilding a table that
    # already has label_copies/batch history pointing to it.
    op.execute("ALTER TABLE print_jobs ADD COLUMN run_id VARCHAR REFERENCES print_runs(id)")
    op.add_column("print_jobs", sa.Column("run_position", sa.Integer(), nullable=True))
    op.add_column("print_jobs", sa.Column("source_row", sa.Integer(), nullable=True))
    op.create_index("ix_print_jobs_run_id", "print_jobs", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_print_jobs_run_id", table_name="print_jobs")
    op.drop_column("print_jobs", "source_row")
    op.drop_column("print_jobs", "run_position")
    op.drop_column("print_jobs", "run_id")
    op.drop_table("print_runs")
