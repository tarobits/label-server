"""Durable access-revocation holds for queued jobs.

Revision ID: c9e4136a7052
Revises: d4e18c327a90
"""

import sqlalchemy as sa
from alembic import op

revision = "c9e4136a7052"
down_revision = "d4e18c327a90"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "print_jobs",
        sa.Column("authorization_basis", sa.String(), nullable=False, server_default="print"),
    )
    # Pending-phase installations may already contain approved request jobs.
    connection = op.get_bind()
    for job_ids in connection.execute(
        sa.text("SELECT job_ids FROM print_requests WHERE status = 'approved'")
    ):
        import json

        for identifier in json.loads(job_ids[0]):
            connection.execute(
                sa.text(
                    "UPDATE print_jobs SET authorization_basis = 'request' WHERE id = :identifier"
                ),
                {"identifier": identifier},
            )
    op.create_table(
        "job_access_holds",
        sa.Column("job_id", sa.String(), sa.ForeignKey("print_jobs.id"), primary_key=True),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("held_at", sa.Double(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("resolved_at", sa.Double()),
        sa.Column("resolved_by", sa.String()),
    )


def downgrade():
    op.drop_table("job_access_holds")
    op.drop_column("print_jobs", "authorization_basis")
